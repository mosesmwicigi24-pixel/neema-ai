"""Tier 2 agent transport endpoint.

n8n (the thin WhatsApp relay) forwards every inbound message here. If the sender
is enabled for Tier 2, we run the agent loop, send the reply, persist it, and
report routed=true. Otherwise routed=false and n8n falls through to the Tier 1
flow — so the two tiers coexist safely behind a per-wa_id flag.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.n8n_bridge import verify_n8n_secret
from app.services import n8n_bridge as svc
from app.agent import runtime

router = APIRouter()
_log = logging.getLogger("neema.agent")


class AgentTurnDto(BaseModel):
    wa_id: str
    text: str = ""


@router.post("/turn", dependencies=[Depends(verify_n8n_secret)])
async def agent_turn(body: AgentTurnDto, request: Request, db: AsyncSession = Depends(get_db)):
    wa_id = svc._normalize_wa_id(body.wa_id)
    if not runtime.is_tier2(wa_id):
        return {"routed": False}

    redis = request.app.state.redis
    reply = await runtime.run_turn(db, redis, wa_id, body.text, runtime.build_llm())

    # Send + persist the reply (Tier 2 owns its own outbound, like Tier 1's gate).
    await svc._send_waba(wa_id, reply)
    await svc.save_outbound_message(db, redis, wa_id, reply)
    return {"routed": True, "reply": reply}
