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

# How much notice a dying page token gets. Three days is enough to be seen on a
# working day and acted on calmly; the 2026-08-19 token had 100 minutes.
_TOKEN_EXPIRY_WARN_SEC = 72 * 3600


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


async def _probe_after_sale(db, redis) -> list[str]:
    """The after-sale arc (hub_events: paid / production / shipped / delivered
    messages) deploys dark and STAYS dark until configured — and once it is on,
    a dead hub→Neema webhook looks exactly like a quiet week. Say plainly
    which state we're in and what unlocks the next one."""
    if not settings.hub_events_secret:
        return ["after-sale messages are OFF (HUB_EVENTS_SECRET unset) — customers "
                "hear nothing at paid/production/shipped/delivered; set the secret "
                "here and in the hub to switch the arc on"]
    out: list[str] = []
    from app.models.order_event import OrderEvent
    from app.services.hub_events import LAST_EVENT_KEY
    week = datetime.now(timezone.utc) - timedelta(days=7)
    orders = (await db.execute(
        select(sa_func.count()).select_from(OrderEvent)
        .where(OrderEvent.created_at >= week))).scalar_one()
    seen = None
    if redis is not None:
        try:
            seen = await redis.get(LAST_EVENT_KEY)
        except Exception:
            pass
    # Orders flowing while the hub has said nothing for 30d+ (the stamp's TTL)
    # is a broken webhook, not a quiet week. No orders → nothing to conclude.
    if orders >= 3 and not seen:
        out.append(f"{orders} order(s) created in 7d but no hub event received — "
                   "the hub→Neema webhook looks dead; check the hub side")
    if not settings.wa_event_template:
        out.append("WA_EVENT_TEMPLATE not set — order updates outside the 24h "
                   "window fall to manual sending; approve a WhatsApp utility "
                   "template and set its name to automate them")
    return out


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


async def _probe_agent_failures(db, redis) -> list[str]:
    """Is Neema still able to reply at all?

    The check that was missing when the AI account ran out of credit: every turn
    raised, every customer was met with silence for days, and nothing said so.
    An out-of-credit or rejected-key failure is reported even for a single turn —
    it never recovers on its own — while transient kinds need a few before we
    call it a problem."""
    from app.services.agent_health import ACTIONABLE, describe, read_turn_failures
    failures = await read_turn_failures(redis)
    if not failures:
        return []
    kind, count = failures.get("kind") or "other", failures.get("count") or 0
    if kind in ACTIONABLE or count >= 3:
        return [describe(failures)]
    return []


