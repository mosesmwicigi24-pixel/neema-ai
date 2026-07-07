"""OpenAI price table + cost estimation, so token spend is measurable.

Prices are USD per 1,000,000 tokens (as of 2026-07). Cached input tokens
(OpenAI automatic prompt caching) bill at a large discount — tracked
separately so we can SEE the value of making the system prompt cacheable.

Keep this table current when models/prices change; unknown models fall back
to a conservative default so a new model never silently logs $0.
"""
from __future__ import annotations

# model -> (input_per_mtok, cached_input_per_mtok, output_per_mtok) in USD
_PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-4.1":        (2.00, 0.50, 8.00),
    "gpt-4.1-mini":   (0.40, 0.10, 1.60),
    "gpt-4.1-nano":   (0.10, 0.025, 0.40),
    "gpt-4o":         (2.50, 1.25, 10.00),
    "gpt-4o-mini":    (0.15, 0.075, 0.60),
    "gpt-5-mini":     (0.25, 0.025, 2.00),
    # Claude (Tier 2 agent). cached = cache-READ rate (~0.1x input); cache
    # WRITES bill at 1.25x input, handled via cache_write_tokens below. Standard
    # (non-intro) rates so telemetry never under-reports once intro pricing ends.
    "claude-sonnet-5":  (3.00, 0.30, 15.00),
    "claude-haiku-4-5": (1.00, 0.10, 5.00),
    "claude-opus-4-8":  (5.00, 0.50, 25.00),
    # audio (billed per-token on these models; Whisper is billed per-minute
    # and logged separately by the caller)
    "whisper-1":      (0.0, 0.0, 0.0),
    "gpt-4o-mini-tts": (0.60, 0.0, 12.00),
}

_DEFAULT = (2.00, 0.50, 8.00)  # conservative: assume flagship pricing
_CACHE_WRITE_MULT = 1.25       # Anthropic 5-minute cache-write premium (x input)


def _norm(model: str | None) -> str:
    m = (model or "").strip().lower()
    # tolerate n8n's "GPT-4.1" display names and dated suffixes
    m = m.replace("gpt4", "gpt-4")
    if m in _PRICES:
        return m
    # Prefix match, MOST-specific first, so "gpt-4.1-mini" never collapses to
    # "gpt-4.1" (which would bill the mini model at flagship rates).
    for known in sorted(_PRICES, key=len, reverse=True):
        if m.startswith(known + "-"):
            return known
    return m


def estimate_cost_usd(
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Estimate USD cost of one call.

    `cached_tokens` and `cache_write_tokens` are disjoint subsets of
    `prompt_tokens`: cached = cache-READ (cheap), cache_write = written to cache
    this turn (1.25x input). The remainder bills at the full input rate. OpenAI
    callers omit cache_write (their automatic caching has no separate write cost).
    """
    inp, cached, out = _PRICES.get(_norm(model), _DEFAULT)
    fresh_input = max(prompt_tokens - cached_tokens - cache_write_tokens, 0)
    cost = (
        fresh_input / 1_000_000 * inp
        + cached_tokens / 1_000_000 * cached
        + cache_write_tokens / 1_000_000 * inp * _CACHE_WRITE_MULT
        + completion_tokens / 1_000_000 * out
    )
    return round(cost, 6)
