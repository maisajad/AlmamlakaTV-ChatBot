import pytest
from fastapi.testclient import TestClient

from app import main


class StubBot:
    """Stands in for ChatBot so the API tests need neither the model nor the network."""

    def __init__(self):
        self.calls, self.resets = [], []
        self.sessions = self

    def chat(self, session_id, message, on_event=None):
        self.calls.append((session_id, message))
        if on_event:
            on_event({"type": "step", "step": "understand", "status": "active"})
            on_event({"type": "draft", "delta": "Hi", "attempt": 1})
        return {"session_id": session_id or "new-id", "status": "answered", "language": "en", "answer": "Hi [1].",
                "citations": [], "conflicts": [], "trace": {"model": "m"}, "retrieved": ["x"], "intent": "question",
                "standalone_query": message}

    def reset(self, session_id):
        self.resets.append(session_id)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "ChatBot", StubBot)
    with TestClient(main.app) as c:
        yield c


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


def test_stream_sends_steps_drafts_then_the_public_reply(client):
    import json
    response = client.post("/api/chat/stream", json={"message": "Who leads the project?"})
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["step", "draft", "result"]
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
