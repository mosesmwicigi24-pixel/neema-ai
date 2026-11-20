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

A polite closer ("thanks", "🙏") is not waiting on anyone, and a chat nobody is
waiting on is released when the colleague has been quiet for
`auto_release_minutes`, as before. A release leaves an internal note on the
thread so staff can see why Neema has it back.
"""
from __future__ import annotations

import logging
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
    try:
        async with AsyncSessionLocal() as db:
            convs = (await db.execute(
                select(Conversation)
                .where(Conversation.intercept_mode == InterceptMode.human)
                .limit(limit)
            )).scalars().all()

            for conv in convs:
                touched = await _last_human_touch(db, conv.id)
                # No colleague has spoken → fall back to when it was taken over,
                # so a thread intercepted and then abandoned is still released.
                since = touched or conv.intercept_since
                if since is None:
                    continue
                if since.tzinfo is None:
                    since = since.replace(tzinfo=timezone.utc)
                if since > cutoff:
                    continue            # a colleague is actively on it — leave them to it
                waiting, why = await _customer_waiting(db, conv.id)
                waited = False
                if waiting:
                    # THE PERSON GETS THEIR 30 MINUTES, THEN NEEMA PICKS UP
                    # (owner, 2026-11-19). Counted from when the customer began
                    # waiting, and only once for that wait.
                    if not getattr(settings, "auto_release_waiting", True):
                        continue
                    ws = await _waiting_since(db, conv.id)
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

    if released:
        _log.info("auto-release: %d conversation(s) returned to AI after %dm quiet",
                  released, mins)
    return released
