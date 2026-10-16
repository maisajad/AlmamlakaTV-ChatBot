"""Single-turn answering: retrieve -> ask Claude for a cited JSON answer -> verify in code.

If verification fails the model gets one retry with the problems spelled out; if it
fails again the user gets "I don't have that information" rather than an
unverifiable answer.
"""

from __future__ import annotations

import json
import logging
import time
from html import escape
from pathlib import Path
from typing import Callable

from app import llm
from app.language import NAMES, detect_language, reply
from app.prompts import ANSWER_SYSTEM
from app.retrieval import ROOT, Hit, Retriever, load_chunks
from app.verify import verify

log = logging.getLogger(__name__)

CONFLICTS_PATH = ROOT / "data" / "conflicts.json"
TOP_K = 4
MAX_ATTEMPTS = 2

ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "answer", "citations", "conflicts"],
    "properties": {
        "status": {"type": "string", "enum": ["answered", "not_in_documents", "out_of_scope"]},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["chunk_id", "quote"],
            "properties": {"chunk_id": {"type": "string"}, "quote": {"type": "string"}},
        }},
        "conflicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["topic", "claims"],
            "properties": {
                "topic": {"type": "string"},
                "claims": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["chunk_id", "statement"],
                    "properties": {"chunk_id": {"type": "string"}, "statement": {"type": "string"}},
                }},
            },
        }},
    },
}


