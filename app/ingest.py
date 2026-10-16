"""PDFs -> section-level chunks, each carrying the metadata needed to cite it.

One chunk per numbered section ("3. Key Details"), with tables kept whole as Markdown so
their rows never get separated from their headers. PDFs without numbered sections fall
back to one chunk per page. Runs at startup when the PDFs change, and on admin upload;
`python -m scripts.ingest` rebuilds data/chunks.json by hand.
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "data" / "pdfs"
CHUNKS_PATH = ROOT / "data" / "chunks.json"

SECTION_RE = re.compile(r"^(\d+)\.\s+(\S.*)$")
# A gap between line tops larger than this many text heights starts a new paragraph.
# In these PDFs wrapped lines sit ~1.4 heights apart and paragraphs ~2.2.
PARAGRAPH_GAP = 1.8
MAX_HEADER_LINES = 2       # short lines before the first section: initiative + document title
MAX_CHUNK_CHARS = 2500     # longer sections are split on paragraph boundaries

Source = tuple[str, bytes]  # (file name, PDF bytes)


def repo_sources(pdf_dir: Path = PDF_DIR) -> list[Source]:
    return [(p.name, p.read_bytes()) for p in sorted(pdf_dir.glob("*.pdf"))]


def fingerprint(sources: list[Source]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(sources):
        digest.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()[:16]


def doc_id_for(name: str) -> str:
    stem = Path(name).stem.removeprefix("Almamlaka_").lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "document"


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


def render_parts(parts: list[dict]) -> str:
    pieces, pending = [], []
    for part in parts:
        if part["kind"] == "line":
            pending.append(part)
        else:
            pieces.append(join_lines(pending))
            pending = []
            pieces.append(part["text"])
    pieces.append(join_lines(pending))
    return "\n\n".join(p for p in pieces if p)


def split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    out, current = [], ""
    for para in text.split("\n\n"):
        if current and len(current) + len(para) > MAX_CHUNK_CHARS:
            out.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    return out + [current]


def parse_pdf(name: str, data: bytes) -> tuple[dict, list[dict]]:
    import pdfplumber  # only needed when (re)ingesting

    doc_id = doc_id_for(name)
    preamble: list[dict] = []   # blocks before the first numbered section
    sections: list[dict] = []
    pages: list[list[dict]] = []

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            blocks = page_blocks(page)
            pages.append(blocks)
            for block in blocks:
                match = SECTION_RE.match(block["text"]) if block["kind"] == "line" else None
                if match:
                    sections.append({"number": match[1], "title": match[2], "pages": [page_no], "parts": []})
                elif not sections:
                    preamble.append({**block, "page": page_no})
                else:
                    section = sections[-1]
                    if page_no not in section["pages"]:
                        section["pages"].append(page_no)
                    section["parts"].append(block)

    # The first short lines are the header (initiative, document title); anything after that and
    # before section 1 is real content and becomes an "Introduction" chunk.
    # Without numbered sections there is no way to tell a second header line from content, so
    # only the first line is taken as the title, and all text stays in the chunks.
    header = []
    for block in preamble[:MAX_HEADER_LINES if sections else 1]:
        if block["kind"] != "line" or len(block["text"]) > 90:
            break
        header.append(block["text"])
    intro = preamble[len(header):]
    title = header[-1] if header else Path(name).stem.replace("_", " ")
    doc = {"doc_id": doc_id, "file": name, "initiative": header[0] if len(header) == 2 else "", "title": title}

    if sections:
        raw = [{"section": s["number"], "title": s["title"], "pages": s["pages"], "text": render_parts(s["parts"])}
               for s in sections]
        if intro:
            raw.insert(0, {"section": "", "title": "Introduction", "pages": sorted({b["page"] for b in intro}),
                           "text": render_parts(intro)})
    else:  # no numbered sections: one chunk per page, every line kept
        raw = [{"section": "", "title": f"Page {page_no}", "pages": [page_no], "text": render_parts(blocks)}
               for page_no, blocks in enumerate(pages, 1)]

    chunks = []
    for entry in raw:
        if not entry["text"]:
            continue
        key = entry["section"] or re.sub(r"\W+", "-", entry["title"].lower()).strip("-")
        for i, part in enumerate(split_long(entry["text"]), 1):
            chunks.append({
                "id": f"{doc_id}#{key}" + (f".{i}" if i > 1 else ""),
                "doc_id": doc_id,
                "doc_title": doc["title"],
                "file": name,
                "pages": entry["pages"],
                "section": entry["section"],
                "section_title": entry["title"] + (f" (part {i})" if i > 1 else ""),
                "text": part,
            })
    return doc, chunks


def build(sources: list[Source] | None = None) -> dict:
    sources = repo_sources() if sources is None else sources
    docs, chunks = [], []
    for name, data in sorted(sources):
        doc, doc_chunks = parse_pdf(name, data)
        docs.append(doc)
        chunks.extend(doc_chunks)
    return {"fingerprint": fingerprint(sources), "documents": docs, "chunks": chunks}
