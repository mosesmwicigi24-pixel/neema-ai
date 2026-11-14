"""ACCOUNTABLE COMMITMENTS (owner's decision, 2026-11-07 — safe-032).

A check Neema promised the team would do ("I'm confirming the cope with the
team and will come back to you") is a commitment the business made. Until
this slice it lived as the deal's open `team_check` (services/deals.py): the
scheduler held sales nudges and the next turn was told not to close on the
item — but nobody OWNED it, nothing measured its age, and a customer who came
back the next day ("any news?") met the same promise again. The owner's rule:

    A customer should never experience our internal system limitations as
    a breakdown in our commitment to serve them.

So here a commitment that is overdue is ESCALATED, accountably, while Neema
stays on the thread:

  * `reading(deal)` — the open check with its age and whether it is overdue
    (older than the acknowledgement target during staffed hours).
  * `escalate(...)` — one durable, idempotent intervention per stage: the
    deal's `next_action["escalation"]` (stage, when, why, how many times the
    customer has followed up), a flag row in the Activity log naming the
    owner (the assigned colleague, or "needs an owner"), and the dashboard
    bell. Stage `team` at the acknowledgement target, stage `supervisor` at
    the supervisor target (the super admin's bell, and an operational
    failure counted in /api/health). Never human mode: a thread parked
    there is one nobody answers (services/unclaimed.py).
  * `customer_followed_up(...)` — the live turn's hook: a customer writing
    while a check is overdue escalates it NOW (whatever the sweeper's clock
    says) and the writer is told to own the delay in one line, say it is
    referred for a manual check, and never promise "shortly" again.
  * `sweep(...)` — the scheduler's half: every tick, every overdue open
    check is escalated to the stage its age earns; outside staffed hours
    nothing rings — the check is queued and rings at the next staffed start.
  * `health_view()` — open / overdue / unowned / oldest, for /api/health.

What closes a commitment is unchanged: a colleague's reply in the thread or
the team-answer endpoint (`deals.clear_team_check`), which now keeps the
opened time and the age so time-to-answer is measurable. A notification is
never counted as a resolution; only that reply is.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings

_log = logging.getLogger("neema.commitments")

STAGES = ("team", "supervisor")
_NAIROBI = timedelta(hours=3)                   # Kenya is UTC+3 year-round


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def staffed_hours() -> tuple[int, int]:
    """(start_hour, end_hour) in Nairobi time from `commitment_staffed_hours`
    ("07-21"); a malformed setting means always staffed (never silently off)."""
    raw = str(getattr(settings, "commitment_staffed_hours", "") or "")
    try:
        a, b = raw.split("-", 1)
        start, end = int(a), int(b)
        if 0 <= start < end <= 24:
            return start, end
    except (TypeError, ValueError):
        pass
    return 0, 24


def staffed_now(now: datetime | None = None) -> bool:
    now = _aware(now) or datetime.now(timezone.utc)
    hour = (now + _NAIROBI).hour
    start, end = staffed_hours()
    return start <= hour < end


def next_staffed_start(now: datetime | None = None) -> datetime:
    """The next moment the team is on duty (UTC), for a check that fell due
    out of hours."""
    now = _aware(now) or datetime.now(timezone.utc)
    start, _ = staffed_hours()
    local = now + _NAIROBI
    candidate = local.replace(hour=start, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate - _NAIROBI


def ack_minutes() -> int:
    return int(getattr(settings, "commitment_ack_minutes", 5) or 5)


def supervisor_minutes() -> int:
    return int(getattr(settings, "commitment_supervisor_minutes", 15) or 15)


def reading(deal, *, now: datetime | None = None) -> dict | None:
    """The open commitment on this deal, or None: {item, since, age_min,
    overdue, stage_due, escalation}. `stage_due` is the stage the age earns
    during staffed hours ("" when not yet due); `escalation` is what was
    already recorded."""
    from app.services.deals import team_check_open
    item = team_check_open(deal, now=now)
    if not item:
        return None
    nxt = deal.next_action if isinstance(getattr(deal, "next_action", None), dict) else {}
    now = _aware(now) or datetime.now(timezone.utc)
    try:
        since = _aware(datetime.fromisoformat(nxt.get("since")))
    except (TypeError, ValueError):
        since = None
    age_min = int((now - since).total_seconds() // 60) if since else 0
    stage_due = ""
    if age_min >= supervisor_minutes():
        stage_due = "supervisor"
    elif age_min >= ack_minutes():
        stage_due = "team"
    esc = nxt.get("escalation") if isinstance(nxt.get("escalation"), dict) else {}
    return {"item": item, "since": since.isoformat(timespec="seconds") if since else None,
            "age_min": age_min, "overdue": bool(stage_due), "stage_due": stage_due,
            "escalation": esc}


def _age_words(age_min: int) -> str:
    if age_min >= 2880:
        return f"{age_min // 1440} days"
    if age_min >= 1440:
        return "a day"
    if age_min >= 120:
        return f"{age_min // 60} hours"
    if age_min >= 60:
        return "an hour"
    return f"{age_min} min"


def writer_note(r: dict) -> str:
    """What the live turn is told about an OVERDUE commitment — the owner's
    shape: own the delay once, say it is now referred for a manual check,
    keep serving, never the same promise again, never a claim it is done."""
    item = r.get("item") or "the item"
    age = _age_words(int(r.get("age_min") or 0))
    return (f"the check on '{item}' was promised {age} ago and is still unanswered — "
            f"it has been referred to the team for a manual check with an owner (the system "
            f"recorded it; you need not call any tool for it). Say so in ONE line: a brief "
            f"apology that we promised to check and have not confirmed yet, that it is now "
            f"referred directly to our team, and that they will hear here once it is confirmed. "
            f"NEVER 'shortly' or 'right away' again, NEVER say it is confirmed or available, "
            f"NEVER a price for it; keep helping with everything else they ask")


async def _owner_of(db, conv) -> str:
    """'<name>' of the colleague assigned to this chat, or 'needs an owner'."""
    agent_id = getattr(conv, "assigned_agent_id", None)
    if agent_id is None:
        return "needs an owner"
    try:
        from app.models.agent import Agent
        a = await db.get(Agent, agent_id)
        name = (getattr(a, "name", None) or getattr(a, "email", None) or str(agent_id)) if a else str(agent_id)
        return str(name)
    except Exception:
        return str(agent_id)


async def _ring(redis, conv, *, stage: str, item: str, age_min: int, owner: str,
                follow_ups: int) -> None:
    if redis is None:
        return
    ext = getattr(conv, "wa_id", None) or getattr(conv, "external_id", None) or "?"
    title = (f"🚨 Unanswered check — {_age_words(age_min)}: {item}" if stage == "supervisor"
             else f"⏳ Check still open — {_age_words(age_min)}: {item}")
    body = (f"{ext} — owner: {owner}. "
            + (f"The customer has followed up {follow_ups}×. " if follow_ups else "")
            + ("Supervisor: this commitment is past the escalation target."
               if stage == "supervisor" else "Please confirm and reply in the thread."))
    try:
        await redis.publish("ws:channel:agents:all", json.dumps({
            "event": "notification", "type": f"commitment_{stage}",
            "title": title[:120], "body": body[:200],
            "conversationId": str(conv.id), "conv_id": str(conv.id), "wa_id": str(ext),
        }))
    except Exception as exc:
        _log.info("commitment bell not sent for %s: %s", ext, exc)


async def escalate(db, redis, conv, deal, *, stage: str, reason: str,
                   followed_up: bool = False, now: datetime | None = None) -> dict | None:
    """Record ONE intervention at `stage` (idempotent: a stage already
    recorded is not recorded again; a follow-up still counts and re-rings).
    Returns the escalation record, or None when nothing was due."""
    if stage not in STAGES:
        return None
    r = reading(deal, now=now)
    if r is None:
        return None
    now = _aware(now) or datetime.now(timezone.utc)
    nxt = dict(deal.next_action or {})
    esc = dict(nxt.get("escalation") or {})
    already = esc.get("stage") or ""
    rank = {"": 0, "team": 1, "supervisor": 2}
    follow_ups = int(esc.get("follow_ups") or 0) + (1 if followed_up else 0)
    new_stage = rank[stage] > rank.get(already, 0)
    if not new_stage and not followed_up:
        return esc or None
    owner = await _owner_of(db, conv)
    if new_stage:
        esc.update({"stage": stage, "at": now.isoformat(timespec="seconds"), "reason": reason,
                    "owner": owner})
        esc.setdefault("first_at", esc["at"])
    esc["follow_ups"] = follow_ups
    if followed_up:
        esc["last_follow_up"] = now.isoformat(timespec="seconds")
    nxt["escalation"] = esc
    deal.next_action = nxt
    try:
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(deal, "next_action")
    except Exception:
        pass
    if new_stage or followed_up:
        try:
            from app.models.intercept import Intercept, InterceptAction
            what = ("🚨 UNANSWERED CHECK (supervisor)" if stage == "supervisor"
                    else "⏳ UNANSWERED CHECK")
            note = (f"{what} — '{r['item']}' promised {_age_words(r['age_min'])} ago, "
                    f"still open. Owner: {owner}. "
                    + (f"The customer followed up ({follow_ups}×); Neema told them it is "
                       f"referred for a manual check. " if follow_ups else "")
                    + "Please confirm the item and reply in the thread — that reply closes it.")
            db.add(Intercept(conversation_id=conv.id, action=InterceptAction.flag, note=note[:2000]))
        except Exception:
            _log.info("commitment flag not recorded", exc_info=True)
    await db.commit()
    if new_stage:
        # A customer-level event on the timeline (services/timeline).
        try:
            from app.services import timeline as _tl
            await _tl.note(db, channel=getattr(conv, "channel", None) or "whatsapp",
                           contact=(getattr(conv, "wa_id", None) or getattr(conv, "external_id", None) or ""),
                           kind="commitment",
                           summary=f"Promised check escalated to the {stage}",
                           detail=f"'{r['item']}' promised {_age_words(r['age_min'])} ago, still open; owner: {owner}",
                           args={"stage": stage, "item": r["item"], "age_min": r["age_min"]})
        except Exception:
            pass
    await _ring(redis, conv, stage=stage, item=r["item"], age_min=r["age_min"], owner=owner,
                follow_ups=follow_ups)
    _log.info("commitment escalated: conv=%s stage=%s age=%smin owner=%s follow_ups=%s",
              getattr(conv, "id", "?"), stage, r["age_min"], owner, follow_ups)
    return esc


async def customer_followed_up(db, redis, key: str, channel: str, *,
                               now: datetime | None = None) -> dict | None:
    """The live turn's hook: when the customer writes while a commitment is
    OVERDUE, escalate it now (the stage its age earns, at least `team`),
    count the follow-up, and return the writer's note. None when no check is
    open or it is not yet overdue (the ordinary team-check note stands)."""
    from app.services.deals import _conversation_of, open_deal_for
    conv = await _conversation_of(db, key, channel)
    if conv is None:
        return None
    deal = await open_deal_for(db, conversation_id=conv.id)
    if deal is None:
        return None
    r = reading(deal, now=now)
    if not r or not r["overdue"]:
        return None
    stage = r["stage_due"] or "team"
    await escalate(db, redis, conv, deal, stage=stage, reason="customer followed up",
                   followed_up=True, now=now)
    return writer_note(r)


# ── closing a check whose reply day has passed (owner, 2026-11-14) ───────────

def lapse_hours() -> int:
    return int(getattr(settings, "commitment_lapse_hours", 24) or 0)


def direct_link(channel: str | None, external_id: str | None, *, permalink: str = "",
                comment_id: str = "") -> str:
    """Where a colleague can answer this customer DIRECTLY on the platform
    once our own reply window has closed: the comment itself on Facebook, the
    post on Instagram, the Page inbox thread on Messenger. "" for WhatsApp
    (outside the window only an approved template may be sent) and whenever
    there is nothing to point at."""
    ch = (channel or "").lower()
    page = str(getattr(settings, "meta_page_id", "") or "").strip()
    if ch == "facebook":
        link = (permalink or "").strip()
        cid = str(comment_id or "").rsplit("_", 1)[-1]
        if link and cid:
            return link + ("&" if "?" in link else "?") + "comment_id=" + cid
        return link
    if ch == "instagram" and (permalink or "").strip():
        return permalink.strip()
    if ch in ("messenger", "instagram") and page:
        base = f"https://business.facebook.com/latest/inbox/all?asset_id={page}"
        if ch == "messenger" and external_id:
            return (base + f"&mailbox_id={page}&selected_item_id={external_id}"
                    "&thread_type=FB_MESSAGE")
        return base
    return ""


async def link_for(db, conv) -> str:
    """direct_link for a conversation, read from its newest comment."""
    permalink = comment_id = ""
    ch = getattr(conv, "channel", None) or "whatsapp"
    if ch in ("facebook", "instagram"):
        try:
            from sqlalchemy import select
            from app.models.message import Message, MsgDirection
            m = (await db.execute(
                select(Message).where(Message.conversation_id == conv.id,
                                      Message.direction == MsgDirection.inbound,
                                      Message.comment_context.isnot(None))
                .order_by(Message.created_at.desc()).limit(1))).scalars().first()
            if m is not None:
                permalink = str((m.comment_context or {}).get("permalink") or "")
                comment_id = str(getattr(m, "waba_msg_id", "") or "")
        except Exception:
            _log.info("direct link: newest comment unreadable", exc_info=True)
    return direct_link(ch, getattr(conv, "external_id", None), permalink=permalink,
                       comment_id=comment_id)


async def _last_inbound_at(db, conv) -> datetime | None:
    from sqlalchemy import func as sa_func, select
    from app.models.message import Message, MsgDirection
    at = (await db.execute(select(sa_func.max(Message.created_at)).where(
        Message.conversation_id == conv.id,
        Message.direction == MsgDirection.inbound))).scalar()
    return _aware(at)


def lapsed(r: dict | None, last_in: datetime | None, *, now: datetime | None = None) -> bool:
    """Has this open check's reply day passed? True when the customer has not
    written for `commitment_lapse_hours` AND the check itself is that old —
    a check opened an hour ago on an old thread is still live. Never when the
    setting is 0 or the customer's last message cannot be read."""
    hours = lapse_hours()
    if not r or hours <= 0 or last_in is None:
        return False
    now = _aware(now) or datetime.now(timezone.utc)
    quiet_min = (now - last_in).total_seconds() / 60
    return quiet_min >= hours * 60 and int(r.get("age_min") or 0) >= hours * 60


