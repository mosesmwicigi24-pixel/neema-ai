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
    return out
