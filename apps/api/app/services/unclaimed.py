"""UNCLAIMED HUMAN CHATS (owner, 2026-11-05).

A chat handed to the team — an escalation, a held reply, a media hand-off —
that nobody picked up stayed silent for as long as nobody acted: the live
path never answers a human-mode thread, the missed-reply sweeper retries
AI-mode threads only, and auto-release refuses while the customer is
waiting. Mama Beth's "what about the sacrament bowl + incense burner?" sat
nine hours with the incense burner priced in the hub all along.

Every tick, a thread in human mode with NO assigned agent whose latest
message is the customer's and older than `unclaimed_alert_minutes`:

  1. the team is rung again (the super admin included), naming the chat;
  2. if `unclaimed_answer`, Neema answers ONLY a plain price or stock
     question from the hub — one short sentence, verified by the reply gate
     like any other — and then, as a second message, says a colleague will
     follow up on the rest. Anything else (a bargain, a complaint, a design,
     an order) she leaves to the colleague: the writer answers SKIP.

Once per customer message. The thread stays in human mode: the colleague is
still needed, and the answer is noted on the thread for them.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from app.core.config import settings
from app.models.conversation import Conversation, InterceptMode
from app.models.intercept import Intercept, InterceptAction
from app.models.message import Message, MsgDirection

_log = logging.getLogger("neema.unclaimed")

CHANNELS = ("whatsapp", "messenger", "instagram")
HANDLED_TTL_S = 2 * 86400
SKIP = "SKIP"

NOTE = (
    "\n\n[UNCLAIMED HUMAN CHAT — a colleague was asked to take this conversation and has "
    "not yet. This ONE message only: if the customer's latest message is a plain PRICE or "
    "STOCK / AVAILABILITY question about an item we sell, answer it from search_catalog "
    "in ONE short sentence — the item and its price (or that it is in stock / made to "
    "order) — nothing else: no greeting, no question back, no suggestion. If their "
    "message is ANYTHING else (a bargain, a complaint, a design, measurements, an order, "
    "a payment, a request for a person, small talk), reply with exactly: SKIP]"
)
FOLLOW = {
    "en": "A colleague will follow up with you shortly on the rest.",
    "sw": "Mwenzangu wa timu atakufuatilia hivi karibuni kuhusu mengine.",
}
_THREAD_NOTE = ("⏳ Unclaimed for {mins} min — Neema answered the price/stock question from the "
                "hub and told the customer a colleague will follow up. The chat still needs "
                "a person: please pick it up.")
_THREAD_NOTE_SKIP = ("⏳ Unclaimed for {mins} min — the customer is waiting on something only a "
                     "person can answer. Please pick it up.")


def _handled_key(msg_id) -> str:
    return f"unclaimed:{msg_id}"


async def _candidates(db, minutes: int, limit: int) -> list:
    now = datetime.now(timezone.utc)
    young = now - timedelta(minutes=minutes)
    old = now - timedelta(hours=23)               # Meta's send window; WhatsApp follows it too
    latest = (
        select(Message.conversation_id, func.max(Message.created_at).label("m"))
        .where(Message.channel.in_(CHANNELS),
               or_(Message.media_type.is_(None), Message.media_type != "note"))
        .group_by(Message.conversation_id).subquery()
    )
    q = (
        select(Message, Conversation)
        .join(latest, and_(Message.conversation_id == latest.c.conversation_id,
                           Message.created_at == latest.c.m))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.direction == MsgDirection.inbound,
               Message.comment_context.is_(None),
               Message.created_at < young, Message.created_at > old,
               Conversation.intercept_mode == InterceptMode.human,
               Conversation.assigned_agent_id.is_(None))
        .order_by(Message.created_at.asc()).limit(limit)
    )
    return (await db.execute(q)).all()


async def _ring(redis, conv, ext: str, said: str | None, mins: int) -> None:
    if redis is None:
        return
    try:
        words = " ".join((said or "").split())[:140]
        await redis.publish("ws:channel:agents:all", json.dumps({
            "event": "notification", "type": "human_transfer",
            "title": f"⏳ Nobody has picked up {ext} — {mins} min",
            "body": (f"“{words}” — in Human with no one assigned. Pick it up, or the "
                     "super admin can take it over.")[:200],
            "conversationId": str(conv.id), "conv_id": str(conv.id), "wa_id": ext,
        }))
    except Exception as exc:
        _log.info("unclaimed bell not sent for %s: %s", ext, exc)


async def _send(redis, conv, ext: str, text: str, page_id) -> None:
    from app.database import AsyncSessionLocal
    from app.services import n8n_bridge as svc
    if conv.channel == "whatsapp":
        wamid = await svc._send_waba(ext, text)
        async with AsyncSessionLocal() as db:
            await svc.save_outbound_message(db, redis, ext, text, waba_msg_id=wamid)
    else:
        from app.services.meta_send import send_to_channel
        await send_to_channel(conv.channel, ext, text, page_id=page_id)
        async with AsyncSessionLocal() as db:
            await svc.save_outbound_channel_message(db, redis, conv.channel, ext, text)


async def _note_thread(conv_id, text: str) -> None:
    from app.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            db.add(Intercept(conversation_id=conv_id, action=InterceptAction.flag, note=text[:500]))
            await db.commit()
    except Exception:
        pass


async def answer_fact(redis, conv, ext: str, text: str, media) -> str:
    """Neema's one-sentence answer to a plain price/stock question, or ''."""
    from app.agent.runtime import run_turn, build_llm
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        reply = await run_turn(db, redis, wa_id=ext, user_text=text or "",
                               llm=build_llm(model=settings.tier2_model, purpose="unclaimed"),
                               media=media, channel=conv.channel,
                               external_id=(ext if conv.channel != "whatsapp" else None),
                               extra_note=NOTE)
    reply = (reply or "").strip()
    if not reply or SKIP in reply.upper().split() or reply.upper().strip(".!") == SKIP:
        return ""
    return reply


