import json
import time

import fakeredis
import pytest
import redis

from app import sessions
from app.answer import Answerer
from app.pipeline import ChatBot
from app.retrieval import load_chunks
from app.sessions import (MAX_TURNS, MemorySessionStore, RedisSessionStore, RedisUsageCap, TTL_SECONDS,
                          make_stores)
from tests.test_pipeline import ENGINEER, FakeModel, route
from tests.test_retrieval import BM25Retriever, HashEmbedder


@pytest.fixture
def server():
    return fakeredis.FakeServer()


def client_for(server):
    return fakeredis.FakeRedis(server=server, decode_responses=True)


def test_redis_session_survives_a_restart(server):
    store = RedisSessionStore(client_for(server))
    session = store.get(None)
    session.turns.append({"user": "Who leads the project?", "answer": "Sara", "status": "answered", "cited_ids": []})
    session.language = "ar"
    store.save(session)

    after_restart = RedisSessionStore(client_for(server))  # new process, same Redis
    restored = after_restart.get(session.id)
    assert restored.turns == session.turns and restored.language == "ar"
    assert 0 < client_for(server).ttl(f"session:{session.id}") <= TTL_SECONDS


def test_redis_store_trims_history_and_ignores_unknown_or_corrupt_ids(server):
    store = RedisSessionStore(client_for(server))
    session = store.get(None)
    session.turns = [{"user": str(i)} for i in range(MAX_TURNS + 4)]
    store.save(session)
    assert len(store.get(session.id).turns) == MAX_TURNS
    assert store.get("forged-id").id != "forged-id"
    client_for(server).set("session:broken", "{not json")
    assert store.get("broken").id != "broken"


def test_redis_usage_cap_is_shared_across_instances(server):
    now = time.time()
    a, b = RedisUsageCap(client_for(server), 3), RedisUsageCap(client_for(server), 3)
    assert [a.try_acquire(now), b.try_acquire(now), a.try_acquire(now), b.try_acquire(now)] == [True, True, True, False]


def test_unreachable_redis_falls_back_to_memory():
    store, _ = make_stores(10, url="redis://127.0.0.1:1/0")
    assert store.kind == "memory"


def test_memory_store_when_no_url():
    assert make_stores(10, url="")[0].kind == "memory"


def test_conversation_continues_across_an_app_restart(server, monkeypatch):
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, url, **kw: client_for(server)))
    retriever = BM25Retriever(load_chunks(), model=HashEmbedder())

    def bot(model):
        return ChatBot(answerer=Answerer(retriever=retriever, conflicts=[], call=model), call=model,
                       redis_url="redis://render-key-value:6379")

    first = FakeModel(routes=[route("question", "Who is the lead engineer?")], answers=[ENGINEER])
    session_id = bot(first).chat(None, "Who is the lead engineer?")["session_id"]

    second = FakeModel(routes=[route("question", "Which department is Omar Fayez in?")],
                       answers=[{**ENGINEER, "answer": "Engineering [1]."}])
    restarted = bot(second)  # a fresh ChatBot: nothing in memory
    assert restarted.sessions.kind == "redis"
    result = restarted.chat(session_id, "Which department is he in?")
    assert result["session_id"] == session_id
    assert "<user>Who is the lead engineer?</user>" in second.route_prompts[0]
    assert "team_governance#1" in result["retrieved"]  # previous answer's sources carried over too
