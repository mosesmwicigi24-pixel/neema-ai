"""Unit tests for AI cost estimation (pure, no DB)."""
from app.core.ai_pricing import estimate_cost_usd, _norm


def test_mini_is_not_billed_as_flagship():
    # The bug this guards: "gpt-4.1-mini" must NOT resolve to "gpt-4.1".
    assert _norm("gpt-4.1-mini") == "gpt-4.1-mini"
    assert _norm("gpt-4.1") == "gpt-4.1"
    mini = estimate_cost_usd("gpt-4.1-mini", 4000, 300)
    full = estimate_cost_usd("gpt-4.1", 4000, 300)
    assert mini < full * 0.3  # mini is ~5x cheaper


def test_prompt_cache_discount():
    no_cache = estimate_cost_usd("gpt-4.1", 26000, 500, cached_tokens=0)
    cached = estimate_cost_usd("gpt-4.1", 26000, 500, cached_tokens=16000)
    assert cached < no_cache  # cached input bills cheaper


def test_display_name_and_unknown_model():
    assert _norm("GPT-4.1") == "gpt-4.1"           # n8n display casing
    # unknown model falls back to a non-zero (conservative) cost, never $0
    assert estimate_cost_usd("some-future-model", 1000, 100) > 0
