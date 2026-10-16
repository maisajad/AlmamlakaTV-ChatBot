"""Conversation sessions and usage limits, in Redis when REDIS_URL is set, else in memory.

History lives on the server, keyed by an opaque session id, so a client cannot forge
earlier assistant turns. With Redis (e.g. Render Key Value), conversations survive the
web service restarting or sleeping; in memory, a restart starts every conversation over.
If Redis is configured but unreachable, the app falls back to memory rather than going down.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field

log = logging.getLogger(__name__)

MAX_TURNS = 6            # turns of history kept per session
TTL_SECONDS = 30 * 60    # idle sessions expire
MAX_SESSIONS = 2000      # in-memory store: oldest dropped beyond this
RATE_LIMIT = 15          # messages ...
RATE_WINDOW = 60         # ... per this many seconds, per session


@dataclass
class Session:
    id: str
    turns: list = field(default_factory=list)
    message_times: list = field(default_factory=list)  # wall-clock seconds, so they survive restarts
    language: str = "en"

    def rate_limited(self, now: float) -> bool:
        recent = [t for t in self.message_times if now - t < RATE_WINDOW]
        return len(recent) >= RATE_LIMIT

    def record_message(self, now: float) -> None:
        self.message_times = [t for t in self.message_times if now - t < RATE_WINDOW] + [now]

    def trim(self) -> None:
        self.turns = self.turns[-MAX_TURNS:]
        self.message_times = self.message_times[-RATE_LIMIT:]


def new_session() -> Session:
    return Session(id=secrets.token_urlsafe(16))


class MemorySessionStore:
    kind = "memory"

    def __init__(self):
        self._sessions: OrderedDict[str, tuple[float, Session]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str | None) -> Session:
        """The live session for this id, or a new one (with a new id) if unknown or expired."""
        now = time.time()
        with self._lock:
            self._evict(now)
            entry = self._sessions.get(session_id) if session_id else None
            session = entry[1] if entry else new_session()
            self._sessions[session.id] = (now, session)
            self._sessions.move_to_end(session.id)
            return session

    def save(self, session: Session) -> None:
        session.trim()
        with self._lock:
            self._sessions[session.id] = (time.time(), session)
            self._sessions.move_to_end(session.id)

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _evict(self, now: float) -> None:
        while self._sessions:
            seen, _ = next(iter(self._sessions.values()))
            if now - seen > TTL_SECONDS or len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
            else:
                break


class RedisSessionStore:
    """One JSON value per session under session:<id>, expiring TTL_SECONDS after the last turn."""

    kind = "redis"

    def __init__(self, client):
        self.redis = client

    def get(self, session_id: str | None) -> Session:
        raw = self.redis.get(f"session:{session_id}") if session_id else None
        if raw:
            try:
                return Session(**json.loads(raw))
            except (TypeError, ValueError):
                log.warning("dropping unreadable session %s", session_id)
        return new_session()

    def save(self, session: Session) -> None:
        session.trim()
        self.redis.set(f"session:{session.id}", json.dumps(asdict(session), ensure_ascii=False), ex=TTL_SECONDS)

    def reset(self, session_id: str) -> None:
        self.redis.delete(f"session:{session_id}")


class UsageCap:
    """Caps model-backed messages across all sessions per rolling hour, so a public demo
    can't run up unlimited API spend by opening new sessions."""

    def __init__(self, per_hour: int):
        self.per_hour = per_hour
        self._times: list[float] = []
        self._lock = threading.Lock()

    def try_acquire(self, now: float) -> bool:
        with self._lock:
            self._times = [t for t in self._times if now - t <= 3600]
            if len(self._times) >= self.per_hour:
                return False
            self._times.append(now)
            return True


class RedisUsageCap:
    """Same cap, shared by every instance and kept across restarts: one counter per clock hour."""

    def __init__(self, client, per_hour: int):
        self.redis, self.per_hour = client, per_hour

    def try_acquire(self, now: float) -> bool:
        key = f"usage:{int(now // 3600)}"
        count = self.redis.incr(key)
        if count == 1:
            self.redis.expire(key, 7200)
        return count <= self.per_hour


def make_stores(per_hour: int, url: str | None = None):
    """(session store, usage cap) for this deployment: Redis if REDIS_URL works, else memory."""
    url = url if url is not None else os.environ.get("REDIS_URL")
    if url:
        try:
            import redis
            client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
            client.ping()
            log.info("sessions: Redis")
            return RedisSessionStore(client), RedisUsageCap(client, per_hour)
        except Exception as e:  # noqa: BLE001 - any failure here means "use memory"
            log.warning("REDIS_URL is set but Redis is unreachable (%s); keeping sessions in memory", e)
    return MemorySessionStore(), UsageCap(per_hour)
