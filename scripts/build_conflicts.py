"""Re-find conflicts across the current chunks and write data/conflicts.json for review.

The app also runs detection by itself (in the background) when the PDFs change; this
script is for producing a reviewed, committed registry.

    python -m scripts.build_conflicts          # writes data/conflicts.json
    python -m scripts.build_conflicts --dry    # prints only
"""

from __future__ import annotations

import argparse
import json

from app.conflicts import CONFLICTS_PATH, find_conflicts
from app.ingest import CHUNKS_PATH, ROOT


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    data = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    kept, dropped = find_conflicts(data["chunks"])
    for status, group in (("kept", kept), ("DROPPED (unverifiable quote)", dropped)):
        for conflict in group:
            print(f"\n[{status}] {conflict['id']}: {conflict['topic']}\n  {conflict['summary']}")
            for cl in conflict["claims"]:
                print(f"  - {cl['chunk_id']}: {cl['statement']}\n      \"{cl['quote']}\"")

    if not args.dry:
        registry = {"fingerprint": data["fingerprint"], "conflicts": kept}
        CONFLICTS_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n{len(kept)} conflicts -> {CONFLICTS_PATH.relative_to(ROOT)}. Review before committing.")


if __name__ == "__main__":
    main()