def load_conflicts(path: Path = CONFLICTS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["conflicts"] if path.exists() else []


def render_documents(hits: list[Hit]) -> str:
    docs = []
    for hit in hits:
        c = hit.chunk
        pages = ", ".join(map(str, c["pages"]))
        docs.append(f'<document id="{c["id"]}" source="{escape(c["doc_title"])}" page="{pages}" '
                    f'section="{c["section"]}. {escape(c["section_title"])}">\n{c["text"]}\n</document>')
    return "<documents>\n" + "\n".join(docs) + "\n</documents>"


def render_discrepancies(conflicts: list[dict], chunk_ids: set[str]) -> str:
    relevant = [c for c in conflicts if any(cl["chunk_id"] in chunk_ids for cl in c["claims"])]
    if not relevant:
        return ""
    lines = [f"- {c['topic']}: " + "; ".join(f"{cl['chunk_id']} says {cl['statement']}" for cl in c["claims"])
             for c in relevant]
    return "<known_discrepancies>\n" + "\n".join(lines) + "\n</known_discrepancies>"


def citation_view(chunk: dict) -> dict:
    return {"chunk_id": chunk["id"], "doc_title": chunk["doc_title"], "file": chunk["file"],
            "pages": chunk["pages"], "section": chunk["section"], "section_title": chunk["section_title"]}


Events = Callable[[dict], None]


def no_events(event: dict) -> None:
    pass


class Answerer:
    def __init__(self, retriever: Retriever | None = None, conflicts: list[dict] | None = None,
                 call: Callable[..., dict] = llm.structured_call,
                 stream_call: Callable[..., dict] = llm.streamed_call):
        self.conflicts = load_conflicts() if conflicts is None else conflicts
        self.retriever = retriever or Retriever(
            load_chunks(), related_groups=[[cl["chunk_id"] for cl in c["claims"]] for c in self.conflicts])
        self.call = call
        self.stream_call = stream_call

    def answer(self, question: str, language: str | None = None, standalone: str | None = None,
               include_ids: list[str] = (), on_event: Events | None = None) -> dict:
        """`question` is the user's own message; `standalone` its self-contained English
        rewrite (for follow-ups); `include_ids` chunks to keep in view from the previous turn.

        With `on_event`, the reply is streamed: progress steps and the draft answer text are
        reported as they happen. The returned result is the same either way, and only it is
        verified; drafts are shown to the user as unverified."""
        emit = on_event or no_events
        language = language or detect_language(question)
        queries = [question] + ([standalone] if standalone and standalone != question else [])

        emit({"type": "step", "step": "search", "status": "active"})
        t0 = time.perf_counter()
        hits = self.retriever.search(queries, k=TOP_K, include_ids=include_ids)
        search_ms = round((time.perf_counter() - t0) * 1000)
        allowed = {h.chunk["id"]: h.chunk for h in hits}
        triggered = [c["topic"] for c in self.conflicts if any(cl["chunk_id"] in allowed for cl in c["claims"])]
        trace = {
            "retrieval": [{**citation_view(h.chunk), "bm25_rank": h.bm25_rank, "dense_rank": h.dense_rank, "via": h.via}
                          for h in hits],
            "known_conflicts": triggered,
            "attempts": [],
            "model": llm.MODEL,
            "timings_ms": {"search": search_ms},
        }
        emit({"type": "step", "step": "search", "status": "done",
              "detail": {"sections": len(hits), "documents": len({h.chunk["doc_id"] for h in hits}),
                         "known_conflicts": triggered}})
        base = {"language": language, "retrieved": list(allowed), "citations": [], "conflicts": [], "trace": trace}

        prompt = "\n\n".join(p for p in [
            render_documents(hits),
            render_discrepancies(self.conflicts, set(allowed)),
            f"<response_language>{NAMES[language]}</response_language>",
            f"<question>\n{escape(question, quote=False)}\n</question>",
            (f"<standalone_question>\n{escape(standalone, quote=False)}\n</standalone_question>\n"
             "(The user's question rewritten using earlier turns of the conversation. Answer the user's "
             "question as this rewrite interprets it.)") if len(queries) > 1 else "",
        ] if p)

        feedback = ""
        t0 = time.perf_counter()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            emit({"type": "step", "step": "write", "status": "active", "detail": {"attempt": attempt}})
            try:
                if on_event:
                    drafts, sent = llm.JsonFieldStreamer("answer"), [0]

                    def on_text(chunk: str, attempt=attempt) -> None:
                        text = drafts.feed(chunk)
                        if len(text) > sent[0]:  # send only the new characters
                            emit({"type": "draft", "delta": text[sent[0]:], "attempt": attempt})
                            sent[0] = len(text)

                    raw = self.stream_call(ANSWER_SYSTEM, prompt + feedback, ANSWER_SCHEMA, on_text=on_text)
                else:
                    raw = self.call(ANSWER_SYSTEM, prompt + feedback, ANSWER_SCHEMA)
            except llm.LLMError:
                trace["timings_ms"]["answer"] = round((time.perf_counter() - t0) * 1000)
                return {**base, "status": "error", "answer": reply("error", language)}
            emit({"type": "step", "step": "write", "status": "done"})

            if raw["status"] != "answered":
                trace["attempts"].append({"status": raw["status"], "problems": []})
                trace["timings_ms"]["answer"] = round((time.perf_counter() - t0) * 1000)
                return {**base, "status": raw["status"], "answer": reply(raw["status"], language)}

            emit({"type": "step", "step": "verify", "status": "active", "detail": {"citations": len(raw["citations"])}})
            verdict = verify(raw, allowed)
            if detect_language(raw["answer"], default=language) != language:
                verdict.problems.append(f"the answer must be written in {NAMES[language]}")
            for conflict in verdict.conflicts:
                text = " ".join([conflict["topic"]] + [cl["statement"] for cl in conflict["claims"]])
                if detect_language(text, default=language) != language:
                    verdict.problems.append(f"conflict topics and statements must be written in {NAMES[language]}")
                    break
            trace["attempts"].append({"status": "answered", "citations": len(raw["citations"]), "problems": verdict.problems})
            if verdict.ok:
                trace["timings_ms"]["answer"] = round((time.perf_counter() - t0) * 1000)
                emit({"type": "step", "step": "verify", "status": "done",
                      "detail": {"citations": len(raw["citations"]), "conflicts": len(verdict.conflicts)}})
                return {
                    **base,
                    "status": "answered",
                    "answer": raw["answer"],
                    "citations": [{"n": n, "quote": c["quote"], **citation_view(allowed[c["chunk_id"]])}
                                  for n, c in enumerate(raw["citations"], 1)],
                    "conflicts": [{"topic": c["topic"],
                                   "claims": [{"statement": cl["statement"], **citation_view(allowed[cl["chunk_id"]])}
                                              for cl in c["claims"]]}
                                  for c in verdict.conflicts],
                }
            log.warning("attempt %d failed verification: %s", attempt, verdict.problems)
            emit({"type": "step", "step": "verify", "status": "failed", "detail": {"problems": len(verdict.problems)}})
            feedback = ("\n\n<verification_feedback>\nYour previous answer was rejected by an automatic check:\n"
                        + "\n".join(f"- {p}" for p in verdict.problems)
                        + "\nAnswer again, fixing these problems and citing only verbatim text from the documents above. If the documents "
                          "do not support an answer, use status not_in_documents.\n</verification_feedback>")

        trace["timings_ms"]["answer"] = round((time.perf_counter() - t0) * 1000)
        return {**base, "status": "not_in_documents", "answer": reply("not_in_documents", language)}
