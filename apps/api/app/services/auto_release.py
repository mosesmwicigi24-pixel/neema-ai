"""Hand a quiet human-held conversation back to the AI.

Intercept was a one-way door. `intercept_mode = human` is set by a colleague
replying from the dashboard, by an explicit `handoff_to_human`, and by certain
hub events — but the only ways back to `ai` were a person clicking **Release** or
a full conversation wipe. There was no time-based release anywhere, so every
takeover was permanent until somebody remembered to undo it.

The result was silence: a customer whose thread a colleague answered once got no
further replies from Neema at all, and the missed-reply sweeper couldn't help
either (it only selects `intercept_mode == ai`). `selfcheck` has been reporting
this for a while — "N human-held thread(s) where the customer has waited 48h+ —
pick up or release" — but reporting it was all anyone did.

So: when a human-held thread has gone quiet — no colleague has said anything for
`auto_release_minutes` — it returns to the AI, with a `release` row in the
Activity timeline so the handover is visible rather than mysterious.

Releasing is safe by construction: it does not make Neema say anything. It only
makes her *able* to answer the next message, instead of that message landing in
a thread nobody is watching.

THIRTY MINUTES, THEN NEEMA PICKS UP (owner, 2026-11-19: "If the human
interception remains for 30 minutes without being released and without chats
continue, release that chat to Neema … this avoids chats that have been taken
by humans to remain inactive").

Two earlier rules kept a chat with the person for good, and those were the
chats that sat inactive:

  * 2026-10-10, "never over a waiting customer": a chat whose newest message
    was an unanswered customer message was never released (in 30 days 1,500
    of 1,544 releases had landed on such a chat minutes after the missed-reply
    sweeper escalated it — a flag→release ping-pong every ~6 minutes);
  * "a hold stays with staff until a person replies": a chat flagged to the
    team (a held reply, a failed order, a delivery failure) waited for a
    colleague however long that took.

Now the person gets their thirty minutes, counted from when the customer began
waiting (`_waiting_since`). After that the chat returns to Neema, and because
its newest message is an unanswered customer message the missed-reply sweeper
(services/reply_sweeper) answers it within a couple of minutes — while the
channel's reply window is open (23 hours). She is told on that turn how she
got the chat back (PICKED_UP_NOTE): no pretending a colleague answered.

THE PING-PONG CANNOT START: one automatic release per wait
(`_auto_released_since`). If her answer is held again, or the chat is
escalated again, it stays with staff until a person replies or the customer
writes anew. `auto_release_waiting = false` restores the 2026-10-10 rule.

TWO ADDITIONS (owner, 2026-11-20: "Merge and do 1 and 2"):

  1. THE WARNING. `auto_release_warn_minutes` (20) into a customer's wait, the
     colleague holding the chat is told, by name, on the team bell: it goes
     back to Neema in about ten minutes unless they reply. Once per wait.
     Only for a chat where the customer is waiting — a chat nobody is waiting
     on returns quietly, as it always did.
  2. MONEY MATTERS STAY WITH A PERSON, AND ARE CHASED. A chat held for a
     refund, a part-payment, a complaint or a delayed order (`_money_hold`)
     is never handed back while no colleague has replied: only a person may
     decide those. Instead, at `auto_release_minutes` the team is alerted
     again and — if the customer is waiting and the channel's window is open
     — Neema sends ONE honest holding line (`HOLDING_LINE`: no promise, no
     time, no decision); at `money_hold_owner_minutes` (120) the owner is
     alerted. Each once per hold, recorded as a thread note. The moment a
     colleague replies the hold is closed and the ordinary rule applies.

A polite closer ("thanks", "🙏") is not waiting on anyone, and a chat nobody is
waiting on is released when the colleague has been quiet for
`auto_release_minutes`, as before. A release leaves an internal note on the
thread so staff can see why Neema has it back.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from app.core.config import settings
from app.models.conversation import Conversation, InterceptMode
from app.models.intercept import Intercept, InterceptAction
from app.models.message import Message, MsgDirection, MsgSender

_log = logging.getLogger("neema.agent")

_NOTE = "Returned to AI automatically — no agent reply for {mins} minutes"
_NOTE_WAITED = "Returned to AI automatically — the customer waited {mins} minutes with no agent reply"
WAITED_WHY = "the customer was still waiting for an answer"
# Told to Neema on her next turn in a chat she got back this way.
PICKED_UP_KEY = "agent:autoreleased:{channel}:{key}"
PICKED_UP_NOTE = (
    "\n\n(This chat was with a colleague, who did not reply for {mins} minutes, so it is back "
    "with you. Do not say or imply that a colleague answered. Answer what the customer is "
    "waiting for, as far as your tools and facts allow. If it truly needs a person — a "
    "refund, a complaint decision, a price only a colleague can set — say honestly that a "
    "colleague has not been able to pick it up yet and that you have raised it again, and "
    "raise it with the proper tool. One short apology for the wait, once.)")
# The same handover, on the thread itself (an internal note — never sent).
# One short line (owner, 2026-11-15: notes "too many and too long"); it sits in
# the thread note's history, not in the chat.
_THREAD_NOTE = "↩ Back to Neema — no colleague reply in {mins} min; {why}."


# ── 1. the warning ───────────────────────────────────────────────────────────
WARNED_KEY = "agent:autorelease:warned:{conv}:{since}"

# ── 2. money matters: with a person, chased ──────────────────────────────────
# What makes a held chat a money matter: the reason it was handed over. Read
# from the hand-over records themselves (hub escalations, a complaint case,
# Neema's own hand-off reason) — never from the customer's words.
_MONEY_KINDS = (
    ("a refund", re.compile(r"\brefund", re.I)),
    ("a part-payment", re.compile(r"\bpartial payment|\bpart[\s-]?pay", re.I)),
    ("a complaint", re.compile(r"\bcomplain", re.I)),
    ("a delayed order", re.compile(r"\border delayed", re.I)),
)
# Thread notes that carry a hand-over reason (tools._handoff_to_human, hub_events._escalate).
_REASON_NOTES = ("🙋 HANDED TO THE TEAM", "⚠️")
_CHASE_TEAM = "💰 Still needs a person"
_CHASE_OWNER = "🔴 Owner alerted"
_NOTE_TEAM = _CHASE_TEAM + " — {kind}, no colleague reply in {mins} min. Team alerted again."
_NOTE_OWNER = _CHASE_OWNER + " — {kind} has waited {hours} h for a person."
HOLDING_KIND = "person_hold_line"
# The one line the customer gets while a money matter waits on a person. It
# promises nothing, names no time and decides nothing — only what is true.
HOLDING_LINE = {
    "en": ("Thank you for your patience. This needs a decision from one of my colleagues, "
           "and they have not been able to reply yet. I have raised it with them again, "
           "and they will answer you here."),
    "sw": ("Asante kwa uvumilivu wako. Jambo hili linahitaji uamuzi wa mwenzangu, na bado "
           "hajaweza kujibu. Nimelifuatilia tena, na atakujibu hapa hapa."),
}
_WINDOW = timedelta(hours=23)           # the channels' reply window, as the sweeper uses it
_SEND_CHANNELS = ("whatsapp", "messenger", "instagram")


def money_kind(text) -> str | None:
    """The money matter a hand-over reason names, or None."""
    for kind, rx in _MONEY_KINDS:
        if rx.search(str(text or "")):
            return kind
    return None


def _aware(t: datetime | None) -> datetime | None:
    return t if t is None or t.tzinfo is not None else t.replace(tzinfo=timezone.utc)


async def _colleague_replied_since(db, conv_id, since: datetime) -> bool:
    n = (await db.execute(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conv_id,
            Message.sender == MsgSender.human_agent,
            Message.created_at >= since,
            or_(Message.media_type.is_(None), Message.media_type != "note",
                and_(Message.agent_id.isnot(None),
                     Message.text.startswith(_TEAM_ANSWER_NOTE))),
        ))).scalar_one()
    return bool(n)


async def _money_hold(db, conv) -> tuple[str, datetime] | None:
    """(kind, since) when this held chat is an OPEN money matter: it was handed
    over for a refund, a part-payment, a complaint or a delayed order since it
    was last released, and no colleague has replied since. `since` is when a
    person became responsible for it."""
    last_release = (await db.execute(
        select(func.max(Intercept.created_at)).where(
            Intercept.conversation_id == conv.id,
            Intercept.action == InterceptAction.release))).scalar_one_or_none()
    iq = select(Intercept.note, Intercept.created_at).where(
        Intercept.conversation_id == conv.id, Intercept.note.isnot(None),
        Intercept.action.in_(_HOLD_OPENS + (InterceptAction.intercept,)))
    mq = select(Message.text, Message.created_at).where(
        Message.conversation_id == conv.id, Message.media_type == "note",
        or_(*[Message.text.startswith(p) for p in _REASON_NOTES]))
    if last_release is not None:
        iq = iq.where(Intercept.created_at > last_release)
        mq = mq.where(Message.created_at > last_release)
    found: list[tuple[datetime, str]] = []
    for text, at in list((await db.execute(iq)).all()) + list((await db.execute(mq)).all()):
        # the note's own first line is the reason; a drafted reply under it is not
        kind = money_kind(str(text or "").split("\n\n", 1)[0])
        if kind and at is not None:
            found.append((_aware(at), kind))
    if not found:
        return None
    at, kind = min(found)
    since = max(at, _aware(conv.intercept_since) or at)
    if await _colleague_replied_since(db, conv.id, at):
        return None
    return kind, since


async def _noted_since(db, conv_id, prefix: str, since: datetime) -> bool:
    n = (await db.execute(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conv_id, Message.media_type == "note",
            Message.text.startswith(prefix), Message.created_at >= since))).scalar_one()
    return bool(n)


def _thread_note(conv, text: str) -> Message:
    return Message(
        channel=conv.channel, wa_id=conv.wa_id, external_id=conv.external_id,
        person_id=conv.person_id, conversation_id=conv.id,
        direction=MsgDirection.outbound, sender=MsgSender.ai,
        text=text, media_type="note", created_at=datetime.now(timezone.utc))


async def _bell(redis, conv, title: str, body: str, **extra) -> None:
    if redis is None:
        return
    ext = conv.wa_id or conv.external_id
    try:
        await redis.publish("ws:channel:agents:all", json.dumps({
            "event": "notification", "type": "human_transfer",
            "title": title[:120], "body": body[:200],
            "conversationId": str(conv.id), "conv_id": str(conv.id), "wa_id": ext, **extra}))
    except Exception as exc:
        _log.info("auto-release bell not sent for %s: %s", conv.id, exc)


async def _send_holding_line(redis, conv, ext: str, text: str) -> None:
    from app.database import AsyncSessionLocal
    from app.services import messaging as svc
    meta = {"v": 1, "kind": HOLDING_KIND}
    if conv.channel == "whatsapp":
        wamid = await svc._send_waba(ext, text)
        async with AsyncSessionLocal() as db:
            await svc.save_outbound_message(db, redis, ext, text, waba_msg_id=wamid, raw_meta=meta)
    else:
        from app.services.meta_send import send_to_channel
        from app.services.reply_sweeper import _page_id_for
        async with AsyncSessionLocal() as db:
            page_id = await _page_id_for(db, conv.channel, ext)
        await send_to_channel(conv.channel, ext, text, page_id=page_id)
        async with AsyncSessionLocal() as db:
            await svc.save_outbound_channel_message(db, redis, conv.channel, ext, text,
                                                    raw_meta=meta)


async def _chase_money_hold(redis, conv_id, kind: str, since: datetime) -> dict:
    """Chase one open money matter. Team at `auto_release_minutes`, with one
    holding line to a waiting customer; the owner at `money_hold_owner_minutes`.
    Each once per hold (the thread note is the record). Never raises."""
    out = {"team": False, "owner": False, "line": False}
    from app.database import AsyncSessionLocal
    try:
        now = datetime.now(timezone.utc)
        age = now - since
        team_at = int(getattr(settings, "auto_release_minutes", 0) or 0)
        owner_at = int(getattr(settings, "money_hold_owner_minutes", 0) or 0)
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, conv_id)
            if conv is None:
                return out
            ext = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
            mins = int(age.total_seconds() // 60)
            if team_at > 0 and age >= timedelta(minutes=team_at) \
                    and not await _noted_since(db, conv.id, _CHASE_TEAM, since):
                db.add(_thread_note(conv, _NOTE_TEAM.format(kind=kind, mins=mins)))
                await db.commit()
                out["team"] = True
                await _bell(redis, conv, f"💰 {kind.capitalize()} still needs a person — {mins} min",
                            f"{ext}: no colleague has replied. Neema will not decide this — "
                            "please pick it up.", money=kind)
                out["line"] = await _maybe_holding_line(db, redis, conv, ext, since, now)
            if owner_at > 0 and age >= timedelta(minutes=owner_at) \
                    and not await _noted_since(db, conv.id, _CHASE_OWNER, since):
                hours = round(age.total_seconds() / 3600, 1)
                db.add(_thread_note(conv, _NOTE_OWNER.format(kind=kind, hours=f"{hours:g}")))
                await db.commit()
                out["owner"] = True
                await _bell(redis, conv, f"🔴 OWNER: {kind} has waited {hours:g} h for a person",
                            f"{ext}: handed to the team and nobody has replied. "
                            "Please take it or assign it now.", money=kind, for_owner=True)
    except Exception:
        _log.warning("money-hold chase failed for %s", conv_id, exc_info=True)
    return out


async def _maybe_holding_line(db, redis, conv, ext, since: datetime, now: datetime) -> bool:
    """One honest line, only to a customer who is waiting, only inside the
    channel's window, only once for this hold."""
    if not getattr(settings, "money_hold_line", True):
        return False
    if conv.channel not in _SEND_CHANNELS or not ext or str(ext).startswith("web_"):
        return False
    from app.agent.runtime import is_closer
    last = (await db.execute(
        select(Message.direction, Message.text, Message.created_at)
        .where(Message.conversation_id == conv.id,
               or_(Message.media_type.is_(None), Message.media_type != "note"))
        .order_by(Message.created_at.desc()).limit(1))).first()
    if last is None or last[0] != MsgDirection.inbound or is_closer(last[1] or ""):
        return False
    if now - _aware(last[2]) > _WINDOW:
        return False
    sent = (await db.execute(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conv.id, Message.created_at >= since,
            func.coalesce(Message.raw_meta["kind"].astext, "") == HOLDING_KIND))).scalar_one()
    if sent:
        return False
    from app.agent.voice import looks_swahili
    try:
        await _send_holding_line(redis, conv, ext,
                                 HOLDING_LINE["sw" if looks_swahili(last[1] or "") else "en"])
        return True
    except Exception as exc:
        _log.warning("holding line not sent for %s/%s: %s", conv.channel, conv.id, exc)
        return False


