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
    # Claude (Tier 2 agent). cached = cache-READ rate; cache WRITES bill at
    # 1.25x input (5-minute) / 2x input (1-hour), via cache_write_tokens below.
    # Anthropic's published standard rates (pricing page, read 2026-10-30):
    # Sonnet 5's $2/$10 launch price became the standard price — the
    # $3/$15 rise scheduled for 2026-09-01 never happened. This table had
    # kept $3/$15, so the meter read ~1.5x the real spend and the $40
    # economy rung moved customers to the light model at ~$27 of real
    # spend (owner, 2026-10-30: keep her intelligence; fix the meter).
    "claude-sonnet-5":   (2.00, 0.20, 10.00),
    "claude-sonnet-5-5": (2.00, 0.10, 10.00),   # cache reads 0.05x on 5.5
    "claude-haiku-4-5":  (1.00, 0.10, 5.00),
    "claude-haiku-5-5":  (0.10, 0.01, 0.50),    # prompts up to 100K tokens
    "claude-opus-5":     (5.00, 0.50, 25.00),
    "claude-opus-5-5":   (4.00, 0.20, 20.00),
    "claude-opus-4-8":   (5.00, 0.50, 25.00),
    # audio (billed per-token on these models; speech-to-text is billed per
    # audio minute — services/transcribe.PRICE_PER_MIN meters it directly)
    "whisper-1":      (0.0, 0.0, 0.0),
    "gpt-4o-transcribe": (0.0, 0.0, 0.0),
    "gpt-4o-mini-transcribe": (0.0, 0.0, 0.0),
    "gpt-4o-mini-tts": (0.60, 0.0, 12.00),
}

# Unknown model → assume Sonnet-class pricing. Deliberately HIGH: the daily
# spend breaker (services/ai_budget) trusts this table, and a renamed or new
# model that quietly billed at cheaper assumed rates would blind it exactly
# when spend patterns change. Over-reporting trips the breaker early — annoying;
# under-reporting lets a surprise through — the thing it exists to prevent.
_DEFAULT = (3.00, 0.30, 15.00)
_CACHE_WRITE_MULT = 1.25       # Anthropic 5-minute cache-write premium (x input)
_CACHE_WRITE_1H_MULT = 2.0     # 1-hour-TTL cache-write premium (x input)


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
    cache_write_1h_tokens: int = 0,
) -> float:
    """Estimate USD cost of one call.

    `cached_tokens` and `cache_write_tokens` are disjoint subsets of
    `prompt_tokens`: cached = cache-READ (cheap), cache_write = written to cache
    this turn. `cache_write_1h_tokens` is the part of `cache_write_tokens`
    written at the 1-hour TTL (2x input, vs 1.25x for the 5-minute default —
    the shared rules prefix uses 1h so it outlives the gaps between customers).
    The remainder bills at the full input rate. OpenAI callers omit the write
    args (their automatic caching has no separate write cost).
    """
    inp, cached, out = _PRICES.get(_norm(model), _DEFAULT)
    fresh_input = max(prompt_tokens - cached_tokens - cache_write_tokens, 0)
    w1h = min(max(cache_write_1h_tokens, 0), cache_write_tokens)
    w5m = cache_write_tokens - w1h
    cost = (
        fresh_input / 1_000_000 * inp
        + cached_tokens / 1_000_000 * cached
        + w5m / 1_000_000 * inp * _CACHE_WRITE_MULT
        + w1h / 1_000_000 * inp * _CACHE_WRITE_1H_MULT
        + completion_tokens / 1_000_000 * out
    )
    return round(cost, 6)
