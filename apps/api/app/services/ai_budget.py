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

The meter counts what `run_turn` meters (all channels, comments, drafts,
sweeps, jobs). The handful of direct light-model calls outside it (the comment
labeler, call transcription, the daily standup) are fractions of a cent each
and are left unmetered on purpose.
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
