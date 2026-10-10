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

BUT NEVER OVER A WAITING CUSTOMER (owner, 2026-10-10). A thread whose newest
message is a customer message nobody — colleague or Neema — has answered stays
with the person it was handed to: they were alerted, and they get the chance to
reply. In 30 days 1,500 of 1,544 auto-releases happened on exactly such a
thread, most of them minutes after the missed-reply sweeper had escalated it —
a flag→release ping-pong every ~6 minutes that no colleague could ever catch.
A polite closer ("thanks", "🙏") is not waiting on anyone.

A HOLD STAYS WITH STAFF UNTIL A PERSON REPLIES (owner: "held replies → Human +
notify"). A thread handed over by a flag — a reviewer hold, a sweeper
escalation, a failed order — is waiting on a colleague even though Neema's own
hand-off line ("a colleague will confirm it here") went out after the
customer's message: that line is a promise, not an answer. Only a colleague's
sent reply after the hold ends it (a staff take-over or release after the flag
closes it too, and then the ordinary rules apply). The 45-minute clock
itself is unchanged: once someone answers, it runs from the last colleague
message as before. A release leaves an internal note on the thread itself so
staff can see why Neema has it back.
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
# The same handover, on the thread itself (an internal note — never sent).
_THREAD_NOTE = ("↩ Returned to Neema automatically — no colleague reply for {mins} minutes, "
                "and {why}, so nobody is left waiting. Neema will answer their next "
                "message; take the thread back any time.")


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
                if waiting:
                    continue            # the person alerted gets the chance to reply

                conv.intercept_mode    = InterceptMode.ai
                conv.assigned_agent_id = None
                conv.intercept_since   = None
                db.add(Intercept(conversation_id=conv.id, agent_id=None,
                                 action=InterceptAction.release,
                                 note=_NOTE.format(mins=mins)))
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
