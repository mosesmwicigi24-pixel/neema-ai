"""The three recovery sweeps, on a daily timer — each off until the owner says.

cart_recovery (carts left before checkout), payment_followup (orders whose
payment link went unpaid) and reengage (customers left waiting on a reply)
were manual-only and had sent nothing in 7–14+ days. This runs each one
once a day at a Nairobi working hour, leader-locked so one worker of the
fleet runs it, ONLY when its own switch is on:

    RECOVERY_PAYMENT_ENABLED   payment_followup  10:00 Nairobi
    RECOVERY_CART_ENABLED      cart_recovery     11:00 Nairobi
    RECOVERY_REENGAGE_ENABLED  reengage          15:00 Nairobi
    RECOVERY_JOBS_DRY_RUN      compose, never send (each run still logged)

All default OFF. Each job keeps its own guards unchanged (24 h window only,
quiet hours, AI-mode threads only, one nudge per basket / order / message
per 7–14 days, the hub re-checked live before any payment reminder); the
timer adds none and removes none.

Every run writes one log line and a small Redis history (started, finished,
mode, candidates, sent, skipped, errors) shown on /api/health — counts only,
never a handle or a message. `preview()` answers "what would be sent today"
(counts + 3 sample messages, handles masked) for the admin endpoint and
`python -m app.services.recovery_jobs --preview`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from app.core.config import settings

_log = logging.getLogger("neema.recovery")

# job → (its switch in settings, the Nairobi hour it runs)
JOBS: dict[str, tuple[str, int]] = {
    "payment_followup": ("recovery_payment_enabled", 10),
    "cart_recovery": ("recovery_cart_enabled", 11),
    "reengage": ("recovery_reengage_enabled", 15),
}
TICK_SECONDS = 300
LOCK_KEY = "recoveryjobs:tick"
HISTORY_KEEP = 14


def anonymise(handle) -> str:
    """'…4567' — enough to tell rows apart in a log, never a contact."""
    s = str(handle or "")
    return f"…{s[-4:]}" if len(s) > 4 else "…"


def sample(channel: str | None, to, text: str | None) -> dict:
    return {"channel": channel or "", "to": anonymise(to), "text": (text or "")[:300]}


def enabled(job: str) -> bool:
    return bool(getattr(settings, JOBS[job][0], False))


def _history_key(job: str) -> str:
    return f"recoveryjobs:history:{job}"


async def _module_run(job: str, *, send: bool, redis, max_drafts: int | None = None) -> dict:
    """The job's own run(): every guard and every send path stays the job's."""
    if job == "cart_recovery":
        from app.jobs import cart_recovery as m
    elif job == "payment_followup":
        from app.jobs import payment_followup as m
    elif job == "reengage":
        from app.jobs import reengage as m
    else:
        raise ValueError(f"unknown recovery job {job!r}")
    return await m.run(send=send, redis=redis, max_drafts=max_drafts)


async def run_job(job: str, redis, *, dry_run: bool) -> dict:
    """Run one job now and record it. Never raises: a failed run is logged
    loudly and kept in the history with its error class (no message text —
    an exception can carry a URL or a token)."""
    started = datetime.now(timezone.utc)
    entry: dict = {"job": job, "mode": "dry_run" if dry_run else "send",
                   "started": started.isoformat(timespec="seconds")}
    try:
        # A dry run composes a few (3) — enough to read — not the whole list.
        res = await _module_run(job, send=not dry_run, redis=redis,
                                max_drafts=3 if dry_run else None)
        entry.update({"candidates": int(res.get("candidates") or 0),
                      "sent": int(res.get("sent") or 0),
                      "skipped": int(res.get("skipped") or 0),
                      "errors": int(res.get("failed") or 0),
                      "would_send": int(res.get("would_send") or 0)})
        _log.info("recovery job %s · %s · %d candidate(s) · %d sent · %d would send · "
                  "%d skipped · %d error(s)", job, entry["mode"], entry["candidates"],
                  entry["sent"], entry["would_send"], entry["skipped"], entry["errors"])
    except Exception as exc:
        entry.update({"error": type(exc).__name__})
        _log.error("recovery job %s FAILED (%s): %s", job, entry["mode"], exc)
    entry["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if redis is not None:
        try:
            await redis.lpush(_history_key(job), json.dumps(entry))
            await redis.ltrim(_history_key(job), 0, HISTORY_KEEP - 1)
        except Exception as exc:
            _log.warning("recovery job %s ran but its history was not recorded: %s", job, exc)
    return entry


async def tick(redis, *, now: datetime | None = None) -> list[str]:
    """One timer tick: under the fleet lock, run each switched-on job whose
    Nairobi hour this is and that has not run today. Returns the jobs run.

    No Redis → nothing runs: without the lock and the per-day guard two
    workers could each send the same campaign."""
    if redis is None:
        return []
    if not any(enabled(j) for j in JOBS):
        return []
    try:
        if not await redis.set(LOCK_KEY, os.environ.get("HOSTNAME", "worker"),
                               nx=True, ex=TICK_SECONDS - 30):
            return []
    except Exception as exc:
        _log.warning("recovery timer: lock unavailable, nothing run: %s", exc)
        return []
    nbo = (now or datetime.now(timezone.utc)) + timedelta(hours=3)
    ran: list[str] = []
    for job, (_flag, hour) in JOBS.items():
        if not enabled(job) or nbo.hour != hour:
            continue
        try:
            fresh = await redis.set(f"recoveryjobs:ran:{job}:{nbo:%Y%m%d}", "1",
                                    nx=True, ex=36 * 3600)
        except Exception as exc:
            _log.warning("recovery job %s skipped — day guard unavailable: %s", job, exc)
            continue
        if not fresh:
            continue
        await run_job(job, redis, dry_run=settings.recovery_jobs_dry_run)
        ran.append(job)
    return ran


async def loop(redis) -> None:
    """The timer: every 5 minutes, after a settling delay at boot."""
    await asyncio.sleep(60)
    while True:
        try:
            await tick(redis)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _log.warning("recovery timer tick failed: %s", exc)
        await asyncio.sleep(TICK_SECONDS)


async def preview(redis, jobs: list[str] | None = None) -> dict:
    """What each job would send if it ran now: counts + up to 3 sample
    messages (handles masked). Composes at most 3 per job; sends nothing,
    claims no guard."""
    out: dict = {}
    for job in jobs or list(JOBS):
        try:
            res = await _module_run(job, send=False, redis=redis, max_drafts=3)
            out[job] = {"enabled": enabled(job), "hour_nairobi": JOBS[job][1],
                        "candidates": int(res.get("candidates") or 0),
                        "would_send": int(res.get("would_send") or 0),
                        "skipped": int(res.get("skipped") or 0),
                        "errors": int(res.get("failed") or 0),
                        "samples": list(res.get("samples") or [])[:3]}
        except Exception as exc:
            _log.error("recovery preview for %s failed: %s", job, exc)
            out[job] = {"enabled": enabled(job), "error": type(exc).__name__}
    return out


async def health_view(redis) -> dict:
    """Coarse and secret-free, for the PUBLIC /api/health: switches, the
    hour, and the last runs' counts."""
    view: dict = {"dry_run": bool(settings.recovery_jobs_dry_run)}
    for job, (_flag, hour) in JOBS.items():
        runs: list = []
        if redis is not None:
            try:
                runs = [json.loads(r) for r in await redis.lrange(_history_key(job), 0, 2)]
            except Exception:
                runs = []
        view[job] = {"enabled": enabled(job), "hour_nairobi": hour, "last_runs": runs}
    return view


async def _cli() -> None:
    ap = argparse.ArgumentParser(description="Recovery jobs: preview what would be sent today.")
    ap.add_argument("--preview", action="store_true", help="counts + 3 samples per job (sends nothing)")
    ap.add_argument("--job", choices=list(JOBS), help="only this job")
    args = ap.parse_args()
    import importlib
    import pkgutil
    import app.models as models_pkg
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{mod.name}")
    import redis.asyncio as aioredis
    r = aioredis.from_url(settings.redis_url, decode_responses=True,
                          socket_connect_timeout=5, socket_timeout=5)
    try:
        if args.preview:
            print(json.dumps(await preview(r, [args.job] if args.job else None),
                             indent=2, ensure_ascii=False))
        else:
            print(json.dumps(await health_view(r), indent=2, ensure_ascii=False))
    finally:
        await r.aclose()


if __name__ == "__main__":
    asyncio.run(_cli())
