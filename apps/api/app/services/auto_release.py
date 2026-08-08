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
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.config import settings
from app.models.conversation import Conversation, InterceptMode
from app.models.intercept import Intercept, InterceptAction
from app.models.message import Message, MsgSender

_log = logging.getLogger("neema.agent")

_NOTE = "Returned to AI automatically — no agent reply for {mins} minutes"


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

    A thread qualifies when it is in human mode and the most recent colleague
    message (or, if none, the moment it was intercepted) is older than
    `auto_release_minutes`. Best-effort: never raises, so a bad tick can't take
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

                conv.intercept_mode    = InterceptMode.ai
                conv.assigned_agent_id = None
                conv.intercept_since   = None
                db.add(Intercept(conversation_id=conv.id, agent_id=None,
                                 action=InterceptAction.release,
                                 note=_NOTE.format(mins=mins)))
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
