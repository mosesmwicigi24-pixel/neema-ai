from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message, MsgDirection, MsgSender
from app.models.intercept import Intercept, InterceptAction
from app.models.agent import Agent
from app.services.n8n_bridge import _send_waba, _broadcast


async def intercept_conversation(
    db: AsyncSession,
    conv_id: str,
    agent: Agent,
    redis=None,
) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # ── Ownership lock ────────────────────────────────────────────────────────
    if (
        conv.intercept_mode == InterceptMode.human
        and conv.assigned_agent_id is not None
        and conv.assigned_agent_id != agent.id
    ):
        owner = await db.get(Agent, conv.assigned_agent_id)
        owner_name = owner.name if owner else "another agent"
        from fastapi import HTTPException
        raise HTTPException(
            status_code=409,
            detail=f"Already handled by {owner_name}. They must release or transfer it first.",
        )
    # ─────────────────────────────────────────────────────────────────────────

    conv.intercept_mode = InterceptMode.human
    conv.assigned_agent_id = agent.id
    conv.intercept_since = datetime.now(timezone.utc)

    log = Intercept(
        conversation_id=conv.id,
        agent_id=agent.id,
        action=InterceptAction.intercept,
    )
    db.add(log)
    await db.commit()

    # Notify customer that a human agent has joined
    wa_id = conv.wa_id.lstrip("+")
    notification = (
        f"👋 Hi! You're now chatting with *{agent.name}*, "
        f"one of our team members. I'll be assisting you from here. "
        f"Feel free to continue — I'm here to help! 😊"
    )
    try:
        await _send_waba(wa_id, notification)
        msg = Message(
            wa_id=conv.wa_id,
            conversation_id=conv.id,
            direction=MsgDirection.outbound,
            sender=MsgSender.human_agent,
            text=notification,
            agent_id=agent.id,
        )
        db.add(msg)
        conv.last_message_at = datetime.now(timezone.utc)
        conv.last_message_preview = notification[:100]
        await db.commit()

        if redis:
            await _broadcast(redis, str(conv.id), {
                "type": "new_message",
                "conversationId": str(conv.id),
                "sender": "human_agent",
                "text": notification,
            })
    except Exception:
        pass  # don't block the intercept if WABA fails

    return {"ok": True, "mode": "human"}


async def release_conversation(
    db: AsyncSession,
    conv_id: str,
    agent: Agent,
    redis=None,
) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.intercept_mode = InterceptMode.ai
    conv.assigned_agent_id = None
    conv.intercept_since = None

    log = Intercept(
        conversation_id=conv.id,
        agent_id=agent.id,
        action=InterceptAction.release,
    )
    db.add(log)
    await db.commit()

    # Notify customer they're back with the AI assistant
    wa_id = conv.wa_id.lstrip("+")
    notification = (
        f"🤖 You're now back with *Neema*, your AI assistant. "
        f"How can I help you today?"
    )
    try:
        await _send_waba(wa_id, notification)
        msg = Message(
            wa_id=conv.wa_id,
            conversation_id=conv.id,
            direction=MsgDirection.outbound,
            sender=MsgSender.ai,
            text=notification,
        )
        db.add(msg)
        conv.last_message_at = datetime.now(timezone.utc)
        conv.last_message_preview = notification[:100]
        await db.commit()

        if redis:
            await _broadcast(redis, str(conv.id), {
                "type": "new_message",
                "conversationId": str(conv.id),
                "sender": "ai",
                "text": notification,
            })
    except Exception:
        pass  # don't block the release if WABA fails

    return {"ok": True, "mode": "ai"}


async def transfer_conversation(
    db: AsyncSession,
    conv_id: str,
    agent: Agent,
    target_agent_id: str,
    redis=None,
) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")

    target_result = await db.execute(
        select(Agent).where(Agent.id == target_agent_id)
    )
    target_agent = target_result.scalar_one_or_none()

    conv.assigned_agent_id = target_agent_id
    log = Intercept(
        conversation_id=conv.id,
        agent_id=agent.id,
        action=InterceptAction.transfer,
    )
    db.add(log)
    await db.commit()

    if target_agent:
        wa_id = conv.wa_id.lstrip("+")
        notification = (
            f"🔄 You've been transferred to *{target_agent.name}*, "
            f"who will continue assisting you. "
            f"One moment please! 😊"
        )
        try:
            await _send_waba(wa_id, notification)
            msg = Message(
                wa_id=conv.wa_id,
                conversation_id=conv.id,
                direction=MsgDirection.outbound,
                sender=MsgSender.human_agent,
                text=notification,
                agent_id=agent.id,
            )
            db.add(msg)
            conv.last_message_at = datetime.now(timezone.utc)
            conv.last_message_preview = notification[:100]
            await db.commit()

            if redis:
                await _broadcast(redis, str(conv.id), {
                    "type": "new_message",
                    "conversationId": str(conv.id),
                    "sender": "human_agent",
                    "text": notification,
                })
        except Exception:
            pass

    return {"ok": True, "transferred_to": target_agent_id}


