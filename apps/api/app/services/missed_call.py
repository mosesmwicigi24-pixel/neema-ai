"""A missed call is a customer waiting: tell them we saw it, keep the thread
warm, and put the conversation in front of a person.

Opt-in (`missed_call_message_enabled`, default off) because it messages the
customer. A missed inbound call has just opened (or refreshed) the 24-hour
window — Meta's pricing doc: an inbound call does so "regardless of if you
accept the call or not" — so a free-form message is allowed.

Never more than one per customer per `missed_call_message_cooldown_h`, never
after they were already called back or spoken to, and never on the webhook's
critical path (scheduled as a background task; every failure only logs).
"""
import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings

_log = logging.getLogger("neema.wa")
_bg: set = set()


def schedule(redis, call_id: str) -> None:
    """Fire-and-forget the follow-up for a call that just ended missed."""
    if not settings.missed_call_message_enabled:
        return
    task = asyncio.create_task(_follow_up(redis, call_id))
    _bg.add(task)
    task.add_done_callback(_bg.discard)


async def _follow_up(redis, call_id: str) -> bool:
    """Returns True when the message went out (tests)."""
    try:
        from app.database import AsyncSessionLocal
        from app.models.call import Call
        from app.services import call_log
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c is None or call_log.normalize_status(c.status) != "missed" or c.direction == "outbound":
                return False
            channel = getattr(c, "channel", None) or "whatsapp"
            handle = c.wa_id if channel == "whatsapp" else getattr(c, "external_id", None)
            if not handle:
                return False
            # Already handled: a later connected call with them (either way).
            later = (await db.execute(
                select(Call.id).where(
                    (Call.wa_id == handle) if channel == "whatsapp" else (Call.external_id == handle),
                    Call.started_at > c.started_at,
                    Call.status.in_(("answered", "completed", "ended")),
                ).limit(1))).first()
            if later is not None:
                return False
        key = f"call:missed-msg:{channel}:{handle}"
        if redis is not None:
            ttl = max(1, int(settings.missed_call_message_cooldown_h)) * 3600
            try:
                if not await redis.set(key, "1", nx=True, ex=ttl):
                    return False            # told them recently — one message is enough
            except Exception:
                pass
        text = (settings.missed_call_message or "").strip()
        if not text:
            return False
        from app.services.meta_send import send_to_channel
        wamid = await send_to_channel(channel, handle, text)
        from app.services import n8n_bridge as bridge
        async with AsyncSessionLocal() as db:
            if channel == "whatsapp":
                await bridge.save_outbound_message(db, redis, handle, text, waba_msg_id=wamid)
            else:
                await bridge.save_outbound_channel_message(db, redis, channel, handle, text)
        # A person owes them a call: flag the conversation (Needs Attention).
        try:
            from app.services.conversation import record_escalation
            from app.services.call_log import conversation_ids_for
            async with AsyncSessionLocal() as db:
                if channel == "whatsapp":
                    conv_id = (await conversation_ids_for(db, [handle])).get(handle)
                else:
                    from app.services.channel import get_or_create_conversation
                    conv_id = str((await get_or_create_conversation(db, channel, handle)).id)
                if conv_id:
                    await record_escalation(db, conv_id, "Missed call — call them back", redis=redis)
        except Exception as exc:
            _log.warning("missed-call flag failed for %s: %s", call_id, exc)
        return True
    except Exception as exc:
        _log.warning("missed-call follow-up failed for %s: %s", call_id, exc)
        return False
