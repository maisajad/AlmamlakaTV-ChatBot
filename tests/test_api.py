import pytest
from fastapi.testclient import TestClient

from app import main


class StubBot:
    """Stands in for ChatBot so the API tests need neither the model nor the network."""

    def __init__(self):
        self.calls, self.resets = [], []
        self.sessions = self

    def chat(self, session_id, message):
        self.calls.append((session_id, message))
        return {"session_id": session_id or "new-id", "status": "answered", "language": "en", "answer": "Hi [1].",
                "citations": [], "conflicts": [], "retrieved": ["x"], "intent": "question", "standalone_query": message}

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


def test_chat_returns_only_public_fields(client):
    body = client.post("/api/chat", json={"message": "Who leads the project?"}).json()
    assert set(body) == set(main.PUBLIC_FIELDS)
    assert body["session_id"] == "new-id"


def test_chat_passes_the_session_id_through(client):
    client.post("/api/chat", json={"message": "and Q4?", "session_id": "abc"})
    assert client.app.state.bot.calls[-1] == ("abc", "and Q4?")


def test_chat_rejects_bad_payloads(client):
    assert client.post("/api/chat", json={}).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 6000}).status_code == 422


def test_reset(client):
    assert client.post("/api/reset", json={"session_id": "abc"}).json() == {"ok": True}
    assert client.app.state.bot.resets == ["abc"]
