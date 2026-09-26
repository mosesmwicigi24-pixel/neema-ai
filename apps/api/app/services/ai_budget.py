"""A hard daily ceiling on AI spend — the cost-surprise breaker.

The August 17 bill ($54.52 in one day) was discovered on a platform dashboard
AFTER the account had already run dry. Every guard in the system was per-SOMETHING
— per turn (iteration cap, max_tokens), per post (comment cap), per message
(dedup) — so nothing stood between "each call is fine" and "the day cost double
the plan". This is the per-DAY guard: every metered turn feeds a UTC day counter
in redis, and the agent checks it before buying tokens.

Two rungs, both env-tunable, both well above a normal post-overhaul day
(~$28–36), because this is a circuit breaker, not a target:

  AI_DAILY_BUDGET_USD (soft, default $40) → ECONOMY: main-model turns downgrade
      to the light model. Every customer still gets answered — at a third of
      the price — and the day keeps moving.
  AI_DAILY_STOP_USD  (hard, default $60) → STOP: agent turns refuse before the
      first token is bought. The refusal deliberately rides the SAME failure
      path as an out-of-credit account — hold line to the customer, flag to
      the team, "budget" on /api/health — because that path is the one part of
      failing we have already rehearsed in production. Unlike a drained
      account, this clears itself at midnight UTC.

Set a rung to 0 to disable it. Everything here is best-effort and fails OPEN:
a redis hiccup must cost a metric, never a sale — the worst day this module can
cause is one where it did nothing.

The meter counts EVERY model call (owner, 2026-09-26: "heightened expenditure
for a few days"): the LLM client itself meters each completion — the agent's
turns on every channel, the reviewer and the rewrite behind the gate, the
comment reader, the vision reads, the bridges, follow-ups and jobs — by
PURPOSE and by model (`meter`), so the breaker sees the true day and
/api/health says where the money went (`read_breakdown`). Before this, only
`run_turn`'s own loop was metered: the reviewer on every turn, every rewrite,
every comment read and every vision read bought tokens the breaker never saw.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import settings

_log = logging.getLogger("neema.agent")

_TTL = 3 * 86400            # the day key outlives its day for post-mortems, then goes


class DailyBudgetExceeded(RuntimeError):
    """Raised instead of buying tokens once the hard stop is reached.

    The message carries the marker `agent_health.classify` maps to "budget",
    so /api/health and the self-check name the real reason on their own."""


def _day_key(now: datetime | None = None) -> str:
    return "ai:spend:" + (now or datetime.now(timezone.utc)).strftime("%Y%m%d")


def exceeded_message(spent: float, stop: float) -> str:
    return (f"daily AI spend ceiling reached (${spent:.2f} of ${stop:.2f}, "
            "AI_DAILY_STOP_USD) — replies hold until midnight UTC or a raised ceiling")


_sink = None                 # the app's redis, attached at startup — the client's meter


def attach(redis) -> None:
    """Give the client-level meter a redis to write to (main.py, at boot)."""
    global _sink
    _sink = redis


def _by_key(now: datetime | None = None) -> str:
    return _day_key(now) + ":by"


def _slug(s: str | None) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in str(s or "other").lower())[:40] or "other"


async def meter(model: str | None, usage: dict | None, purpose: str = "other",
                redis=None) -> float:
    """One model call, from the client: its estimated cost into today's total
    (the breaker's number) and into the day's breakdown — USD, calls and
    tokens (fresh, cache-read, cache-written, out) per PURPOSE, USD and calls
    per model. Returns the cost. Best-effort; never raises."""
    from app.core.ai_pricing import estimate_cost_usd
    u = usage or {}

    def _n(k: str) -> int:
        try:
            return int(u.get(k) or 0)
        except (TypeError, ValueError):
            return 0
    fresh, cached, written, w1h, out = (_n("input_tokens"), _n("cache_read_tokens"),
                                        _n("cache_write_tokens"), _n("cache_write_1h_tokens"),
                                        _n("output_tokens"))
    usd = estimate_cost_usd(model, fresh + cached + written, out, cached_tokens=cached,
                            cache_write_tokens=written, cache_write_1h_tokens=w1h)
    r = redis if redis is not None else _sink
    if r is None or usd < 0:
        return usd
    try:
        key, by = _day_key(), _by_key()
        p, m = _slug(purpose), _slug(model)
        if usd > 0:
            await r.incrbyfloat(key, round(usd, 6))
            await r.expire(key, _TTL)
            await r.hincrbyfloat(by, f"usd:{p}", round(usd, 6))
            await r.hincrbyfloat(by, f"usd:model:{m}", round(usd, 6))
        await r.hincrby(by, f"calls:{p}", 1)
        await r.hincrby(by, f"calls:model:{m}", 1)
        for field, n in (("in", fresh), ("cached", cached), ("written", written), ("out", out)):
            if n:
                await r.hincrby(by, f"{field}:{p}", n)
        await r.expire(by, _TTL)
    except Exception:
        pass                     # the meter must never cost a reply
    return usd


async def read_breakdown(redis=None) -> dict:
    """Today, for /api/health: the total against the rungs and the mode, then
    every purpose (USD, calls, tokens) and every model (USD, calls), dearest
    first. {} when redis cannot say."""
    r = redis if redis is not None else _sink
    if r is None:
        return {}
    try:
        raw = await r.hgetall(_by_key()) or {}
    except Exception:
        raw = {}
    purposes: dict[str, dict] = {}
    models: dict[str, dict] = {}
    for k, v in raw.items():
        k = k.decode() if isinstance(k, bytes) else str(k)
        v = v.decode() if isinstance(v, bytes) else v
        try:
            field, _, name = k.partition(":")
            if name.startswith("model:"):
                d = models.setdefault(name[6:], {"usd": 0.0, "calls": 0})
            else:
                d = purposes.setdefault(name, {"usd": 0.0, "calls": 0, "in": 0, "cached": 0,
                                               "written": 0, "out": 0})
            if field == "usd":
                d["usd"] = round(float(v), 4)
            elif field in d:
                d[field] = int(float(v))
        except (TypeError, ValueError):
            continue
    spent = await spent_today(r)
    try:
        soft, stop = float(settings.ai_daily_budget_usd or 0), float(settings.ai_daily_stop_usd or 0)
    except Exception:
        soft, stop = 0.0, 0.0
    return {"today_usd": round(spent, 2), "soft_usd": soft, "stop_usd": stop,
            "mode": await mode(r),
            "by_purpose": dict(sorted(purposes.items(), key=lambda kv: -kv[1]["usd"])),
            "by_model": dict(sorted(models.items(), key=lambda kv: -kv[1]["usd"]))}


async def add_spend(redis, usd: float) -> None:
    """Meter one turn's estimated cost into today's counter. Best-effort."""
    if redis is None or not usd or usd <= 0:
        return
    try:
        key = _day_key()
        await redis.incrbyfloat(key, round(float(usd), 6))
        await redis.expire(key, _TTL)
    except Exception:
        pass                     # the meter must never cost a reply


async def spent_today(redis) -> float:
    """Today's metered spend in USD — 0.0 whenever redis can't say."""
    if redis is None:
        return 0.0
    try:
        raw = await redis.get(_day_key())
        if raw is None:
            return 0.0
        if isinstance(raw, (int, float)):
            return float(raw)
        return float(raw if isinstance(raw, str) else raw.decode())
    except Exception:
        return 0.0


async def mode(redis) -> str:
    """'ok' | 'economy' | 'stop' for right now. Fails open to 'ok'."""
    if redis is None:
        return "ok"
    spent = await spent_today(redis)
    if spent <= 0:
        return "ok"
    try:
        stop = float(settings.ai_daily_stop_usd or 0)
        soft = float(settings.ai_daily_budget_usd or 0)
    except Exception:
        return "ok"
    if stop > 0 and spent >= stop:
        return "stop"
    if soft > 0 and spent >= soft:
        return "economy"
    return "ok"


async def guard_turn(redis) -> str:
    """The one call `run_turn` makes: returns the mode, raising at the stop.

    Logs the rung ONCE per state change per process (roughly — a plain module
    flag), so a stopped afternoon is one WARNING line, not ten thousand."""
    m = await mode(redis)
    if m == "stop":
        spent = await spent_today(redis)
        stop = float(settings.ai_daily_stop_usd or 0)
        _note_state(m, spent)
        raise DailyBudgetExceeded(exceeded_message(spent, stop))
    if m == "economy":
        _note_state(m, None)
    return m


_last_noted = ""


def _note_state(m: str, spent: float | None) -> None:
    global _last_noted
    if m == _last_noted:
        return
    _last_noted = m
    if m == "stop":
        _log.warning("AI BUDGET STOP: $%.2f spent today ≥ AI_DAILY_STOP_USD — "
                     "agent turns now hold until midnight UTC", spent or 0)
    elif m == "economy":
        _log.warning("AI budget economy mode: past AI_DAILY_BUDGET_USD — "
                     "main-model turns downgrade to the light model")
