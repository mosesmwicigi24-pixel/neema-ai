"""Copilot mode — human-held conversations keep BOTH workers working (plan C).

When a human holds a thread, Neema stops talking but never stops working:
  C1 · handoff briefing — a note into the thread the moment a human takes over
  C2 · continuous drafting — every customer message gets a ready suggestion
       (published as the existing `ai_draft_ready` ws event the composer shows)
  C3 · the scribe — a capture-only pass that keeps saving facts (names, sizes,
       parish, role) from the conversation the HUMAN is having
  C4 · take-back — a resolved thread quiet for hours gets a "take it back?" ping

Everything is gated by COPILOT_MODE (default off) and best-effort: copilot
work can never break, delay, or leak into the customer-facing path.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings

_log = logging.getLogger("neema.copilot")

_bg: set = set()

TAKE_BACK_IDLE_HOURS = 4


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg.add(task)
    task.add_done_callback(_bg.discard)


# ── C2 + C3: customer wrote while a human holds the thread ───────────────────


def schedule_human_held(redis, key: str, channel: str, text: str) -> None:
    if not settings.copilot_mode or not (text or "").strip():
        return
    _spawn(_human_held(redis, key, channel, text))


async def _human_held(redis, key: str, channel: str, text: str) -> None:
    from app.database import AsyncSessionLocal
    from app.agent import runtime
    from app.models.conversation import Conversation

    # C2 — the ready draft, into the composer via the existing banner event.
    try:
        async with AsyncSessionLocal() as db:
            conv = await _conv_of(db, key, channel)
            if conv is None:
                return
            draft = (await runtime.run_turn(
                db, redis, wa_id=key, user_text=text, llm=runtime.build_llm(),
                channel=channel,
                external_id=(None if channel == "whatsapp" else key),
                read_only=True)).strip()
        if draft and redis is not None:
            await redis.publish(f"ws:channel:{conv.id}", json.dumps({
                "type": "ai_draft_ready", "conversationId": str(conv.id),
                "draft": draft}))
    except Exception as exc:
        _log.info("copilot draft failed for %s: %s", key, exc)

    # C3 — the scribe: save facts, say nothing.
    try:
        async with AsyncSessionLocal() as db:
            await runtime.run_turn(
                db, redis, wa_id=key, user_text=text, llm=runtime.build_llm(),
                channel=channel,
                external_id=(None if channel == "whatsapp" else key),
                scribe_only=True)
        async with AsyncSessionLocal() as db2:
            from app.services.deals import scribe_update
            await scribe_update(db2, key, channel, reply="", inbound_text=text)
    except Exception as exc:
        _log.info("copilot scribe failed for %s: %s", key, exc)


async def _conv_of(db, key: str, channel: str):
    from app.models.conversation import Conversation
    if channel == "whatsapp":
        return (await db.execute(select(Conversation).where(
            Conversation.wa_id == key))).scalar_one_or_none()
    return (await db.execute(select(Conversation).where(
        Conversation.channel == channel,
        Conversation.external_id == key))).scalar_one_or_none()


# ── C1: the handoff briefing ─────────────────────────────────────────────────


def schedule_briefing(redis, conv_id) -> None:
    if not settings.copilot_mode:
        return
    _spawn(_briefing(redis, conv_id))


async def _briefing(redis, conv_id) -> None:
    from app.database import AsyncSessionLocal
    from app.agent import runtime
    from app.models.conversation import Conversation
    from app.models.message import Message, MsgDirection, MsgSender
    try:
        # One briefing per takeover, whoever schedules it: rapid re-clicks and
        # racing tabs collapse into a single note (and a single model turn).
        if redis is not None:
            try:
                if not await redis.set(f"copilot:briefed:{conv_id}", "1",
                                       nx=True, ex=900):
                    return
            except Exception:
                pass
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, conv_id)
            if conv is None:
                return
            key = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
            brief = (await runtime.run_turn(
                db, redis, wa_id=key,
                user_text=("[HANDOFF BRIEFING — a human colleague is taking this "
                           "conversation over. Write FOR THEM, not the customer: "
                           "1-2 lines on where the sale stands, what's already "
                           "settled (items/colour/size/total), what's still open, "
                           "anything to avoid, and ONE suggested opening line. "
                           "Short bullets.]"),
                llm=runtime.build_llm(), channel=conv.channel,
                external_id=(None if conv.channel == "whatsapp" else conv.external_id),
                read_only=True)).strip()
            if not brief:
                return
            db.add(Message(
                channel=conv.channel, wa_id=conv.wa_id,
                external_id=getattr(conv, "external_id", None),
                person_id=conv.person_id, conversation_id=conv.id,
                direction=MsgDirection.outbound, sender=MsgSender.human_agent,
                text=f"🤝 Handoff briefing\n\n{brief}", media_type="note",
            ))
            await db.commit()
    except Exception as exc:
        _log.info("briefing failed for %s: %s", conv_id, exc)


# ── C4: take it back? ────────────────────────────────────────────────────────


async def take_back_scan(db, redis) -> int:
    """Human-held threads quiet for hours → one polite ping per day."""
    if not settings.copilot_mode or redis is None:
        return 0
    from app.models.conversation import Conversation, InterceptMode, ConvStatus
    cutoff = datetime.now(timezone.utc) - timedelta(hours=TAKE_BACK_IDLE_HOURS)
    convs = (await db.execute(select(Conversation).where(
        Conversation.intercept_mode == InterceptMode.human,
        Conversation.status == ConvStatus.open,
        Conversation.last_message_at < cutoff,
    ).limit(20))).scalars().all()
    n = 0
    for c in convs:
        try:
            fresh = await redis.set(f"takeback:{c.id}", "1", nx=True, ex=86400)
            if not fresh:
                continue
            await redis.publish("ws:channel:agents:all", json.dumps({
                "event": "notification", "type": "take_back",
                "title": "🤝 Take this back?",
                "body": (f"{getattr(c, 'contact_name', None) or c.wa_id or c.external_id}: "
                         f"quiet for {TAKE_BACK_IDLE_HOURS}h in human mode — release "
                         "to Neema so nothing slips."),
                "conv_id": str(c.id), "wa_id": c.wa_id or c.external_id}))
            n += 1
        except Exception:
            continue
    return n