async def _warn_before_release(db, redis, conv, ws: datetime, mins: int) -> bool:
    """Tell the colleague holding the chat that it goes back to Neema soon.
    Once per wait; needs redis (it is both the bell and the once-only mark)."""
    warn = int(getattr(settings, "auto_release_warn_minutes", 0) or 0)
    if redis is None or warn <= 0 or warn >= mins:
        return False
    now = datetime.now(timezone.utc)
    waited = now - ws
    if waited < timedelta(minutes=warn):
        return False
    if await _auto_released_since(db, conv.id, ws):
        return False                    # it will not be released again for this wait
    try:
        if not await redis.set(WARNED_KEY.format(conv=conv.id, since=int(ws.timestamp())), "1",
                               nx=True, ex=6 * 3600):
            return False
    except Exception:
        return False
    who = "Team"
    if conv.assigned_agent_id is not None:
        try:
            from app.models.agent import Agent
            agent = await db.get(Agent, conv.assigned_agent_id)
            who = (getattr(agent, "name", "") or "").split(" ")[0] or who
        except Exception:
            pass
    left = max(1, mins - int(waited.total_seconds() // 60))
    ext = conv.wa_id or conv.external_id
    await _bell(redis, conv, f"⏰ {who}: this chat goes back to Neema in {left} min",
                f"{ext} has waited {int(waited.total_seconds() // 60)} min for a reply. "
                "Reply now to keep it — otherwise Neema answers.",
                agent_id=(str(conv.assigned_agent_id) if conv.assigned_agent_id else None))
    return True


# Intercept rows that open a hold (a flag/escalation hands the thread to the
# team) or close it (a person taking over, or releasing, after it).
_HOLD_OPENS = (InterceptAction.flag, InterceptAction.escalated)
_HOLD_ROWS = _HOLD_OPENS + (InterceptAction.intercept, InterceptAction.release)
# answer_through_neema: the colleague's answer goes out in Neema's voice
# (sender ai), and this note — written with the colleague's agent_id — records it.
_TEAM_ANSWER_NOTE = "📣 Team answer delivered via Neema"


async def _hold_unanswered(db, conv_id) -> bool:
    """True when the thread's latest hold (flag/escalation) has had no reply
    from a colleague since. A colleague reply = a SENT human_agent message, or
    the record of a team answer delivered through Neema. System notes written
    as human_agent (availability checks, briefs, hub events) are not one, and
    neither is any line Neema sent."""
    row = (await db.execute(
        select(Intercept.action, Intercept.created_at)
        .where(Intercept.conversation_id == conv_id, Intercept.action.in_(_HOLD_ROWS))
        .order_by(Intercept.created_at.desc())
        .limit(1)
    )).first()
    if row is None or row[0] not in _HOLD_OPENS:
        return False
    answered = (await db.execute(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conv_id,
            Message.sender == MsgSender.human_agent,
            Message.created_at >= row[1],
            or_(Message.media_type.is_(None), Message.media_type != "note",
                and_(Message.agent_id.isnot(None),
                     Message.text.startswith(_TEAM_ANSWER_NOTE))),
        )
    )).scalar_one()
    return not answered


async def _customer_waiting(db, conv_id) -> tuple[bool, str]:
    """(waiting, why-not) for a held thread. Waiting = its newest message that
    the customer could see (internal notes excluded — they are never an
    answer) is an inbound customer message that is not a polite closer, OR a
    hold on it has had no colleague reply (`_hold_unanswered`). A polite
    closer as the newest message is never waiting. When not waiting, `why`
    says what the thread's state is, for the release note."""
    from app.agent.runtime import is_closer
    last = (await db.execute(
        select(Message.direction, Message.sender, Message.text)
        .where(Message.conversation_id == conv_id,
               or_(Message.media_type.is_(None), Message.media_type != "note"))
        .order_by(Message.created_at.desc())
        .limit(1)
    )).first()
    if last is not None and last[0] == MsgDirection.inbound and is_closer(last[2] or ""):
        return False, "the customer's last message was a polite close"
    if await _hold_unanswered(db, conv_id):
        return True, ""
    if last is None:
        return False, "there is no customer message waiting"
    direction, sender, text = last
    if direction == MsgDirection.inbound:
        return True, ""
    if sender == MsgSender.human_agent:
        return False, "a colleague answered the customer's last message"
    return False, "Neema answered the customer's last message"


async def _waiting_since(db, conv_id) -> datetime | None:
    """Since when the customer has been waiting on a person: the moment the
    latest unanswered hold was raised, else their first message after the
    last thing they were sent. None when that cannot be told."""
    hold = (await db.execute(
        select(Intercept.action, Intercept.created_at)
        .where(Intercept.conversation_id == conv_id, Intercept.action.in_(_HOLD_ROWS))
        .order_by(Intercept.created_at.desc()).limit(1))).first()
    visible = or_(Message.media_type.is_(None), Message.media_type != "note")
    last_out = (await db.execute(
        select(func.max(Message.created_at)).where(
            Message.conversation_id == conv_id, visible,
            Message.direction == MsgDirection.outbound))).scalar_one_or_none()
    q = select(func.min(Message.created_at)).where(
        Message.conversation_id == conv_id, visible, Message.direction == MsgDirection.inbound)
    if last_out is not None:
        q = q.where(Message.created_at > last_out)
    first_in = (await db.execute(q)).scalar_one_or_none()
    times = [t for t in (first_in, hold[1] if hold is not None and hold[0] in _HOLD_OPENS else None)
             if t is not None]
    if not times:
        return None
    t = min(times)
    return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)


