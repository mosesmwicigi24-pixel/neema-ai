from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
import json
import httpx

from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message, MsgDirection, MsgSender
from app.models.user import User
from app.models.order_event import OrderEvent
from app.models.customer_history import CustomerHistory
from app.models.session import Session
from app.models.intercept import Intercept, InterceptAction
from app.core.config import settings
from app.schemas.n8n import OutboundDto


# ── Intercept Gate ────────────────────────────────────────

async def outbound_gate(db: AsyncSession, redis, body: OutboundDto) -> dict:
    """Core logic: AI mode sends immediately; human mode holds the reply."""
    # Get or create conversation record
    result = await db.execute(
        select(Conversation).where(Conversation.wa_id == body.wa_id)
    )
    conv = result.scalar_one_or_none()

    if not conv:
        conv = Conversation(wa_id=body.wa_id)
        db.add(conv)
        await db.flush()

    if conv.intercept_mode == InterceptMode.human:
        # Hold — store draft, push WebSocket event to assigned agent
        intercept = Intercept(
            conversation_id=conv.id,
            agent_id=conv.assigned_agent_id,
            action=InterceptAction.intercept,
            ai_reply_held=body.ai_reply,
        )
        db.add(intercept)
        await _broadcast(redis, str(conv.id), {
            "type": "ai_draft_ready",
            "conversationId": str(conv.id),
            "waId": body.wa_id,
            "draft": body.ai_reply,
        })
        return {"action": "hold"}

    # AI mode — send directly via WABA
    await _send_waba(body.wa_id, body.ai_reply)

    # Store as outbound message
    msg = Message(
        wa_id=body.wa_id,
        conversation_id=conv.id,
        direction=MsgDirection.outbound,
        sender=MsgSender.ai,
        text=body.ai_reply,
    )
    db.add(msg)
    await _broadcast(redis, str(conv.id), {
        "type": "new_message",
        "conversationId": str(conv.id),
        "sender": "ai",
        "text": body.ai_reply,
    })
    return {"action": "send"}


# ── WABA Sender ───────────────────────────────────────────

async def _send_waba(wa_id: str, text: str) -> None:
    url = (f"https://graph.facebook.com/{settings.waba_api_version}"
           f"/{settings.waba_phone_number_id}/messages")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.waba_token}"},
            json={"messaging_product": "whatsapp", "to": wa_id,
                  "type": "text", "text": {"body": text}},
        )
        resp.raise_for_status()


# ── Redis Broadcast ───────────────────────────────────────

async def _broadcast(redis, channel: str, payload: dict) -> None:
    await redis.publish(f"ws:channel:{channel}", json.dumps(payload))


# ── Context ───────────────────────────────────────────────

async def get_context(db: AsyncSession, redis, wa_id: str) -> dict:
    cache_key = f"context:{wa_id}"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()

    ctx = {
        "wa_id": wa_id,
        "state": user.state if user else {"active": "active", "cart": {"items": [], "subtotal": 0}},
        "lastText": user.last_text if user else "",
        "lastDirection": user.last_direction if user else "inbound",
        "lastMessageAt": user.last_message_at.isoformat() if user and user.last_message_at else None,
    }
    await redis.setex(cache_key, 3600, json.dumps(ctx))
    return ctx


# ── Upsert User ───────────────────────────────────────────

async def upsert_user(db: AsyncSession, body) -> dict:
    stmt = pg_insert(User).values(
        wa_id=body.wa_id,
        phone=body.phone or body.wa_id,
        last_text=body.last_text or "",
        last_direction=body.last_direction or "inbound",
        state=body.state or {"active": "active", "cart": {"items": [], "subtotal": 0}},
    ).on_conflict_do_update(
        index_elements=["wa_id"],
        set_={
            "last_text": body.last_text or "",
            "last_direction": body.last_direction or "inbound",
            "state": body.state or {},
        },
    ).returning(User)
    result = await db.execute(stmt)
    user = result.scalar_one()
    return {"id": str(user.id), "wa_id": user.wa_id}