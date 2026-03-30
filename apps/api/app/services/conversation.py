from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message, MsgDirection, MsgSender
from app.models.intercept import Intercept, InterceptAction
from app.models.agent import Agent
from app.services.n8n_bridge import _send_waba, _broadcast


async def intercept_conversation(db: AsyncSession, conv_id: str, agent: Agent) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.intercept_mode = InterceptMode.human
    conv.assigned_agent_id = agent.id
    conv.intercept_since = datetime.now(timezone.utc)
    log = Intercept(conversation_id=conv.id, agent_id=agent.id, action=InterceptAction.intercept)
    db.add(log)
    await db.commit()
    return {"ok": True, "mode": "human"}


async def release_conversation(db: AsyncSession, conv_id: str, agent: Agent) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.intercept_mode = InterceptMode.ai
    conv.assigned_agent_id = None
    conv.intercept_since = None
    log = Intercept(conversation_id=conv.id, agent_id=agent.id, action=InterceptAction.release)
    db.add(log)
    await db.commit()
    return {"ok": True, "mode": "ai"}


async def transfer_conversation(db: AsyncSession, conv_id: str, agent: Agent, target_agent_id: str) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.assigned_agent_id = target_agent_id
    log = Intercept(conversation_id=conv.id, agent_id=agent.id, action=InterceptAction.transfer)
    db.add(log)
    await db.commit()
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

    # Meta WABA requires number without leading + (e.g. 254700912916 not +254700912916)
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

    # Update conversation preview so list stays current
    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = text[:100]

    await db.commit()
    await db.refresh(msg)

    # Push live update to dashboard WebSocket
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

    # Fall back to the latest held draft if no text was passed in
    if not text:
        dr = await db.execute(
            select(Intercept)
            .where(Intercept.conversation_id == conv_id)
            .where(Intercept.ai_reply_held.isnot(None))
            .order_by(Intercept.created_at.desc())
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