async def _auto_released_since(db, conv_id, since: datetime) -> bool:
    """Was this chat already handed back automatically for THIS wait? One
    automatic release per waiting message: if Neema's answer was held or the
    chat was escalated again, it stays with staff until a person replies —
    the flag→release ping-pong of 2026-10 cannot start."""
    n = (await db.execute(
        select(func.count()).select_from(Intercept).where(
            Intercept.conversation_id == conv_id, Intercept.agent_id.is_(None),
            Intercept.action == InterceptAction.release, Intercept.created_at >= since,
        ))).scalar_one()
    return bool(n)


async def _last_human_touch(db, conv_id) -> datetime | None:
    """When a colleague last said something in this thread (None if never)."""
    return (await db.execute(
        select(func.max(Message.created_at)).where(
            Message.conversation_id == conv_id,
            Message.sender == MsgSender.human_agent,
        )
    )).scalar_one_or_none()


async def sweep_auto_release(redis=None, limit: int = 200) -> int:
    """Release quiet human-held conversations back to the AI. Returns how many.

    A thread qualifies when it is in human mode, the most recent colleague
    message (or, if none, the moment it was intercepted) is older than
    `auto_release_minutes`, AND the customer is not waiting on an answer
    (`_customer_waiting`). Best-effort: never raises, so a bad tick can't take
    the loop down."""
    mins = int(getattr(settings, "auto_release_minutes", 0) or 0)
    if mins <= 0:                       # 0 disables the sweep entirely
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=mins)

    from app.database import AsyncSessionLocal
    released = 0
    chase: list[tuple] = []
    try:
        async with AsyncSessionLocal() as db:
            convs = (await db.execute(
                select(Conversation)
                .where(Conversation.intercept_mode == InterceptMode.human)
                .limit(limit)
            )).scalars().all()

            for conv in convs:
                # A money matter no colleague has answered is never handed
                # back: it is chased instead (after this session closes).
                money = await _money_hold(db, conv)
                if money is not None:
                    chase.append((conv.id, money[0], money[1]))
                    continue
                touched = await _last_human_touch(db, conv.id)
                # No colleague has spoken → fall back to when it was taken over,
                # so a thread intercepted and then abandoned is still released.
                since = touched or conv.intercept_since
                if since is None:
                    continue
                if since.tzinfo is None:
                    since = since.replace(tzinfo=timezone.utc)
                waiting, why = await _customer_waiting(db, conv.id)
                waited = False
                ws = None
                if waiting and getattr(settings, "auto_release_waiting", True):
                    ws = await _waiting_since(db, conv.id)
                    if ws is not None and max(ws, since) > cutoff:
                        # not yet due — but the colleague is warned when it is close
                        await _warn_before_release(db, redis, conv, max(ws, since), mins)
                if since > cutoff:
                    continue            # a colleague is actively on it — leave them to it
                if waiting:
                    # THE PERSON GETS THEIR 30 MINUTES, THEN NEEMA PICKS UP
                    # (owner, 2026-11-19). Counted from when the customer began
                    # waiting, and only once for that wait.
                    if not getattr(settings, "auto_release_waiting", True):
                        continue
                    if ws is None or ws > cutoff:
                        continue        # the person alerted still has time to reply
                    if await _auto_released_since(db, conv.id, ws):
                        continue        # already handed back once for this wait: staff keep it
                    waited, why = True, WAITED_WHY

                conv.intercept_mode    = InterceptMode.ai
                conv.assigned_agent_id = None
                conv.intercept_since   = None
                db.add(Intercept(conversation_id=conv.id, agent_id=None,
                                 action=InterceptAction.release,
                                 note=(_NOTE_WAITED if waited else _NOTE).format(mins=mins)))
                db.add(Message(
                    channel=conv.channel, wa_id=conv.wa_id, external_id=conv.external_id,
                    person_id=conv.person_id, conversation_id=conv.id,
                    direction=MsgDirection.outbound, sender=MsgSender.ai,
                    text=_THREAD_NOTE.format(mins=mins, why=why), media_type="note",
                    created_at=datetime.now(timezone.utc),   # aware: sorts after what it explains
                ))
                released += 1

                if redis is not None:
                    try:
                        await redis.delete(f"context:{conv.wa_id}")
                        if waited:
                            # Neema is told, on her next turn here, how she got it back.
                            _k = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
                            await redis.set(PICKED_UP_KEY.format(channel=conv.channel, key=_k),
                                            str(mins), ex=24 * 3600)
                    except Exception:
                        pass

            if released:
                await db.commit()
    except Exception:
        _log.warning("auto-release sweep failed", exc_info=True)
        return 0

    for conv_id, kind, since in chase:
        await _chase_money_hold(redis, conv_id, kind, since)

    if released:
        _log.info("auto-release: %d conversation(s) returned to AI after %dm quiet",
                  released, mins)
    return released
