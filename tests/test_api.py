import pytest
from fastapi.testclient import TestClient

from app import main


class StubBot:
    """Stands in for ChatBot so the API tests need neither the model nor the network."""

    kind = "memory"

    def __init__(self):
        self.calls, self.resets = [], []
        self.sessions = self

    def chat(self, session_id, message, on_event=None):
        self.calls.append((session_id, message))
        if on_event:
            on_event({"type": "draft", "delta": "Hi", "attempt": 1})
        return {"session_id": session_id or "new-id", "status": "answered", "language": "en", "answer": "Hi [1].",
                "citations": [], "conflicts": [], "retrieved": ["x"], "intent": "question", "standalone_query": message}

    def reset(self, session_id):
        self.resets.append(session_id)


class StubKB:
    def __init__(self):
        self.added = []

    def status(self):
        return {"documents": [], "conflicts": [], "conflict_state": "reviewed"}

    def add(self, name, data):
        if not data.startswith(b"%PDF-"):
            raise main.UploadError("That file is not a PDF.")
        self.added.append(name)
        return self.status()

    def remove(self, name):
        raise main.UploadError("Only uploaded documents can be removed.")

    def pdf_bytes(self, name):
        return b"%PDF-uploaded" if name == "uploaded.pdf" else None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "build_state", lambda: (StubBot(), StubKB()))
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    with TestClient(main.app) as c:
        yield c


def test_admin_is_hidden_without_a_token(client):
    assert client.get("/admin").status_code == 404
    assert client.get("/api/admin/status").status_code == 404


def test_admin_requires_the_right_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    assert client.get("/admin").status_code == 200
    assert client.get("/api/admin/status").status_code == 401
    assert client.get("/api/admin/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = client.get("/api/admin/status", headers={"Authorization": "Bearer test-admin-token"})
    assert ok.status_code == 200 and ok.json()["conflict_state"] == "reviewed"


def test_admin_upload_passes_the_pdf_through_and_reports_errors(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    auth = {"Authorization": "Bearer test-admin-token"}
    ok = client.post("/api/admin/documents", content=b"%PDF-1.7 ...", headers={**auth, "X-Filename": "new.pdf"})
    assert ok.status_code == 200 and client.app.state.kb.added == ["new.pdf"]
    bad = client.post("/api/admin/documents", content=b"not a pdf", headers={**auth, "X-Filename": "x.pdf"})
    assert bad.status_code == 400 and bad.json()["detail"] == "That file is not a PDF."
    too_big = client.post("/api/admin/documents", content=b"%PDF-" + b"0" * (main.MAX_UPLOAD_BYTES + 1), headers=auth)
    assert too_big.status_code == 413
    assert client.delete("/api/admin/documents/x.pdf", headers=auth).status_code == 400


def test_uploaded_pdfs_are_served_too(client):
    assert client.get("/pdfs/uploaded.pdf").content == b"%PDF-uploaded"
    assert client.get("/pdfs/missing.pdf").status_code == 404


def test_index_and_static_assets(client):
    page = client.get("/")
    assert page.status_code == 200 and "Almamlaka TV Assistant" in page.text
    for asset in ("/static/app.js", "/static/styles.css", "/static/logo.png"):
        assert client.get(asset).status_code == 200


def test_assets_are_versioned_and_revalidated(client):
    page = client.get("/")
    assert f"/static/app.js?v={main.asset_version()}" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert client.get("/static/viewer.js").headers["cache-control"] == "no-cache"


def test_source_pdfs_are_served(client):
    pdf = client.get("/pdfs/Almamlaka_Budget_Timeline.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get("/pdfs/../.env").status_code == 404


def test_chat_returns_only_public_fields(client):
    body = client.post("/api/chat", json={"message": "Who leads the project?"}).json()
    assert set(body) == set(main.PUBLIC_FIELDS)
    assert body["session_id"] == "new-id"


def test_stream_sends_drafts_then_the_public_reply(client):
    import json
    response = client.post("/api/chat/stream", json={"message": "Who leads the project?"})
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["draft", "result"]
    assert set(events[-1]["reply"]) == set(main.PUBLIC_FIELDS)


def test_chat_passes_the_session_id_through(client):
    client.post("/api/chat", json={"message": "and Q4?", "session_id": "abc"})
    assert client.app.state.bot.calls[-1] == ("abc", "and Q4?")


def test_chat_rejects_bad_payloads(client):
    assert client.post("/api/chat", json={}).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 6000}).status_code == 422


def test_reset(client):
    assert client.post("/api/reset", json={"session_id": "abc"}).json() == {"ok": True}
    assert client.app.state.bot.resets == ["abc"]