async def _probe_unanswered_customers(db, redis) -> list[str]:
    """Customers waiting on the AI — threads it OWNS where nothing went back.

    Deliberately outcome-based, so it fires whatever the cause: no credit, a bad
    deploy, a crashed task, a bug none of us predicted. `_probe_waiting_customers`
    only looks at human-held threads, so an AI that had stopped answering was
    invisible to it."""
    from app.models.conversation import Conversation, InterceptMode
    from app.models.message import Message, MsgDirection
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=30)
    # Only the RECENT window (48h) is evidence about whether Neema is answering
    # TODAY. The historical tail — hundreds of threads whose Meta reply window
    # expired months ago and that nobody can lawfully answer — used to be counted
    # too, which pinned this finding at "823 waiting (oldest 3180h)" forever:
    # permanent alarm, zero signal. An outage shows up as a pile-up of FRESH
    # unanswered inbound, so that is all we look at.
    horizon = now - timedelta(hours=48)
    latest = (
        select(Message.conversation_id, sa_func.max(Message.created_at).label("m"))
        .group_by(Message.conversation_id).subquery())
    rows = (await db.execute(
        select(Message.created_at)
        .join(latest, and_(Message.conversation_id == latest.c.conversation_id,
                           Message.created_at == latest.c.m))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.direction == MsgDirection.inbound,
               Conversation.intercept_mode == InterceptMode.ai,
               Message.created_at < cutoff,
               Message.created_at > horizon)
    )).scalars().all()
    # A couple can be legitimate (a paused chat, a closing "asante" needing no
    # reply). A pile-up is the AI being down.
    if len(rows) < 3:
        return []
    oldest = min(rows)
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    hours = int((now - oldest).total_seconds() // 3600)
    return [f"{len(rows)} customer(s) waiting on the AI with no reply for 30m+ "
            f"in the last 48h (oldest {hours}h) — check that Neema can still answer"]


async def _token_expiry_finding(label: str, tok: str) -> list[str]:
    """Warn while a page token still has hours to live, not after it dies.

    Graph will happily tell you when a token expires (`/debug_token`), and a
    token minted from a short-lived login carries `expires_at` a few hours out
    — the exact shape of the 2026-08-19 replacement token, which was installed
    at 10:20 UTC and would have died at 12:00 with no warning at all. Only a
    token derived from an EXTENDED user token reports `expires_at: 0` (never).

    The token debugs itself (`input_token` = `access_token`), so this needs no
    app secret — which matters, because the box had none.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get("https://graph.facebook.com/v19.0/debug_token",
                                 params={"input_token": tok, "access_token": tok})
        data = (r.json() or {}).get("data") or {}
        exp = data.get("expires_at")
        if not isinstance(exp, int) or exp <= 0:
            return []                     # 0 = never expires; absent = unknown
        left = exp - int(datetime.now(timezone.utc).timestamp())
        if left > _TOKEN_EXPIRY_WARN_SEC:
            return []
        when = datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        hours = max(0, left) // 3600
        return [f"Meta page token ({label}) EXPIRES in {hours}h ({when}) — "
                "Messenger/Instagram sends stop then. This one was minted from a "
                "short-lived login; a permanent token comes from EXTENDING the "
                "user token first, then GET /me/accounts. "
                "See docs/META_TOKEN_ROTATION.md"]
    except Exception:
        return []                         # a blip must never cry wolf


async def _probe_meta_tokens(db, redis) -> list[str]:
    """Ask Graph directly whether each configured page token still works —
    BEFORE a customer send fails on it. A user-session-derived token dies the
    moment the page admin changes their Facebook password (today's outage);
    this probe turns that silent death into a named, once-notified finding
    within the hour. Network blips never cry wolf — only a definite Graph
    auth rejection counts."""
    toks: dict[str, str] = {}
    if settings.meta_page_token:
        toks["default"] = settings.meta_page_token
    try:
        for pid, t in (settings.page_token_map or {}).items():
            if t and t not in toks.values():
                toks[str(pid)] = t
    except Exception:
        pass
    out: list[str] = []
    for label, tok in list(toks.items())[:5]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get("https://graph.facebook.com/v19.0/me",
                                     params={"access_token": tok,
                                             "fields": "id,name,category"})
            if r.status_code == 200:
                # Valid is not enough — it must be a PAGE token. A System User
                # token answers /me happily but has no messages edge, so every
                # send 400s ("Object with ID 'me' does not exist") while this
                # probe stays green — exactly today's second outage. Only a
                # Page carries `category`.
                if '"category"' not in (r.text or ""):
                    out.append(
                        f"Meta token ({label}) is VALID but NOT a Page token — "
                        "sends fail with 'Object with ID me does not exist'. "
                        "Exchange it: GET /me/accounts with this token and use "
                        "the page's own access_token. See docs/META_TOKEN_ROTATION.md")
                    continue
                out += await _token_expiry_finding(label, tok)
                continue
            body = (r.text or "")[:160]
            if r.status_code in (400, 401, 403) and (
                    "oauth" in body.lower() or "access token" in body.lower()):
                out.append(
                    f"Meta page token ({label}) is REJECTED by Graph "
                    f"({r.status_code}) — Messenger/Instagram sends are failing. "
                    "Regenerate the Page Access Token (use a System User token), "
                    "update META_PAGE_TOKEN(S), restart the api. "
                    "See docs/META_TOKEN_ROTATION.md")
                from app.services.agent_health import record_turn_failure
                await record_turn_failure(
                    redis, f"meta-token:{label}",
                    RuntimeError(f"Meta token probe failed ({r.status_code}): {body}"))
        except Exception:
            continue
    return out


async def _probe_webhook_signature(db, redis) -> list[str]:
    """An unset app secret does not fail loudly — it turns verification OFF.

    Both webhook front doors verify Meta's `X-Hub-Signature-256` only when a
    secret is configured, and return True when it is not (a dev convenience:
    routers/meta_webhook.py, routers/whatsapp_webhook.py). On 2026-08-19 the
    box turned out to have no META_APP_SECRET at all — inbound had "always
    worked", so nothing ever hinted that every payload was being taken on
    trust. Anyone who learned the callback URL could have posted a fake
    customer message; Neema would have run a paid turn and answered it as
    real. Silence is not the same as safety, so the gap gets a voice.
    """
    out: list[str] = []
    if not settings.meta_app_secret:
        out.append(
            "META_APP_SECRET is UNSET — the Messenger/Instagram webhook accepts "
            "UNSIGNED payloads: anyone with the callback URL can inject fake "
            "customer messages, each costing a paid AI turn and answered as if "
            "real. Copy the App Secret from the Meta app (Settings → Basic), set "
            "META_APP_SECRET on the box, recreate the api container.")
    if not (settings.whatsapp_app_secret or settings.meta_app_secret):
        out.append(
            "No WhatsApp webhook secret (WHATSAPP_APP_SECRET / META_APP_SECRET "
            "both unset) — the WhatsApp front door accepts UNSIGNED payloads too.")
    return out


async def _probe_price_consistency(db, redis) -> list[str]:
    """Does the hub's USD price agree with its KES price, product by product?

    2026-09-02: a customer was quoted $10, then "KES 10", for a pack of 50
    cups — both read faithfully from the hub, both wrong, and 38 other rows
    were wrong the same way. Nothing had looked. This looks, daily, and names
    the worst row so the fix is a hub edit and not an investigation."""
    from app.core.config import settings
    from app.services import n8n_bridge as svc
    from app.services.price_audit import audit, summary_line
    catalog = await svc.catalog_items(db, redis)
    line = summary_line(audit(catalog, settings.usd_kes_rate or 100))
    return [line] if line else []


PROBES = [
    ("agent_failures", _probe_agent_failures),
    ("meta_tokens", _probe_meta_tokens),
    ("webhook_signature", _probe_webhook_signature),
    ("unanswered_customers", _probe_unanswered_customers),
    ("media_dir", _probe_media_dir),
    ("media_rot", _probe_media_rot),
    ("stuck_actions", _probe_stuck_actions),
    ("deferred_events", _probe_deferred_events),
    ("after_sale", _probe_after_sale),
    ("missing_wamids", _probe_missing_wamids),
    ("briefings", _probe_briefings),
    ("waiting_customers", _probe_waiting_customers),
    ("price_consistency", _probe_price_consistency),
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
