"""Turn the source PDFs into section-level chunks (data/chunks.json).

One chunk per numbered section ("3. Key Details"). Tables are kept whole and
rendered as Markdown so their rows never get separated from their headers.
Every chunk carries the metadata the app needs to cite it: document, page and
section.

    python -m scripts.ingest
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "data" / "pdfs"
OUT_PATH = ROOT / "data" / "chunks.json"

SECTION_RE = re.compile(r"^(\d+)\.\s+(\S.*)$")
# A gap between line tops larger than this many text heights starts a new paragraph.
# In these PDFs wrapped lines sit ~1.4 heights apart and paragraphs ~2.2.
PARAGRAPH_GAP = 1.8


def table_to_markdown(rows: list[list[str | None]]) -> str:
    rows = [[(cell or "").strip() for cell in row] for row in rows]
    header, *body = rows
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


def page_blocks(page) -> list[dict]:
    """Text lines outside tables plus one block per table, in reading order."""
    tables = page.find_tables()
    boxes = [t.bbox for t in tables]

    def inside_table(line) -> bool:
        return any(x0 <= line["x0"] and line["x1"] <= x1 and top <= line["top"] and line["bottom"] <= bottom
                   for x0, top, x1, bottom in boxes)

    blocks = [{"kind": "line", "top": line["top"], "height": line["bottom"] - line["top"], "text": line["text"].strip()}
              for line in page.extract_text_lines() if not inside_table(line) and line["text"].strip()]
    blocks += [{"kind": "table", "top": t.bbox[1], "text": table_to_markdown(t.extract())} for t in tables]
    return sorted(blocks, key=lambda b: b["top"])


def join_lines(lines: list[dict]) -> str:
    """Rejoin wrapped lines into paragraphs, splitting where the vertical gap is wider than a wrap."""
    if not lines:
        return ""
    paragraphs, current = [], [lines[0]["text"]]
    for prev, line in zip(lines, lines[1:]):
        if line["top"] - prev["top"] > prev["height"] * PARAGRAPH_GAP:
            paragraphs.append(" ".join(current))
            current = []
        current.append(line["text"])
    paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def parse_pdf(path: Path) -> tuple[dict, list[dict]]:
    doc_id = path.stem.removeprefix("Almamlaka_").lower()
    header: list[str] = []
    sections: list[dict] = []

    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            for block in page_blocks(page):
                match = SECTION_RE.match(block["text"]) if block["kind"] == "line" else None
                if match:
                    sections.append({"number": match[1], "title": match[2], "pages": [page_no], "parts": []})
                elif not sections:
                    header.append(block["text"])
                else:
                    section = sections[-1]
                    if page_no not in section["pages"]:
                        section["pages"].append(page_no)
                    section["parts"].append(block)

    if len(header) != 2:
        raise ValueError(f"{path.name}: expected a 2-line header (initiative, document title), got {header}")
    doc = {"doc_id": doc_id, "file": path.name, "initiative": header[0], "title": header[1]}

    chunks = []
    for section in sections:
        pieces, pending_lines = [], []
        for part in section["parts"]:
            if part["kind"] == "line":
                pending_lines.append(part)
            else:
                pieces.append(join_lines(pending_lines))
                pending_lines = []
                pieces.append(part["text"])
        pieces.append(join_lines(pending_lines))
        chunks.append({
            "id": f"{doc_id}#{section['number']}",
            "doc_id": doc_id,
            "doc_title": doc["title"],
            "file": path.name,
            "pages": section["pages"],
            "section": section["number"],
            "section_title": section["title"],
            "text": "\n\n".join(p for p in pieces if p),
        })
    return doc, chunks


def build() -> dict:
    docs, chunks = [], []
    for path in sorted(PDF_DIR.glob("*.pdf")):
        doc, doc_chunks = parse_pdf(path)
        docs.append(doc)
        chunks.extend(doc_chunks)
    return {"documents": docs, "chunks": chunks}


def main() -> None:
    data = build()
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for chunk in data["chunks"]:
        print(f"{chunk['id']:<20} p.{','.join(map(str, chunk['pages'])):<4} {chunk['section_title']}")
    print(f"\n{len(data['chunks'])} chunks from {len(data['documents'])} documents -> {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
