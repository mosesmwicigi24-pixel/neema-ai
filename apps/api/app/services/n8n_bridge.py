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

# ── Upsert Message ────────────────────────────────────────

async def upsert_message(db: AsyncSession, body) -> dict:
    result = await db.execute(
        select(Conversation).where(Conversation.wa_id == body.wa_id)
    )
    conv = result.scalar_one_or_none()

    if not conv:
        conv = Conversation(wa_id=body.wa_id)
        db.add(conv)
        await db.flush()

    sender = MsgSender.customer if body.direction == "inbound" else MsgSender.ai
    direction = MsgDirection.inbound if body.direction == "inbound" else MsgDirection.outbound

    msg = Message(
        conversation_id=conv.id,
        wa_id=body.wa_id,
        direction=direction,
        sender=sender,
        text=body.text,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    return {
        "ok": True,
        "conversation_id": str(conv.id),
        "message_id": str(msg.id),
    }


# ── Patch Message ─────────────────────────────────────────

async def patch_message(db: AsyncSession, docid: str, body) -> dict:
    result = await db.execute(
        select(Message).where(Message.id == docid)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        return {"ok": False, "error": f"Message {docid} not found"}
    if body.inbound_text is not None:
        msg.text = body.inbound_text
    if body.outbound_text is not None:
        msg.text = body.outbound_text
    if body.direction is not None:
        msg.direction = body.direction
    await db.commit()
    return {"ok": True, "message_id": docid}


# ── Touch Session ─────────────────────────────────────────

async def touch_session(db: AsyncSession, body) -> dict:
    from app.models.session import Session as SessionModel
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from datetime import datetime

    session_id = body.session_id or f"{body.wa_id}_{int(datetime.utcnow().timestamp())}"

    stmt = pg_insert(SessionModel).values(
        id=session_id,
        wa_id=body.wa_id,
        turns=body.turns,
        start_ts=body.start_ts,
        last_ts=body.last_ts,
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "turns": body.turns,
            "last_ts": body.last_ts,
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True, "session_id": session_id}



# ── Get Messages ──────────────────────────────────────────

async def get_messages(db: AsyncSession, wa_id: str) -> list:
    result = await db.execute(
        select(Message)
        .where(Message.wa_id == wa_id)
        .order_by(Message.created_at.asc())
        .limit(50)
    )
    msgs = result.scalars().all()
    return [
        {
            "id": str(m.id),
            "wa_id": m.wa_id,
            "direction": m.direction,
            "sender": m.sender,
            "text": m.text,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]


# ── Save User Facts ───────────────────────────────────────

async def save_user_facts(db: AsyncSession, body) -> dict:
    result = await db.execute(select(User).where(User.wa_id == body.wa_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"ok": False, "error": "User not found"}
    # Map known fields onto user
    for field in ("name", "email", "phone", "location", "age"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(user, field, val)
    await db.commit()
    return {"ok": True}


# ── Upsert Order Event ────────────────────────────────────

async def upsert_order_event(db: AsyncSession, body) -> dict:
    from app.models.order_event import OrderEvent
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from datetime import datetime

    event_id = f"{body.wa_id}_{int(datetime.utcnow().timestamp() * 1000)}"

    stmt = pg_insert(OrderEvent).values(
        id=event_id,
        wa_id=body.wa_id,
        session_id=body.session_id,
        event_type=body.event_type,
        items=body.items,
        subtotal=body.subtotal,
        currency=body.currency,
        status=body.status,
        payment_status=body.payment_status,
        fulfillment_status=body.fulfillment_status,
        reply_text=body.reply_text,
        channel=body.channel,
        state=body.state,
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "status": body.status,
            "payment_status": body.payment_status,
            "fulfillment_status": body.fulfillment_status,
            "reply_text": body.reply_text,
            "state": body.state,
            "items": body.items,
            "subtotal": body.subtotal,
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True, "event_id": event_id}

# ── Upsert Customer History ───────────────────────────────

async def upsert_customer_history(db: AsyncSession, body) -> dict:
    from app.models.customer_history import CustomerHistory
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(CustomerHistory).values(
        wa_id=body.wa_id,
        last_status=body.last_status,
        has_open_order=body.has_open_order,
        last_event=body.last_event or {},
        last_chat={},
        last_order={},
        counts=body.counts or {},
    ).on_conflict_do_update(
        index_elements=["wa_id"],
        set_={
            "last_status": body.last_status,
            "has_open_order": body.has_open_order,
            "last_event": body.last_event or {},
            "counts": body.counts or {},
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True}