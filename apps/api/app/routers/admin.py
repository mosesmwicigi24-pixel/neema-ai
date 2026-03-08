from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.database import get_db
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message
from app.models.agent import Agent
from app.models.intercept import Intercept, InterceptAction
from app.schemas.conversation import ConversationListItem, InterceptRequest
from app.services.conversation import (
    intercept_conversation, release_conversation,
    transfer_conversation, send_agent_reply, approve_draft
)
import jwt
from app.core.security import decode_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

router = APIRouter()
bearer = HTTPBearer()


async def get_current_agent(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(Agent).where(Agent.id == payload["sub"]))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


# ── Conversations ─────────────────────────────────────────

@router.get("/conversations")
async def list_conversations(
    mode: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    q = select(Conversation).order_by(Conversation.last_message_at.desc().nullslast())
    if mode:
        q = q.where(Conversation.intercept_mode == mode)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/conversations/{conv_id}/messages")
async def get_thread(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    return result.scalars().all()


@router.post("/conversations/{conv_id}/intercept")
async def intercept(conv_id: str, db: AsyncSession = Depends(get_db),
                    agent: Agent = Depends(get_current_agent)):
    return await intercept_conversation(db, conv_id, agent)


@router.post("/conversations/{conv_id}/reply")
async def reply(conv_id: str, body: dict, db: AsyncSession = Depends(get_db),
                agent: Agent = Depends(get_current_agent)):
    return await send_agent_reply(db, conv_id, agent, body["text"])


@router.post("/conversations/{conv_id}/approve-draft")
async def approve(conv_id: str, body: dict = {}, db: AsyncSession = Depends(get_db),
                  agent: Agent = Depends(get_current_agent)):
    return await approve_draft(db, conv_id, agent, body.get("text"))


@router.post("/conversations/{conv_id}/release")
async def release(conv_id: str, db: AsyncSession = Depends(get_db),
                  agent: Agent = Depends(get_current_agent)):
    return await release_conversation(db, conv_id, agent)


@router.post("/conversations/{conv_id}/transfer")
async def transfer(conv_id: str, body: dict, db: AsyncSession = Depends(get_db),
                   agent: Agent = Depends(get_current_agent)):
    return await transfer_conversation(db, conv_id, agent, body["agentId"])


# ── Agents ────────────────────────────────────────────────

@router.get("/agents")
async def list_agents(db: AsyncSession = Depends(get_db),
                      agent: Agent = Depends(get_current_agent)):
    result = await db.execute(select(Agent).order_by(Agent.name))
    return result.scalars().all()


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, body: dict,
                       db: AsyncSession = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    allowed = {"name", "is_available", "role", "avatar_url"}
    updates = {k: v for k, v in body.items() if k in allowed}
    await db.execute(update(Agent).where(Agent.id == agent_id).values(**updates))
    return {"ok": True}