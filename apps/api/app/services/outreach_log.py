"""Who sent what, and why — the record every unprompted message leaves.

Until now an outbound row could not say which component produced it; the
inbox showed the words and nothing else, and no sender could ask "has anyone
written to this customer today?". Every unprompted sender now stamps the row's
`raw_meta` (an existing JSONB column — no migration) through `stamp()`, and
every decision NOT to send is logged through `decision()` with the contact
masked. The trace CLI (app/jobs/outreach_trace.py) reads both.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

_log = logging.getLogger("neema.outreach")

KIND = "outreach"

# Message classes (audit §4): what the message IS for the customer. Decisions
# in later stages are made per class; today the class is recorded.
ROUTINE = "routine"              # a sales follow-up nobody asked for
PROMISE = "promise"              # a check-in on a day the customer or Neema named
TRANSACTIONAL = "transactional"  # order / payment / care about their own order
ANSWER = "answer"                # a reply to something they asked


def stamp(source: str, cls: str, *, action_id=None, kind: str | None = None,
          reference: str | None = None, template: dict | None = None,
          delivery: dict | None = None) -> dict:
    """raw_meta for a stored outbound row."""
    m: dict = {"kind": KIND, "source": source, "class": cls,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if action_id is not None:
        m["action_id"] = str(action_id)
    if kind:
        m["action_kind"] = kind
    if reference:
        m["reference"] = str(reference)[:80]
    if template:
        m["template"] = template
    if delivery:
        m["delivery"] = delivery
    return m


def decision(source: str, channel: str, key: str, verdict: str, reason: str,
             **facts) -> None:
    """One line per decision — send, suppress, defer, hold — contact masked."""
    masked = f"…{str(key)[-4:]}" if key else "…"
    extra = " ".join(f"{k}={v}" for k, v in facts.items() if v is not None)
    _log.info("outreach %s %s/%s %s: %s %s", source, channel, masked, verdict, reason, extra)


# ── the shadow week, readable without SSH (Stage 4) ──────────────────────────

TALLY_FIELDS = ("suppress", "defer", "enforced_suppress", "enforced_defer",
                "rule_customer_replied", "rule_colleague_replied", "rule_daily_cap", "rule_other",
                "hold_customer", "hold_team_check", "hold_intent", "park_language", "park_template",
                "unknown_outcome")


def _day_key(offset_days: int = 0) -> str:
    from datetime import datetime, timedelta, timezone
    nbo = datetime.now(timezone.utc) + timedelta(hours=3) - timedelta(days=offset_days)
    return "outreach:shadow:" + nbo.strftime("%Y%m%d")


async def _tally(redis, key: str) -> dict:
    raw = await redis.hgetall(key) or {}
    out = {}
    for k, v in raw.items():
        k = k.decode() if isinstance(k, bytes) else str(k)
        try:
            out[k] = int(v)
        except (TypeError, ValueError):
            continue
    return {f: out.get(f, 0) for f in TALLY_FIELDS if out.get(f, 0)} or {}


async def health_view(redis, db_factory=None) -> dict:
    """Counts only, for /api/health (public): what the dispatcher decided today
    and yesterday (Nairobi days), and how many rows wait for a person. Never a
    number, a name, a reason text or a message. Each part is best-effort."""
    from app.services import app_settings
    out: dict = {"mode": app_settings._default_outreach_control()["mode"],
                 "enforced_rules": app_settings._default_outreach_control()["rules"]}
    if redis is not None:
        try:
            out["today"] = await _tally(redis, _day_key(0))
            out["yesterday"] = await _tally(redis, _day_key(1))
        except Exception:
            pass
    try:
        if db_factory is None:
            from app import database as _database
            db_factory = _database.AsyncSessionLocal
        from sqlalchemy import func, select
        from app.models.agent_action import AgentAction
        async with db_factory() as db:
            try:
                ctrl = await app_settings.get_outreach_control(db, redis)
                out["mode"], out["enforced_rules"] = ctrl["mode"], ctrl["rules"]
            except Exception:
                pass
            rows = (await db.execute(
                select(AgentAction.status, func.count()).where(
                    AgentAction.status.in_(("planned", "needs_approval", "sending")))
                .group_by(AgentAction.status))).all()
            waiting = {str(s): int(n) for s, n in rows}
            unknown = (await db.execute(
                select(func.count()).select_from(AgentAction).where(
                    AgentAction.status == "needs_approval",
                    AgentAction.reason.ilike("%outcome unknown%")))).scalar() or 0
            out["rows"] = {"planned": waiting.get("planned", 0),
                           "needs_approval": waiting.get("needs_approval", 0),
                           "unknown_outcome": int(unknown)}
            try:
                out["backlog"] = await backlog_view(db)
            except Exception:
                pass
    except Exception:
        pass
    return out


# ── the parked-row backlog (Stage 6) ─────────────────────────────────────────
# 595 rows sat in needs_approval the day the programme went live. Counts by WHY
# they wait and by HOW LONG, so a person can see the pile without SSH and the
# CLI below can retire what is plainly stale — never silently, never sending.

BACKLOG_BUCKETS = (
    ("window", "outside the 24h"),
    ("team_check", "team still confirming"),
    ("language", "they write in"),
    ("unknown_outcome", "outcome unknown"),
    ("failed", "auto-send failed"),
    ("opt_out", "asked not to be messaged"),
    ("human_held", "human-held"),
    ("flagged", "flagged for the team"),
    ("sensitive", "deal total above"),
    ("nudged", "already nudged"),
)
BACKLOG_AGES = ((7, "under_7d"), (30, "7_to_30d"), (10 ** 6, "over_30d"))


def backlog_bucket(reason: str | None) -> str:
    r = (reason or "").lower()
    for name, needle in BACKLOG_BUCKETS:
        if needle in r:
            return name
    return "other"


def backlog_age(created_at, now) -> str:
    from datetime import timezone as _tz
    if created_at is None:
        return "unknown"
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=_tz.utc)
    days = (now - created_at).days
    for limit, name in BACKLOG_AGES:
        if days < limit:
            return name
    return "over_30d"


async def backlog_view(db, *, now=None) -> dict:
    """{'by_reason': {...}, 'by_age': {...}, 'by_kind': {...}, 'total': n} over
    the rows in needs_approval. Counts only."""
    from datetime import datetime, timezone as _tz
    from sqlalchemy import select
    from app.models.agent_action import AgentAction
    now = now or datetime.now(_tz.utc)
    rows = (await db.execute(
        select(AgentAction.kind, AgentAction.reason, AgentAction.created_at)
        .where(AgentAction.status == "needs_approval"))).all()
    by_reason: dict = {}
    by_age: dict = {}
    by_kind: dict = {}
    for kind, reason, created in rows:
        by_reason[backlog_bucket(reason)] = by_reason.get(backlog_bucket(reason), 0) + 1
        a = backlog_age(created, now)
        by_age[a] = by_age.get(a, 0) + 1
        by_kind[kind or "?"] = by_kind.get(kind or "?", 0) + 1
    return {"total": len(rows), "by_reason": by_reason, "by_age": by_age, "by_kind": by_kind}