async def send_agent_reply(
    db: AsyncSession,
    conv_id: str,
    agent: Agent,
    text: str,
    redis=None,
) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # ── Ownership lock ────────────────────────────────────────────────────────
    if (
        conv.intercept_mode == InterceptMode.human
        and conv.assigned_agent_id is not None
        and conv.assigned_agent_id != agent.id
    ):
        owner = await db.get(Agent, conv.assigned_agent_id)
        owner_name = owner.name if owner else "another agent"
        from fastapi import HTTPException
        raise HTTPException(
            status_code=409,
            detail=f"Conversation is handled by {owner_name}.",
        )
    # ─────────────────────────────────────────────────────────────────────────

    wa_id = conv.wa_id.lstrip("+")
    await _send_waba(wa_id, text)

    msg = Message(
        wa_id=conv.wa_id,
        conversation_id=conv.id,
        direction=MsgDirection.outbound,
        sender=MsgSender.human_agent,
        text=text,
        agent_id=agent.id,
    )
    db.add(msg)

    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = text[:100]

    await db.commit()
    await db.refresh(msg)

    if redis:
        await _broadcast(redis, str(conv.id), {
            "type": "new_message",
            "conversationId": str(conv.id),
            "sender": "human_agent",
            "text": text,
        })

    return {
        "id": str(msg.id),
        "direction": "outbound",
        "sender": "human_agent",
        "text": text,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


async def approve_draft(
    db: AsyncSession,
    conv_id: str,
    agent: Agent,
    text: str | None = None,
    redis=None,
) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not text:
        dr = await db.execute(
            select(Intercept)
            .where(Intercept.conversation_id == conv_id)
            .where(Intercept.ai_reply_held.isnot(None))
            .order_by(Intercept.created_at.desc())
            .limit(1)
        )
        intercept = dr.scalar_one_or_none()
        text = intercept.ai_reply_held if intercept else ""

    if not text:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="No draft text found to approve")

    wa_id = conv.wa_id.lstrip("+")
    await _send_waba(wa_id, text)

    msg = Message(
        wa_id=conv.wa_id,
        conversation_id=conv.id,
        direction=MsgDirection.outbound,
        sender=MsgSender.ai,
        text=text,
        agent_id=agent.id,
    )
    db.add(msg)

    log = Intercept(
        conversation_id=conv.id,
        agent_id=agent.id,
        action=InterceptAction.approve_draft,
        agent_reply_sent=text,
    )
    db.add(log)

    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = text[:100]

    await db.commit()
    await db.refresh(msg)

    if redis:
        await _broadcast(redis, str(conv.id), {
            "type": "new_message",
            "conversationId": str(conv.id),
            "sender": "ai",
            "text": text,
        })

    return {
        "id": str(msg.id),
        "direction": "outbound",
        "sender": "ai",
        "text": text,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


# ── Media ──────────────────────────────────────────────────────────────────────

async def send_agent_media(
    db: AsyncSession,
    conv_id: str,
    agent: Agent,
    media_url: str,
    media_type: str,       # "image" | "document" | "video" | "audio"
    caption: str | None,
    filename: str | None,
    redis=None,
) -> dict:
    """Send an image / document / video / audio to the customer via WABA."""
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")

    wa_id = conv.wa_id.lstrip("+")
    await _send_waba_media(wa_id, media_type, media_url, caption, filename)

    preview = caption or filename or f"[{media_type}]"
    msg = Message(
        wa_id=conv.wa_id,
        conversation_id=conv.id,
        direction=MsgDirection.outbound,
        sender=MsgSender.human_agent,
        text=preview,
        media_type=media_type,
        media_url=media_url,
        agent_id=agent.id,
    )
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = preview[:100]
    await db.commit()
    await db.refresh(msg)

    if redis:
        await _broadcast(redis, str(conv.id), {
            "type": "new_message",
            "conversationId": str(conv.id),
            "sender": "human_agent",
            "text": preview,
            "mediaType": media_type,
            "mediaUrl": media_url,
        })

    return {
        "id": str(msg.id),
        "direction": "outbound",
        "sender": "human_agent",
        "media_type": media_type,
        "media_url": media_url,
        "text": caption,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


async def _send_waba_media(
    wa_id: str,
    media_type: str,
    media_url: str,
    caption: str | None,
    filename: str | None,
) -> None:
    """Send a media message via the WhatsApp Business API using a public link URL."""
    import httpx, logging
    from app.core.config import settings

    url = (
        f"https://graph.facebook.com/{settings.waba_api_version}"
        f"/{settings.waba_phone_number_id}/messages"
    )

    media_obj: dict = {"link": media_url}
    if caption:
        media_obj["caption"] = caption
    if filename and media_type == "document":
        media_obj["filename"] = filename

    payload = {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": media_type,
        media_type: media_obj,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.waba_token}"},
            json=payload,
            timeout=30.0,
        )
        if not resp.is_success:
            logging.error(f"WABA media error {resp.status_code}: {resp.text}")
            resp.raise_for_status()