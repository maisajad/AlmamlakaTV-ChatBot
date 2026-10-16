from app import llm


def test_fallback_is_sent_only_to_models_that_have_one():
    sonnet = llm.request_args("claude-sonnet-5-5", "s", "u", {}, "medium", 100)
    assert sonnet["fallbacks"] == "default" and sonnet["betas"] == [llm.FALLBACK_BETA]
    haiku = llm.request_args("claude-haiku-5-5", "s", "u", {}, "low", 100)
    assert "fallbacks" not in haiku and "betas" not in haiku  # Haiku 5.5 has no server-side fallback


def test_effort_and_json_schema_are_always_set():
    args = llm.request_args("claude-haiku-5-5", "s", "u", {"type": "object"}, "low", 100)
    assert args["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}


def test_default_models():
    assert (llm.ANSWER_MODEL, llm.ROUTER_MODEL) == ("claude-sonnet-5-5", "claude-haiku-5-5")
