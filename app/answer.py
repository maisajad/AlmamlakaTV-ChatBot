"""Single-turn answering: retrieve -> ask Claude for a cited JSON answer -> verify in code.

If verification fails the model gets one retry with the problems spelled out; if it
fails again the user gets "I don't have that information" rather than an
unverifiable answer.
"""

from __future__ import annotations

import json
import logging
from html import escape
from pathlib import Path
from typing import Callable

from app import llm
from app.language import NAMES, detect_language, reply, script_language
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

        With `on_event`, the answer text is streamed as {"type": "draft"} events while it is
        written. The returned result is the same either way, and only it is verified; drafts
        are shown to the user as unverified."""
        emit = on_event or no_events
        language = language or detect_language(question)
        queries = [question] + ([standalone] if standalone and standalone != question else [])
        hits = self.retriever.search(queries, k=TOP_K, include_ids=include_ids)
        allowed = {h.chunk["id"]: h.chunk for h in hits}
        base = {"language": language, "retrieved": list(allowed), "citations": [], "conflicts": []}

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
        for attempt in range(1, MAX_ATTEMPTS + 1):
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
                return {**base, "status": "error", "answer": reply("error", language)}

            if raw["status"] != "answered":
                return {**base, "status": raw["status"], "answer": reply(raw["status"], language)}

            verdict = verify(raw, allowed)
            if script_language(raw["answer"], default=language) != language:
                verdict.problems.append(f"the answer must be written in {NAMES[language]}")
            for conflict in verdict.conflicts:
                text = " ".join([conflict["topic"]] + [cl["statement"] for cl in conflict["claims"]])
                if script_language(text, default=language) != language:
                    verdict.problems.append(f"conflict topics and statements must be written in {NAMES[language]}")
                    break
            if verdict.ok:
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
            feedback = ("\n\n<verification_feedback>\nYour previous answer was rejected by an automatic check:\n"
                        + "\n".join(f"- {p}" for p in verdict.problems)
                        + "\nAnswer again, fixing these problems and citing only verbatim text from the documents above. If the documents "
                          "do not support an answer, use status not_in_documents.\n</verification_feedback>")

        return {**base, "status": "not_in_documents", "answer": reply("not_in_documents", language)}
