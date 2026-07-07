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


def test_claude_sonnet_priced_and_cache_saves():
    # Sonnet 5 is known (not the fallback) and cache reads cut the input cost.
    assert _norm("claude-sonnet-5") == "claude-sonnet-5"
    no_cache = estimate_cost_usd("claude-sonnet-5", 30000, 500)
    cached = estimate_cost_usd("claude-sonnet-5", 30000, 500, cached_tokens=27000)
    assert cached < no_cache * 0.4  # ~90% of input served from cache


def test_claude_cache_write_costs_more_than_fresh():
    # Writing to cache bills at 1.25x input — must exceed the plain-input cost.
    fresh = estimate_cost_usd("claude-sonnet-5", 10000, 0)
    write = estimate_cost_usd("claude-sonnet-5", 10000, 0, cache_write_tokens=10000)
    assert write > fresh
