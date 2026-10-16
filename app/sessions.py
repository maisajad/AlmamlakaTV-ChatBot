"""In-memory conversation sessions.

History lives on the server, keyed by an opaque session id, so a client cannot forge
earlier assistant turns. A restart (e.g. a sleeping Hugging Face Space) clears every
session; for a demo that is acceptable.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

MAX_TURNS = 6            # turns of history kept per session
TTL_SECONDS = 30 * 60    # idle sessions expire
MAX_SESSIONS = 2000      # oldest dropped beyond this
RATE_LIMIT = 15          # messages ...
RATE_WINDOW = 60         # ... per this many seconds, per session


@dataclass
class Session:
    id: str
    turns: deque = field(default_factory=lambda: deque(maxlen=MAX_TURNS))
    message_times: deque = field(default_factory=lambda: deque(maxlen=RATE_LIMIT))
    language: str = "en"
    last_seen: float = field(default_factory=time.monotonic)

    def rate_limited(self, now: float) -> bool:
        return len(self.message_times) == RATE_LIMIT and now - self.message_times[0] < RATE_WINDOW

    def record_message(self, now: float) -> None:
        self.message_times.append(now)


class UsageCap:
    """Caps model-backed messages across all sessions per rolling hour, so a public demo
    can't run up unlimited API spend by opening new sessions."""

    def __init__(self, per_hour: int):
        self.per_hour = per_hour
        self._times: deque = deque()
        self._lock = threading.Lock()

    def try_acquire(self, now: float) -> bool:
        with self._lock:
            while self._times and now - self._times[0] > 3600:
                self._times.popleft()
            if len(self._times) >= self.per_hour:
                return False
            self._times.append(now)
            return True


class SessionStore:
    def __init__(self):
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str | None) -> Session:
        """Return the live session for this id, or a new one (with a new id) if unknown or expired."""
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            session = self._sessions.get(session_id) if session_id else None
            if session is None:
                session = Session(id=secrets.token_urlsafe(16))
                self._sessions[session.id] = session
            session.last_seen = now
            self._sessions.move_to_end(session.id)
            return session

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _evict(self, now: float) -> None:
        while self._sessions:
            oldest = next(iter(self._sessions.values()))
            if now - oldest.last_seen > TTL_SECONDS or len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
            else:
                break
