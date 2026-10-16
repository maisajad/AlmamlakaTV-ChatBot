"""The one place that talks to the Claude API."""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Callable

import anthropic
from dotenv import load_dotenv

from app.retrieval import ROOT

load_dotenv(ROOT / ".env")
log = logging.getLogger(__name__)

# One model per job, each the cheapest that holds up on the evals; override with env vars.
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "claude-sonnet-5-5")      # cited answers: strict rules
ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "claude-haiku-5-5")       # classify + rewrite: short, simple
CONFLICT_MODEL = os.environ.get("CONFLICT_MODEL", "claude-sonnet-5-5")  # offline, rare
MODEL = ANSWER_MODEL  # the model that writes what users read

# Server-side refusal fallback: if a safety classifier declines, the API re-runs the request on
# Anthropic's recommended fallback model inside the same call. Haiku 5.5 has no fallback, and a
# fallbacks parameter there would leave the decline in place (or 400), so it isn't sent.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}


def request_args(model: str, system: str, user_content: str, schema: dict, effort: str, max_tokens: int) -> dict:
    args = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    }
    if model in FALLBACK_MODELS:
        args.update(betas=[FALLBACK_BETA], fallbacks="default")
    return args


class LLMError(Exception):
    """The model call failed or returned something unusable. Callers show a generic error reply."""


@lru_cache(maxsize=1)
def client() -> anthropic.Anthropic:
    return anthropic.Anthropic(max_retries=3, timeout=90)


def structured_call(system: str, user_content: str, schema: dict, effort: str = "medium",
                    max_tokens: int = 8000, model: str = ANSWER_MODEL) -> dict:
    """One request whose reply is JSON matching `schema` (guaranteed by output_config.format)."""
    try:
        response = client().beta.messages.create(
            **request_args(model, system, user_content, schema, effort, max_tokens))
    except anthropic.APIStatusError as e:
        log.error("Claude API error %s: %s", e.status_code, e.message)
        raise LLMError(str(e)) from e
    except anthropic.APIConnectionError as e:
        log.error("Claude API unreachable: %s", e)
        raise LLMError(str(e)) from e

    return parse_reply(response, getattr(response, "_request_id", None))


def streamed_call(system: str, user_content: str, schema: dict, on_text: Callable[[str], None],
                  effort: str = "medium", max_tokens: int = 8000, model: str = ANSWER_MODEL) -> dict:
    """Like structured_call, but hands each chunk of the JSON reply to `on_text` as it is generated."""
    try:
        with client().beta.messages.stream(
                **request_args(model, system, user_content, schema, effort, max_tokens)) as stream:
            for text in stream.text_stream:
                on_text(text)
            response = stream.get_final_message()
    except anthropic.APIStatusError as e:
        log.error("Claude API error %s: %s", e.status_code, e.message)
        raise LLMError(str(e)) from e
    except anthropic.APIConnectionError as e:
        log.error("Claude API unreachable: %s", e)
        raise LLMError(str(e)) from e
    return parse_reply(response, None)


def parse_reply(response, request_id: str | None) -> dict:
    log.info("claude %s stop=%s in=%s out=%s", request_id or response.id, response.stop_reason,
             response.usage.input_tokens, response.usage.output_tokens)
    if response.stop_reason == "refusal":
        raise LLMError(f"refused: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise LLMError("hit max_tokens")
    # If a fallback model took over mid-reply, the last text block holds its complete answer.
    texts = [b.text for b in response.content if b.type == "text"]
    if not texts:
        raise LLMError("no text block in response")
    try:
        return json.loads(texts[-1])
    except json.JSONDecodeError as e:
        raise LLMError(f"reply is not valid JSON: {e}") from e


class JsonFieldStreamer:
    """Pulls one top-level string field (e.g. "answer") out of a JSON object while it is still
    being generated, decoding escapes as they complete. feed() returns the text decoded so far."""

    ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}

    def __init__(self, field: str):
        self.key = re.compile(r'"%s"\s*:\s*"' % re.escape(field))
        self.raw = ""
        self.pos: int | None = None  # index in raw where the string value starts
        self.value = ""
        self.done = False

    def feed(self, chunk: str) -> str:
        self.raw += chunk
        if self.pos is None:
            match = self.key.search(self.raw)
            if not match:
                return self.value
            self.pos = match.end()
        while not self.done and self.pos < len(self.raw):
            ch = self.raw[self.pos]
            if ch == '"':
                self.done = True
            elif ch == "\\":
                if self.pos + 1 >= len(self.raw):
                    break  # escape not complete yet
                nxt = self.raw[self.pos + 1]
                if nxt == "u":
                    if self.pos + 6 > len(self.raw):
                        break
                    self.value += chr(int(self.raw[self.pos + 2:self.pos + 6], 16))
                    self.pos += 6
                    continue
                self.value += self.ESCAPES.get(nxt, nxt)
                self.pos += 2
                continue
            else:
                self.value += ch
            self.pos += 1
        return self.value
