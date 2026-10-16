import fakeredis
import pytest

from app.ingest import parse_pdf
from app.kb import KnowledgeBase, UploadError
from tests.pdfgen import make_pdf
from tests.test_retrieval import HashEmbedder

ADDENDUM = make_pdf([[
    "Almamlaka TV Digital Expansion Initiative", "Vendor Contracts Addendum",
    "1. Streaming Vendor", "The streaming platform vendor is NovaStream, contracted for 24 months.",
    "2. Revised Budget", "The total project budget is now $2,750,000 after vendor negotiations.",
]])


class FakeDetector:
    """Stands in for the conflict-detection model call."""

    def __init__(self, conflicts):
        self.conflicts, self.calls = conflicts, 0

    def __call__(self, system, user_content, schema, **kwargs):
        self.calls += 1
        return {"conflicts": self.conflicts}


NEW_BUDGET_CONFLICT = {"id": "total-budget", "topic": "Total budget", "summary": "", "claims": [
    {"chunk_id": "project_overview#3", "statement": "$2.4M", "quote": "Total Approved Budget: $2,400,000"},
    {"chunk_id": "vendor_addendum#2", "statement": "$2.75M", "quote": "The total project budget is now $2,750,000"},
]}


def make_kb(redis=None, conflicts=()):
    detector = FakeDetector(list(conflicts))
    kb = KnowledgeBase(redis=redis, call=detector, model=HashEmbedder(), detect_in_background=False)
    return kb, detector


def test_startup_uses_the_committed_chunks_and_reviewed_conflicts():
    kb, detector = make_kb()
    kb.load()
    status = kb.status()
    assert [d["file"] for d in status["documents"]] == [
        "Almamlaka_Budget_Timeline.pdf", "Almamlaka_Project_Overview.pdf", "Almamlaka_Team_Governance.pdf"]
    assert status["conflict_state"] == "reviewed" and len(status["conflicts"]) == 3
    assert detector.calls == 0  # nothing changed: no model call


def test_upload_is_ingested_searchable_and_conflict_checked():
    kb, detector = make_kb(conflicts=[NEW_BUDGET_CONFLICT])
    swaps = []
    kb.on_change = swaps.append
    kb.load()
    status = kb.add("Vendor_Addendum.pdf", ADDENDUM)

    doc = next(d for d in status["documents"] if d["file"] == "Vendor_Addendum.pdf")
    assert doc["source"] == "upload" and doc["chunks"] == 2
    assert detector.calls == 1 and status["conflict_state"] == "detected"
    assert [c["topic"] for c in status["conflicts"]] == ["Total budget"]
    retriever = kb.answerer.retriever  # keyword ranking: the fake embedder's vectors are noise
    top = retriever.chunks[retriever.bm25_ranking("Who is the streaming platform vendor?")[0]]
    assert top["id"] == "vendor_addendum#1"
    assert swaps[-1] is kb.answerer  # the chat bot got the new answerer without a restart
    assert kb.pdf_bytes("Vendor_Addendum.pdf") == ADDENDUM


def test_unverifiable_detected_conflicts_are_dropped():
    fabricated = {**NEW_BUDGET_CONFLICT, "claims": [
        NEW_BUDGET_CONFLICT["claims"][0], {**NEW_BUDGET_CONFLICT["claims"][1], "quote": "budget is $9,000,000"}]}
    kb, _ = make_kb(conflicts=[fabricated])
    kb.load()
    assert kb.add("Vendor_Addendum.pdf", ADDENDUM)["conflicts"] == []


def test_removing_the_upload_restores_the_reviewed_state():
    kb, _ = make_kb()
    kb.load()
    kb.add("Vendor_Addendum.pdf", ADDENDUM)
    status = kb.remove("Vendor_Addendum.pdf")
    assert status["conflict_state"] == "reviewed" and len(status["documents"]) == 3


def test_uploads_survive_a_restart_with_redis():
    server = fakeredis.FakeServer()
    kb, _ = make_kb(redis=fakeredis.FakeRedis(server=server, decode_responses=True))
    kb.load()
    kb.add("Vendor_Addendum.pdf", ADDENDUM)

    restarted, detector = make_kb(redis=fakeredis.FakeRedis(server=server, decode_responses=True))
    restarted.load()
    assert "Vendor_Addendum.pdf" in [d["file"] for d in restarted.status()["documents"]]
    assert detector.calls == 0  # conflicts for these exact PDFs were cached


@pytest.mark.parametrize("name,data,message", [
    ("../../etc/passwd.pdf", ADDENDUM, None),  # path parts are stripped, not trusted
    ("notes.txt", ADDENDUM, "file name"),
    ("fake.pdf", b"hello", "not a PDF"),
    ("Almamlaka_Project_Overview.pdf", ADDENDUM, "already has that name"),
    ("blank.pdf", make_pdf([[]]), "No text"),
])
def test_upload_validation(name, data, message):
    kb, _ = make_kb()
    kb.load()
    if message is None:
        assert "passwd.pdf" in [d["file"] for d in kb.add(name, data)["documents"]]
    else:
        with pytest.raises(UploadError, match=message):
            kb.add(name, data)


def test_pdfs_without_numbered_sections_become_page_chunks():
    doc, chunks = parse_pdf("notes.pdf", make_pdf([["Board notes", "Meeting held on 3 May."], ["Second page."]]))
    assert doc["title"] == "Board notes"
    assert [(c["section"], c["section_title"], c["pages"]) for c in chunks] == [("", "Page 1", [1]), ("", "Page 2", [2])]
    assert "Meeting held on 3 May." in chunks[0]["text"]  # nothing lost to the title heuristic
