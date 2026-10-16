"""One chat turn: guard -> rewrite/route -> retrieve + answer + verify -> remember the turn."""

from __future__ import annotations

import logging
import os
import time
from typing import Callable

from app import llm
from app.answer import Answerer
from app.language import detect_language, reply
from app.rewrite import rewrite
from app.sessions import SessionStore, UsageCap

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 1000
ROUTED_REPLIES = {"greeting": "greeting", "off_topic": "out_of_scope", "injection": "out_of_scope"}
DEFAULT_HOURLY_CAP = int(os.environ.get("GLOBAL_HOURLY_LIMIT", "300"))  # ~$10-15/hour at most


class ChatBot:
    def __init__(self, answerer: Answerer | None = None, call: Callable[..., dict] = llm.structured_call,
                 hourly_cap: int = DEFAULT_HOURLY_CAP):
        self.answerer = answerer or Answerer(call=call)
        self.call = call
        self.sessions = SessionStore()
        self.usage = UsageCap(hourly_cap)

    def chat(self, session_id: str | None, message: str) -> dict:
        session = self.sessions.get(session_id)
        message = message.strip()
        language = detect_language(message, default=session.language)
        base = {"session_id": session.id, "language": language, "citations": [], "conflicts": []}

        now = time.monotonic()
        if session.rate_limited(now):
            return {**base, "status": "rate_limited", "answer": reply("rate_limited", language)}
        session.record_message(now)
        if len(message) > MAX_MESSAGE_CHARS:
            return {**base, "status": "too_long", "answer": reply("too_long", language, limit=MAX_MESSAGE_CHARS)}
        if not message:
            return {**base, "status": "greeting", "answer": reply("greeting", language)}
        if not self.usage.try_acquire(now):
            log.warning("global hourly cap reached")
            return {**base, "status": "busy", "answer": reply("busy", language)}

        history = list(session.turns)
        route = rewrite(message, history, call=self.call)
        log.info("route intent=%s query=%r", route.intent, route.standalone_query)

        if route.intent in ROUTED_REPLIES:
            status = ROUTED_REPLIES[route.intent]
            result = {**base, "status": status, "answer": reply(status, language)}
        else:
            previous = history[-1]["cited_ids"] if history else []
            result = {**base, **self.answerer.answer(message, language, standalone=route.standalone_query,
                                                     include_ids=previous)}
        result["intent"] = route.intent
        result["standalone_query"] = route.standalone_query

        # Refusals and errors are remembered too: "What about the project lead?" after an
        # unanswered question still needs the earlier turn to make sense.
        session.turns.append({"user": message, "answer": result["answer"], "status": result["status"],
                              "cited_ids": [c["chunk_id"] for c in result["citations"]]})
        session.language = language
        return result
