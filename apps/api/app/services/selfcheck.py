"""Outcome probes: did Neema's own work actually land?

Nearly every background subsystem here is best-effort by design — a failure
must never break a customer reply. The price of that safety is that a broken
subsystem is indistinguishable from a quiet one: three note-writers used a
non-existent enum member for weeks, every call swallowed the AttributeError,
and nothing noticed until a human went looking.

These probes check OUTCOMES, not implementations — rows that should exist,
links that should be durable, queues that should be drained — so any silent
failure with a visible symptom gets a voice, whatever its cause.

Wiring: rides the actions_loop heartbeat behind an hourly redis guard.
Findings go three places — the neema.selfcheck logger (WARNING), a one-time
notification when a finding is NEW (diffed against the last run, stored in
app_settings, so nobody is nagged every hour about the same thing), and the
08:00 standup's system-health line.

A probe that crashes becomes a finding itself. The checker must not have the
disease it exists to cure.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func as sa_func, select

from app.core.config import settings

_log = logging.getLogger("neema.selfcheck")

FINDINGS_KEY = "selfcheck_findings"     # app_settings row: {"at": iso, "findings": [...]}


# ── Probes ───────────────────────────────────────────────────────────────────
# Each returns a list of human-readable finding strings (empty = healthy) and
# may assume nothing about the health of what it probes.


async def _probe_media_dir(db, redis) -> list[str]:
    """The media volume must be writable or every upload and inbound photo
    save fails. Checked at boot too — this catches a regression mid-flight."""
    from app.routers.media import MEDIA_DIR
    probe = os.path.join(MEDIA_DIR, ".selfcheck_probe")
    try:
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return []
    except Exception as exc:
        return [f"media dir not writable ({exc}) — uploads and inbound photos are failing; "
                f"fix: docker compose exec -u root api chown -R appuser:appgroup {MEDIA_DIR}"]


async def _probe_media_rot(db, redis) -> list[str]:
    """Inbound Meta photos still on expiring CDN links two hours after arrival
    mean the repair sweep is dead — the photos WILL vanish."""
    from app.models.message import Message
    from app.services.meta_media import is_ephemeral
    from app.services.meta_send import META_CHANNELS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (await db.execute(
        select(Message.media_url).where(
            Message.channel.in_(META_CHANNELS),
            Message.media_type.isnot(None), Message.media_type != "note",
            Message.media_url.isnot(None),
            Message.created_at > since, Message.created_at < cutoff,
        ).limit(500)
    )).scalars().all()
    rotting = sum(1 for u in rows if is_ephemeral(u))
    if rotting:
        return [f"{rotting} inbound Meta photo(s) still on expiring CDN links "
                "after 2h — the media repair sweep is not landing"]
    return []


async def _probe_stuck_actions(db, redis) -> list[str]:
    """With AGENT_INITIATIVE on, a due planned action still 'planned' two hours
    later (outside quiet hours) means the initiative loop is dead."""
    if not settings.agent_initiative:
        return []
    from app.models.agent_action import AgentAction
    from app.services.hub_events import is_quiet_hours
    if is_quiet_hours(datetime.now(timezone.utc)):
        return []
    overdue = (await db.execute(
        select(sa_func.count()).select_from(AgentAction).where(
            AgentAction.status == "planned",
            AgentAction.due_at < datetime.now(timezone.utc) - timedelta(hours=2),
        )
    )).scalar_one()
    if overdue:
        return [f"{overdue} planned follow-up(s) overdue by 2h+ with AGENT_INITIATIVE on "
                "— the initiative loop is not sending"]
    return []


async def _probe_deferred_events(db, redis) -> list[str]:
    """Quiet-hours celebrations must drain when morning comes; entries stale by
    2h+ mean the drain loop is dead and paid customers hear nothing."""
    if redis is None:
        return []
    from app.services.hub_events import DEFER_ZSET
    stale_before = (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
    n = await redis.zcount(DEFER_ZSET, "-inf", stale_before)
    if n:
        return [f"{n} deferred hub event(s) past due by 2h+ — the morning drain "
                "is not running"]
    return []


async def _probe_missing_wamids(db, redis) -> list[str]:
    """Outbound WhatsApp rows should carry the wamid Meta returned; mostly-null
    means the send path is degraded and reply-quotes silently stopped resolving."""
    from app.models.message import Message, MsgDirection
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    base = [Message.channel == "whatsapp",
            Message.direction == MsgDirection.outbound,
            Message.media_type.is_(None) | (Message.media_type != "note"),
            Message.created_at >= since]
    total = (await db.execute(
        select(sa_func.count()).select_from(Message).where(*base))).scalar_one()
    if total < 5:
        return []                       # too few sends to judge
    missing = (await db.execute(
        select(sa_func.count()).select_from(Message).where(
            *base, Message.waba_msg_id.is_(None)))).scalar_one()
    if missing * 2 > total:
        return [f"{missing}/{total} outbound WhatsApp messages in 24h have no wamid "
                "— the send path is degraded (reply-quotes won't resolve)"]
    return []


async def _probe_briefings(db, redis) -> list[str]:
    """With COPILOT_MODE on, human pickups should produce briefing notes; pickups
    without a single note in a week is exactly how the dead-enum bug looked."""
    if not settings.copilot_mode:
        return []
    from app.models.intercept import Intercept, InterceptAction
    from app.models.message import Message
    day = datetime.now(timezone.utc) - timedelta(hours=24)
    week = datetime.now(timezone.utc) - timedelta(days=7)
    pickups = (await db.execute(
        select(sa_func.count()).select_from(Intercept).where(
            Intercept.action == InterceptAction.intercept,
            Intercept.created_at >= day))).scalar_one()
    if pickups < 2:
        return []
    notes = (await db.execute(
        select(sa_func.count()).select_from(Message).where(
            Message.media_type == "note",
            Message.text.like("🤝 Handoff briefing%"),
            Message.created_at >= week))).scalar_one()
    if notes == 0:
        return [f"{pickups} human pickup(s) in 24h but zero copilot briefing notes "
                "all week — the briefing writer is not landing"]
    return []


async def _probe_waiting_customers(db, redis) -> list[str]:
    """Human-held threads where the CUSTOMER spoke last and nobody has answered
    for 48h+ — the queue-discipline gap, surfaced instead of silently growing."""
    from app.models.conversation import Conversation, InterceptMode
    from app.models.message import Message, MsgDirection
    latest = (
        select(Message.conversation_id, sa_func.max(Message.created_at).label("m"))
        .group_by(Message.conversation_id).subquery())
    rows = (await db.execute(
        select(Message.created_at)
        .join(latest, and_(Message.conversation_id == latest.c.conversation_id,
                           Message.created_at == latest.c.m))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.direction == MsgDirection.inbound,
               Conversation.intercept_mode == InterceptMode.human,
               Message.created_at < datetime.now(timezone.utc) - timedelta(hours=48))
    )).scalars().all()
    if rows:
        oldest = min(rows)
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - oldest).days
        return [f"{len(rows)} human-held thread(s) where the customer has waited 48h+ "
                f"(oldest {days}d) — pick up or release"]
    return []


PROBES = [
    ("media_dir", _probe_media_dir),
    ("media_rot", _probe_media_rot),
    ("stuck_actions", _probe_stuck_actions),
    ("deferred_events", _probe_deferred_events),
    ("missing_wamids", _probe_missing_wamids),
    ("briefings", _probe_briefings),
    ("waiting_customers", _probe_waiting_customers),
]


# ── Runner ───────────────────────────────────────────────────────────────────


async def run_checks(db, redis) -> list[str]:
    """Run every probe; log, store, and notify NEW findings once. Never raises."""
    from app.services.app_settings import get_value, set_value

    findings: list[str] = []
    for name, probe in PROBES:
        try:
            findings += await probe(db, redis)
        except Exception as exc:
            # The checker must not fail the way its subjects do — a broken
            # probe is itself a finding, not a silent pass.
            findings.append(f"selfcheck probe '{name}' crashed: {exc}")

    for f in findings:
        _log.warning("selfcheck: %s", f)

    previous: list[str] = []
    try:
        raw = await get_value(db, FINDINGS_KEY)
        if raw:
            previous = json.loads(raw).get("findings", [])
    except Exception:
        pass

    new = [f for f in findings if f not in previous]
    if new and redis is not None:
        try:
            await redis.publish("ws:channel:agents:all", json.dumps({
                "event": "notification", "type": "selfcheck",
                "title": "🩺 System check found a problem",
                "body": " · ".join(new)[:300],
            }))
        except Exception:
            pass

    try:
        await set_value(db, FINDINGS_KEY, json.dumps({
            "at": datetime.now(timezone.utc).isoformat(), "findings": findings}))
    except Exception:
        pass

    if not findings:
        _log.info("selfcheck: all %d probes passing", len(PROBES))
    return findings


async def health_line(db) -> str:
    """One standup line from the last stored run — '' when there's nothing yet."""
    from app.services.app_settings import get_value
    try:
        raw = await get_value(db, FINDINGS_KEY)
        if not raw:
            return ""
        findings = json.loads(raw).get("findings", [])
    except Exception:
        return ""
    if not findings:
        return "🩺 System health: all checks passing."
    return "🩺 System health: " + "; ".join(findings[:3])
