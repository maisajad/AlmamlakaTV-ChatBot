"""Step before retrieval: classify the message and turn follow-ups into standalone questions.

"What about its budget?" means nothing to a retriever. Given the conversation it becomes
"What is the budget of the Digital Expansion Initiative?", in English, which also
helps BM25 for questions asked in Arabic.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Callable

from app import llm
from app.prompts import REWRITE_SYSTEM

INTENTS = ["question", "greeting", "off_topic", "injection"]
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "standalone_query"],
    "properties": {
        "intent": {"type": "string", "enum": INTENTS},
        "standalone_query": {"type": "string"},
    },
}
HISTORY_ANSWER_CHARS = 600  # earlier answers only need enough to resolve references


@dataclass
class Rewrite:
    intent: str
    standalone_query: str


def render_conversation(turns: list[dict]) -> str:
    if not turns:
        return "<conversation></conversation>"
    parts = []
    for t in turns:
        answer = t["answer"][:HISTORY_ANSWER_CHARS]
        parts.append(f"<user>{escape(t['user'], quote=False)}</user>\n"
                     f"<assistant>{escape(answer, quote=False)}</assistant>")
    return "<conversation>\n" + "\n".join(parts) + "\n</conversation>"


def rewrite(message: str, turns: list[dict], call: Callable[..., dict] = llm.structured_call) -> Rewrite:
    """On API failure, fall back to treating the raw message as the question: the answer
    step still applies every rule, so this degrades follow-ups, not safety."""
    prompt = f"{render_conversation(turns)}\n\n<message>{escape(message, quote=False)}</message>"
    try:
        raw = call(REWRITE_SYSTEM, prompt, SCHEMA, effort="low", max_tokens=2000)
    except llm.LLMError:
        return Rewrite("question", message)
    query = raw["standalone_query"].strip()
    if raw["intent"] == "question" and not query:
        query = message
    return Rewrite(raw["intent"], query)
