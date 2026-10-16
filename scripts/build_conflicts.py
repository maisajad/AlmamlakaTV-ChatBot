"""Find conflicting facts across the chunks once, offline, and save them to data/conflicts.json.

The file is reviewed by a person and committed. At query time it does two things:
retrieving one side of a conflict pulls in the other sides, and the prompt gets a
<known_discrepancies> hint, so flagging a conflict doesn't depend on the model
noticing it on the fly.

    python -m scripts.build_conflicts          # writes data/conflicts.json
    python -m scripts.build_conflicts --dry    # prints only
"""

from __future__ import annotations

import argparse
import json

from app.answer import CONFLICTS_PATH
from app.llm import structured_call
from app.prompts import CONFLICTS_SYSTEM
from app.retrieval import ROOT, load_chunks
from app.verify import quote_supported

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    chunks = {c["id"]: c for c in load_chunks()}
    corpus = "\n\n".join(f'<chunk id="{c["id"]}" document="{c["doc_title"]}" section="{c["section"]}. '
                         f'{c["section_title"]}">\n{c["text"]}\n</chunk>' for c in chunks.values())
    result = structured_call(CONFLICTS_SYSTEM, corpus, SCHEMA, effort="high", max_tokens=16000)

    kept = []
    for conflict in result["conflicts"]:
        bad = [cl for cl in conflict["claims"]
               if cl["chunk_id"] not in chunks or not quote_supported(cl["quote"], chunks[cl["chunk_id"]]["text"])]
        status = "DROPPED (unverifiable quote)" if bad or len(conflict["claims"]) < 2 else "kept"
        print(f"\n[{status}] {conflict['id']}: {conflict['topic']}\n  {conflict['summary']}")
        for cl in conflict["claims"]:
            print(f"  - {cl['chunk_id']}: {cl['statement']}\n      \"{cl['quote']}\"")
        if status == "kept":
            kept.append(conflict)

    if not args.dry:
        CONFLICTS_PATH.write_text(json.dumps({"conflicts": kept}, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        print(f"\n{len(kept)} conflicts -> {CONFLICTS_PATH.relative_to(ROOT)}. Review before committing.")


if __name__ == "__main__":
    main()
