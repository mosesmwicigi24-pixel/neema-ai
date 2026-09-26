import os

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    """Liveness, the running commit, and — the part that matters — whether
    Neema can still ANSWER.

    The account once ran out of credit and every turn failed for days: inbound
    messages kept arriving, the inbox looked busy, and the only trace was an
    ERROR line nobody was grepping (see services/agent_health.py). The failure
    reason has been recorded ever since, but only the 08:00 standup read it, so
    "why is Neema not replying?" still needed SSH. Now it is one curl.

    Deliberately COARSE: the kind of failure (credit / auth / model / rate) and
    how many, never the raw provider error, the customer's number, or anything
    else from the record — this endpoint is public.
    """
    out = {
        # version = the git sha baked into the image at build time (deploy.yml
        # passes GIT_SHA). Empty on local/dev builds. This is how we tell WHICH
        # commit the box is actually running — the box pulls :latest on a timer,
        # so "did the deploy land?" was unanswerable before this field.
        "status": "ok",
        "version": os.environ.get("GIT_SHA", ""),
    }
    # Best-effort by construction: monitoring must never break the thing it
    # monitors, so any failure to READ the health state leaves the payload as-is.
    try:
        from app.services.agent_health import ACTIONABLE, read_turn_failures
        failures = await read_turn_failures(getattr(request.app.state, "redis", None))
        if failures:
            kind = failures.get("kind") or "other"
            out["agent"] = {
                "replies": "failing",
                "kind": kind,
                "failed_last_hour": failures.get("count", 0),
                # the bit an operator acts on: does this clear itself, or does
                # someone have to go and fix billing/keys?
                "needs_a_human": kind in ACTIONABLE,
            }
        else:
            out["agent"] = {"replies": "ok"}
    except Exception:
        pass
    # THE GATE BEFORE POSTING (owner, 2026-09-25): what the reviewer did today
    # — replies passed, rewritten once, held back for a colleague.
    try:
        from app.agent.review import read_verdicts
        tally = await read_verdicts(getattr(request.app.state, "redis", None))
        out["review"] = {"passed": tally.get("pass", 0),
                         "rewritten": tally.get("rewritten", 0),
                         "soft": tally.get("soft", 0),
                         "held": tally.get("held", 0)}
    except Exception:
        pass
    # WHERE THE MONEY WENT (owner, 2026-09-26): today's spend against the
    # rungs, by purpose and by model — every model call is metered.
    try:
        from app.services.ai_budget import read_breakdown
        spend = await read_breakdown(getattr(request.app.state, "redis", None))
        if spend:
            out["spend"] = spend
    except Exception:
        pass
    # PACING (owner, 2026-09-26): chat volume today — economy turns, threads
    # cooled, messages silenced, cool-offs lifted by a buying signal, duplicates.
    try:
        from app.agent.cooling import read_tally as _cool_tally
        c = await _cool_tally(getattr(request.app.state, "redis", None))
        out["cooling"] = {"economy": c.get("economy", 0), "cooled": c.get("cooled", 0),
                          "deferred": c.get("deferred", 0), "question": c.get("question", 0),
                          "silenced": c.get("silenced", 0), "lifted": c.get("lifted", 0),
                          "duplicate": c.get("duplicate", 0)}
    except Exception:
        pass
    # WE SELL CHURCH GOODS ONLY (owner, 2026-09-25): what the guard did today
    # — asks for other goods declined, threads paused, silenced, lifted.
    try:
        from app.agent.domain import read_tally
        g = await read_tally(getattr(request.app.state, "redis", None))
        out["guard"] = {"declined": g.get("declined", 0), "paused": g.get("paused", 0),
                        "silenced": g.get("silenced", 0), "lifted": g.get("lifted", 0),
                        "noted": g.get("noted", 0)}
    except Exception:
        pass
    return out
