from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message, MsgDirection, MsgSender
from app.models.intercept import Intercept, InterceptAction
from app.models.agent import Agent
from app.services.n8n_bridge import _send_waba, _broadcast
import json


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
    return {"ok": True, "transferred_to": target_agent_id}


async def send_agent_reply(db: AsyncSession, conv_id: str, agent: Agent, text: str) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")
    await _send_waba(conv.wa_id, text)
    msg = Message(
        wa_id=conv.wa_id,
        conversation_id=conv.id,
        direction=MsgDirection.outbound,
        sender=MsgSender.human_agent,
        text=text,
        agent_id=agent.id,
    )
    db.add(msg)
    return {"ok": True}


async def approve_draft(db: AsyncSession, conv_id: str, agent: Agent, text: str | None = None) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Get the latest held draft if no text provided
    if not text:
        dr = await db.execute(
            select(Intercept)
            .where(Intercept.conversation_id == conv_id)
            .where(Intercept.ai_reply_held.isnot(None))
            .order_by(Intercept.created_at.desc())
        )
        intercept = dr.scalar_one_or_none()
        text = intercept.ai_reply_held if intercept else ""
    if text:
        await _send_waba(conv.wa_id, text)
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
    return {"ok": True}