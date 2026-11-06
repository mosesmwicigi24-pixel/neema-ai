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
# themselves within the hour: retrying a turn against an unpaid account just
# fails again, and a budget stop holds until midnight UTC unless someone
# raises the ceiling.
ACTIONABLE = ("credit", "auth", "model", "budget", "meta", "whatsapp")

# The subset where NO model turn can succeed, on any thread, until a person
# acts: the account, the key, the model id, or our own ceiling. A channel
# credential (meta/whatsapp) still lets the turn compose — only its send dies.
AI_DOWN = ("credit", "auth", "model", "budget")


def _is_database_error(exc: BaseException) -> bool:
    """SQLAlchemy's own hierarchy, or a driver error (asyncpg / psycopg)
    that reached us unwrapped — by type and module, never by message."""
    try:
        from sqlalchemy.exc import SQLAlchemyError
        if isinstance(exc, SQLAlchemyError):
            return True
    except Exception:
        pass
    mod = type(exc).__module__ or ""
    return mod.split(".")[0] in ("asyncpg", "psycopg", "psycopg2")


def classify(exc_or_text) -> str:
    """Bucket a turn failure by what it demands of a human.

    credit → the account is out of money (this outage) · auth → the key is wrong,
    revoked or missing · model → the configured model id isn't valid for this
    account · budget → Neema's own daily spend ceiling tripped (ai_budget) ·
    rate → throttled, usually self-clearing · other → anything else."""
    # By TYPE before by text (verification pass 3b / UNFINISHED, 2026-11-06):
    # a database error's message can say "permission denied" or "relation
    # does not exist", which the text rules below read as "auth" / "model" —
    # AI_DOWN kinds that pause the missed-reply sweep for an hour and tell
    # the owner to check the API key. A database or reply-gate failure is
    # neither: it is counted, named, and never mistaken for the provider.
    if isinstance(exc_or_text, BaseException):
        if _is_database_error(exc_or_text):
            return "database"
        if str(exc_or_text).startswith("reply gate error"):
            return "gate"
    s = str(exc_or_text or "").lower()
    # Ours before the provider's: the breaker's message says "spend ceiling",
    # and it must never be mistaken for a real billing failure.
    if "spend ceiling" in s or "ai_daily_stop" in s:
        return "budget"
    # CHANNEL credentials before AI credentials (2026-08-19): a Meta Graph 401
    # ("Error validating access token — the session has been invalidated
    # because the user changed their password") contains "401" and was being
    # classified "auth" — whose remedy line says "check ANTHROPIC_API_KEY".
    # A whole morning was spent chasing the wrong key. The failing credential
    # must be NAMED.
    if (("meta " in s and "failed (" in s)
            or "error validating access token" in s
            or "oauthexception" in s):
        return "meta"
    if "whatsapp" in s and "failed (" in s:
        return "whatsapp"
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


async def record_turn_success(redis) -> bool:
    """A turn just completed. Clear an ACTIONABLE failure state — only that.

    The count is a rolling hour and nothing used to clear it early, so the
    dashboard kept telling the team "replies are failing, a human is needed"
    for up to an hour after a person had already fixed it — the credit outage
    of 2026-09-01 read `needs_a_human` long after the account was topped up.
    A completed turn is proof the blocker is gone: you cannot finish one
    against an unpaid account, a rejected key or a dead page token.

    `rate` and `other` never clear this way. Those are intermittent by nature —
    some turns fail while others succeed — and wiping the count on the next
    success would hide exactly the partial outage the count exists to show.

    Best-effort, like everything here: monitoring must never cost a reply.
    """
    if redis is None:
        return False
    try:
        raw = await redis.get(_LAST_KEY)
        if not raw:
            return False                   # nothing recorded, or already aged out
        kind = ((json.loads(raw) or {}).get("kind") or "other")
        if kind not in ACTIONABLE:
            return False
        await redis.delete(_COUNT_KEY)
        await redis.delete(_LAST_KEY)
    except Exception:
        return False
    _log.info("agent recovered — a turn completed, clearing the %s failure state", kind)
    return True


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


async def ai_down(redis) -> str | None:
    """The AI_DOWN kind of the last failure this hour — None when replies can
    be composed. Cleared by the next completed turn (record_turn_success), or
    by the rolling hour running out. Fails open: no redis → None."""
    kind = (await read_turn_failures(redis)).get("kind")
    return kind if kind in AI_DOWN else None


_HUMAN = {
    "credit": "the AI account is OUT OF CREDIT — top it up, replies are dead until you do",
    "auth": "the AI API key is rejected — check ANTHROPIC_API_KEY",
    "model": "the configured AI model was rejected — check TIER2_MODEL",
    "budget": ("Neema hit her own daily AI spend ceiling — replies hold until "
               "midnight UTC; raise AI_DAILY_STOP_USD if today's spend is expected"),
    "meta": ("the Facebook/Instagram PAGE TOKEN is rejected — Messenger/IG sends "
             "are failing. Regenerate the Page Access Token (use a System User "
             "token so password changes can't kill it), update META_PAGE_TOKEN / "
             "META_PAGE_TOKENS on the box, restart the api — see "
             "docs/META_TOKEN_ROTATION.md"),
    "whatsapp": ("the WhatsApp (WABA) token is rejected — WhatsApp sends are "
                 "failing; regenerate it in Meta Business settings and update "
                 "the box env"),
    "rate": "the AI is rate-limiting us — replies are delayed or dropped",
    "database": "agent turns are failing on the DATABASE — not the AI account; check Postgres and the api logs",
    "gate": "the reply gate's own rule code is erroring — replies are held, not sent; check the api logs",
    "other": "agent turns are failing",
}


def describe(failures: dict) -> str:
    """One operator-facing line for a batch of failures."""
    kind = failures.get("kind") or "other"
    n = failures.get("count") or 0
    remedy = _HUMAN.get(kind, _HUMAN["other"])
    # A Meta refusal of the HUMAN_AGENT tag is an APP REVIEW problem, not a
    # token problem — pointing at META_PAGE_TOKEN here would repeat the
    # wrong-credential morning in a new costume (2026-08-19: "(#100) Cannot
    # tag messages with 'HUMAN_AGENT' without prior approval").
    if kind == "meta" and "human_agent" in (failures.get("error") or "").lower():
        remedy = ("Meta refused the HUMAN_AGENT tag — the app lacks Human Agent "
                  "approval. Request it: developers.facebook.com → the app → "
                  "App Review → Permissions and Features → Human Agent. The "
                  "page token itself is fine.")
    line = f"{n} agent repl{'y' if n == 1 else 'ies'} FAILED in the last hour — {remedy}"
    err = (failures.get("error") or "").strip()
    if err:
        line += f' (last error: "{" ".join(err.split())[:160]}")'
    return line