async def lapse(db, conv, deal, r: dict, *, last_in: datetime | None,
                now: datetime | None = None) -> bool:
    """Close a check whose reply day has passed — recorded as UNANSWERED, never
    as answered: a flag row in the Activity log (with the place to answer the
    customer directly, when the platform has one) and the deal's closed record
    (`owner: lapsed`, the age). True when one was closed."""
    from app.services.deals import clear_team_check
    now = _aware(now) or datetime.now(timezone.utc)
    link = await link_for(db, conv)
    quiet = _age_words(int((now - last_in).total_seconds() // 60)) if last_in else "a while"
    try:
        from app.models.intercept import Intercept, InterceptAction
        note = (f"⌛ CHECK CLOSED UNANSWERED — '{r['item']}' was promised "
                f"{_age_words(int(r.get('age_min') or 0))} ago and nobody confirmed it. The customer "
                f"last wrote {quiet} ago, so the reply day has passed and the check is closed. "
                + (f"You can still answer them directly here: {link}" if link else
                   "On WhatsApp only an approved template can reach them now."))
        db.add(Intercept(conversation_id=conv.id, action=InterceptAction.flag, note=note[:2000]))
        await db.commit()
    except Exception:
        _log.info("lapse flag not recorded", exc_info=True)
    closed = await clear_team_check(db, conv.id, by="lapsed")
    if closed:
        _log.info("commitment lapsed: conv=%s age=%smin", getattr(conv, "id", "?"), r.get("age_min"))
    return closed


async def _open_checks(db, limit: int = 200) -> list:
    from sqlalchemy import select
    from app.models.conversation import Conversation
    from app.models.deal import Deal
    q = (select(Deal, Conversation)
         .join(Conversation, Conversation.id == Deal.conversation_id)
         .where(Deal.status == "open", Deal.next_action["kind"].astext == "team_check")
         .order_by(Deal.updated_at.asc()).limit(limit))
    return (await db.execute(q)).all()


async def sweep(redis=None, *, now: datetime | None = None, limit: int = 200) -> dict:
    """Escalate every overdue open check to the stage its age earns. Outside
    staffed hours nothing rings: the check is marked queued for the next
    staffed start and rings then. Returns counts. Best-effort."""
    from app.database import AsyncSessionLocal
    now = _aware(now) or datetime.now(timezone.utc)
    out = {"open": 0, "overdue": 0, "team": 0, "supervisor": 0, "queued": 0, "lapsed": 0}
    try:
        async with AsyncSessionLocal() as db:
            rows = await _open_checks(db, limit)
            for deal, conv in rows:
                r = reading(deal, now=now)
                if r is None:
                    continue
                # The reply day has passed: close it, unanswered and recorded
                # (owner, 2026-11-14) — whatever the hour.
                try:
                    last_in = await _last_inbound_at(db, conv)
                    if lapsed(r, last_in, now=now) and await lapse(db, conv, deal, r,
                                                                    last_in=last_in, now=now):
                        out["lapsed"] += 1
                        continue
                except Exception:
                    _log.info("lapse check skipped", exc_info=True)
                out["open"] += 1
                if not r["overdue"]:
                    continue
                out["overdue"] += 1
                if not staffed_now(now):
                    nxt = dict(deal.next_action or {})
                    esc = dict(nxt.get("escalation") or {})
                    if not esc.get("queued_for"):
                        esc["queued_for"] = next_staffed_start(now).isoformat(timespec="seconds")
                        nxt["escalation"] = esc
                        deal.next_action = nxt
                        try:
                            from sqlalchemy.orm.attributes import flag_modified
                            flag_modified(deal, "next_action")
                        except Exception:
                            pass
                        await db.commit()
                    out["queued"] += 1
                    continue
                stage = r["stage_due"]
                before = (r["escalation"] or {}).get("stage") or ""
                esc = await escalate(db, redis, conv, deal, stage=stage,
                                     reason="sweep: past the target", now=now)
                if esc and (esc.get("stage") or "") != before:
                    out[stage] += 1
    except Exception:
        _log.warning("commitments sweep failed", exc_info=True)
    return out


async def health_view(now: datetime | None = None) -> dict:
    """Counts only — never a handle, an item or a text."""
    from app.database import AsyncSessionLocal
    now = _aware(now) or datetime.now(timezone.utc)
    view = {"open": 0, "overdue": 0, "unowned": 0, "oldest_min": 0,
            "escalated": {"team": 0, "supervisor": 0}, "staffed": staffed_now(now),
            "closed_unanswered": 0}
    try:
        async with AsyncSessionLocal() as db:
            try:
                from sqlalchemy import func as sa_func, select
                from app.models.deal import Deal
                view["closed_unanswered"] = int((await db.execute(
                    select(sa_func.count()).select_from(Deal).where(
                        Deal.next_action["kind"].astext == "team_check_closed",
                        Deal.next_action["owner"].astext == "lapsed"))).scalar() or 0)
            except Exception:
                _log.info("closed-unanswered count unavailable", exc_info=True)
            for deal, conv in await _open_checks(db):
                r = reading(deal, now=now)
                if r is None:
                    continue
                view["open"] += 1
                view["oldest_min"] = max(view["oldest_min"], r["age_min"])
                if r["overdue"]:
                    view["overdue"] += 1
                if getattr(conv, "assigned_agent_id", None) is None:
                    view["unowned"] += 1
                st = (r["escalation"] or {}).get("stage")
                if st in view["escalated"]:
                    view["escalated"][st] += 1
    except Exception:
        _log.info("commitments health view unavailable", exc_info=True)
    return view
