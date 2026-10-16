"""Rebuild data/chunks.json from the PDFs in data/pdfs.

The app does this by itself at startup whenever the PDFs change; this script is for
inspecting the result or committing a fresh chunks.json.

    python -m scripts.ingest
"""

from __future__ import annotations

import json

from app.ingest import CHUNKS_PATH, ROOT, build


def main() -> None:
    data = build()
    CHUNKS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for chunk in data["chunks"]:
        print(f"{chunk['id']:<20} p.{','.join(map(str, chunk['pages'])):<4} {chunk['section_title']}")
    print(f"\n{len(data['chunks'])} chunks from {len(data['documents'])} documents -> {CHUNKS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