async def sweep_unclaimed(redis=None, *, minutes: int | None = None, limit: int = 20) -> dict:
    """Ring the team for every unclaimed chat past the threshold; answer the
    plain price/stock ones. Returns {'rung': n, 'answered': n}. Best-effort."""
    from app.database import AsyncSessionLocal
    from app.services.reply_sweeper import _answerable_turn, _page_id_for
    mins = int(minutes if minutes is not None else (settings.unclaimed_alert_minutes or 0))
    out = {"rung": 0, "answered": 0}
    if mins <= 0:
        return out
    try:
        async with AsyncSessionLocal() as db:
            rows = await _candidates(db, mins, limit)
    except Exception:
        _log.warning("unclaimed sweep: query failed", exc_info=True)
        return out
    for msg, conv in rows:
        ext = (conv.wa_id or msg.wa_id or msg.external_id) if conv.channel == "whatsapp" else msg.external_id
        if not ext or str(ext).startswith("web_"):
            continue
        try:
            if redis is not None and not await redis.set(_handled_key(msg.id), "1", nx=True,
                                                         ex=HANDLED_TTL_S):
                continue
        except Exception:
            pass
        await _ring(redis, conv, ext, msg.text, mins)
        out["rung"] += 1
        if not settings.unclaimed_answer:
            continue
        text, media = _answerable_turn(msg.text, msg.media_type, msg.media_url,
                                       getattr(msg, "raw_meta", None))
        if text is None and media is None:
            continue
        try:
            reply = await answer_fact(redis, conv, ext, text or "", media)
        except Exception as exc:
            _log.warning("unclaimed answer failed for %s/%s: %s", conv.channel, ext, exc)
            reply = ""
        if not reply:
            await _note_thread(conv.id, _THREAD_NOTE_SKIP.format(mins=mins))
            continue
        try:
            from app.agent.voice import looks_swahili
            page_id = None
            if conv.channel != "whatsapp":
                async with AsyncSessionLocal() as db2:
                    page_id = await _page_id_for(db2, conv.channel, ext)
            await _send(redis, conv, ext, reply, page_id)
            await _send(redis, conv, ext, FOLLOW["sw" if looks_swahili(text or "") else "en"], page_id)
            await _note_thread(conv.id, _THREAD_NOTE.format(mins=mins))
            out["answered"] += 1
        except Exception as exc:
            _log.warning("unclaimed send failed for %s/%s: %s", conv.channel, ext, exc)
    return out
