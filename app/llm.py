"""The one place that talks to the Claude API."""

from __future__ import annotations

import json
import logging
from functools import lru_cache

import anthropic
from dotenv import load_dotenv

from app.retrieval import ROOT

load_dotenv(ROOT / ".env")
log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
# Server-side refusal fallback: if a safety classifier declines, the API re-runs the
# request on Anthropic's recommended fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """The model call failed or returned something unusable. Callers show a generic error reply."""


@lru_cache(maxsize=1)
def client() -> anthropic.Anthropic:
    return anthropic.Anthropic(max_retries=3, timeout=90)


def structured_call(system: str, user_content: str, schema: dict, effort: str = "medium",
                    max_tokens: int = 8000) -> dict:
    """One request whose reply is JSON matching `schema` (guaranteed by output_config.format)."""
    try:
        response = client().beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.APIStatusError as e:
        log.error("Claude API error %s: %s", e.status_code, e.message)
        raise LLMError(str(e)) from e
    except anthropic.APIConnectionError as e:
        log.error("Claude API unreachable: %s", e)
        raise LLMError(str(e)) from e

    log.info("claude %s stop=%s in=%s out=%s", response._request_id, response.stop_reason,
             response.usage.input_tokens, response.usage.output_tokens)
    if response.stop_reason == "refusal":
        raise LLMError(f"refused: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise LLMError("hit max_tokens")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise LLMError("no text block in response")
    return json.loads(text)
