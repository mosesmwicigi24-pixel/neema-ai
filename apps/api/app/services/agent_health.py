"""Notice when Neema stops being able to reply.

The Anthropic account ran out of credit. Every `llm.complete()` raised, so every
WhatsApp turn failed, for days — to customers in Kenya, Nigeria, South Africa,
India, Congo and Australia alike. Inbound messages kept arriving and kept being
stored, the inbox looked busy, and the only trace of the outage was an
`ERROR ... tier2 background turn failed` line that nobody was grepping. It was
found by a person noticing the silence, not by the system.

The self-check had probes for media, stuck actions, briefings and human-held
threads — but nothing watching the one thing the business actually runs on: that
she can still answer. This records why turns fail, and classifies the failures
that a human must act on (billing, credentials) apart from the ones that pass on
their own (a timeout, a blip).

Everything here is best-effort: monitoring must never be able to break the thing
it monitors, so a redis hiccup costs a metric, never a reply.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_log = logging.getLogger("neema.agent")

_COUNT_KEY = "agent:fail:count"
_LAST_KEY = "agent:fail:last"
_TTL = 3600                      # a rolling hour — matches the self-check cadence

# Failure kinds a person must DO something about. These never clear by
# themselves: retrying a turn against an unpaid account just fails again.
ACTIONABLE = ("credit", "auth", "model")


def classify(exc_or_text) -> str:
    """Bucket a turn failure by what it demands of a human.

    credit → the account is out of money (this outage) · auth → the key is wrong,
    revoked or missing · model → the configured model id isn't valid for this
    account · rate → throttled, usually self-clearing · other → anything else."""
    s = str(exc_or_text or "").lower()
    if ("credit balance" in s or "insufficient" in s or "billing" in s
            or "quota" in s or "payment" in s):
        return "credit"
    if ("authentication" in s or "unauthorized" in s or "invalid x-api-key" in s
            or "invalid api key" in s or "401" in s or "permission" in s):
        return "auth"
    if "not_found" in s or "notfound" in s or "does not exist" in s or "unknown model" in s:
        return "model"
    if "rate limit" in s or "429" in s or "overloaded" in s:
        return "rate"
    return "other"


async def record_turn_failure(redis, wa_id: str, exc) -> None:
    """Count a failed agent turn and remember the most recent reason."""
    if redis is None:
        return
    kind = classify(exc)
    try:
        n = await redis.incr(_COUNT_KEY)
        if n == 1:
            await redis.expire(_COUNT_KEY, _TTL)
        await redis.set(_LAST_KEY, json.dumps({
            "kind": kind,
            "error": str(exc)[:400],
            "wa_id": wa_id,
            "at": datetime.now(timezone.utc).isoformat(),
        }), ex=_TTL)
    except Exception:
        pass                       # never let monitoring cost a reply


async def read_turn_failures(redis) -> dict:
    """{count, kind, error, at} for the last hour — {} when nothing has failed."""
    if redis is None:
        return {}
    try:
        raw_count = await redis.get(_COUNT_KEY)
        if not raw_count:
            return {}
        out = {"count": int(raw_count)}
        last = await redis.get(_LAST_KEY)
        if last:
            out.update(json.loads(last))
        return out
    except Exception:
        return {}


_HUMAN = {
    "credit": "the AI account is OUT OF CREDIT — top it up, replies are dead until you do",
    "auth": "the AI API key is rejected — check ANTHROPIC_API_KEY",
    "model": "the configured AI model was rejected — check TIER2_MODEL",
    "rate": "the AI is rate-limiting us — replies are delayed or dropped",
    "other": "agent turns are failing",
}


def describe(failures: dict) -> str:
    """One operator-facing line for a batch of failures."""
    kind = failures.get("kind") or "other"
    n = failures.get("count") or 0
    line = f"{n} agent repl{'y' if n == 1 else 'ies'} FAILED in the last hour — {_HUMAN.get(kind, _HUMAN['other'])}"
    err = (failures.get("error") or "").strip()
    if err:
        line += f' (last error: "{" ".join(err.split())[:160]}")'
    return line
