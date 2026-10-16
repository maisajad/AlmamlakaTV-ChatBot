import json
import re
from collections import Counter

import pdfplumber
import pytest

from scripts.ingest import OUT_PATH, PDF_DIR, build


@pytest.fixture(scope="module")
def data():
    return build()


@pytest.fixture(scope="module")
def chunks(data):
    return {c["id"]: c for c in data["chunks"]}


def test_committed_chunks_are_up_to_date(data):
    assert json.loads(OUT_PATH.read_text(encoding="utf-8")) == data, "run: python -m scripts.ingest"


def test_one_chunk_per_numbered_section(chunks):
    assert len(chunks) == 16
    assert [c["section_title"] for c in chunks.values() if c["doc_id"] == "budget_timeline"] == [
        "Quarterly Budget Allocation", "Budget Notes", "Project Timeline", "Risk Notes"]
    assert all(c["text"].strip() for c in chunks.values())


def test_page_numbers(chunks):
    assert chunks["project_overview#3"]["pages"] == [1]
    assert chunks["project_overview#4"]["pages"] == [2]
    assert chunks["budget_timeline#3"]["pages"] == [2]
    assert chunks["team_governance#3"]["pages"] == [1]


def test_table_rows_stay_intact(chunks):
    assert "| Public launch | March 15, 2027 |" in chunks["budget_timeline#3"]["text"]
    assert "| QA & testing | Mar 1 - Mar 20, 2027 |" in chunks["budget_timeline#3"]["text"]
    assert "| Q2 2027 | $500,000 | $150,000 | $70,000 | $720,000 |" in chunks["budget_timeline#1"]["text"]
    assert "| Omar Fayez | Lead Engineer | Engineering |" in chunks["team_governance#1"]["text"]


def test_conflicting_facts_land_in_the_expected_chunks(chunks):
    assert "Total Approved Budget: $2,400,000" in chunks["project_overview#3"]["text"]
    assert "$2,600,000" in chunks["budget_timeline#2"]["text"]
    assert "Planned Launch Date: March 15, 2027" in chunks["project_overview#3"]["text"]
    assert "April 1, 2027" in chunks["team_governance#3"]["text"]


def test_paragraphs_and_label_lines_are_kept_apart(chunks):
    assert chunks["project_overview#3"]["text"].count("\n\n") == 3
    assert chunks["project_overview#4"]["text"].count("\n\n") == 1


def words(text: str) -> Counter:
    return Counter(w for w in re.split(r"[\s|]+", text) if w and not re.fullmatch(r"-+", w))


def test_every_word_in_the_pdfs_appears_exactly_once(data):
    pdf_words = Counter()
    for path in sorted(PDF_DIR.glob("*.pdf")):
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                pdf_words += words(page.extract_text())

    chunk_words = Counter()
    for doc in data["documents"]:
        chunk_words += words(doc["initiative"]) + words(doc["title"])
    for chunk in data["chunks"]:
        chunk_words += words(f"{chunk['section']}. {chunk['section_title']}") + words(chunk["text"])

    assert chunk_words == pdf_words
