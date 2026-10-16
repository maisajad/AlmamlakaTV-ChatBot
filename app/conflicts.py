"""Find facts the documents disagree on, once per set of PDFs.

At query time the result does two things: retrieving one side of a conflict pulls in the
other sides, and the prompt gets a <known_discrepancies> hint, so flagging a conflict
doesn't depend on the model noticing it on the fly. Every claim must quote its chunk
verbatim, or the conflict is dropped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from app import llm
from app.ingest import ROOT
from app.prompts import CONFLICTS_SYSTEM
from app.verify import quote_supported

CONFLICTS_PATH = ROOT / "data" / "conflicts.json"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["conflicts"],
    "properties": {"conflicts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "topic", "summary", "claims"],
        "properties": {
            "id": {"type": "string", "description": "short kebab-case id, e.g. total-budget"},
            "topic": {"type": "string"},
            "summary": {"type": "string"},
            "claims": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["chunk_id", "statement", "quote"],
                "properties": {"chunk_id": {"type": "string"}, "statement": {"type": "string"},
                               "quote": {"type": "string"}},
            }},
        },
    }}},
}


def load_registry(path: Path = CONFLICTS_PATH) -> dict:
    """{"fingerprint": ..., "conflicts": [...]}; fingerprint says which PDFs it was reviewed for."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"fingerprint": None, "conflicts": []}


def valid_for(conflicts: list[dict], chunks: list[dict]) -> list[dict]:
    """Conflicts whose every claim still points at an existing chunk and quotes it verbatim."""
    by_id = {c["id"]: c for c in chunks}
    return [c for c in conflicts if len(c["claims"]) >= 2 and all(
        cl["chunk_id"] in by_id and quote_supported(cl.get("quote", ""), by_id[cl["chunk_id"]]["text"])
        for cl in c["claims"])]


def find_conflicts(chunks: list[dict], call: Callable[..., dict] = llm.structured_call) -> tuple[list[dict], list[dict]]:
    """Ask Claude for discrepancies across all chunks; returns (kept, dropped)."""
    from app.answer import section_label
    corpus = "\n\n".join(f'<chunk id="{c["id"]}" document="{c["doc_title"]}" section="{section_label(c)}">'
                         f'\n{c["text"]}\n</chunk>' for c in chunks)
    result = call(CONFLICTS_SYSTEM, corpus, SCHEMA, effort="high", max_tokens=16000, model=llm.CONFLICT_MODEL)
    kept = valid_for(result["conflicts"], chunks)
    dropped = [c for c in result["conflicts"] if c not in kept]
    return kept, dropped
