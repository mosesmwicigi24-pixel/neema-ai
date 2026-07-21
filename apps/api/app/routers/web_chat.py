"""Website storefront → Neema. One brain everywhere.

The storefront server POSTs a visitor's message here (server-to-server, authed by
a shared X-Storefront-Key) and gets Neema's reply back synchronously — the same
agent, catalogue, pricing and memory the WhatsApp/Messenger channels use. Unlike
those async webhook channels, web chat is request→reply: we persist the turn,
run the agent, and return the text in the HTTP response.

Continuity: the storefront sends a stable `session_id`; we derive a namespaced
wa_id (`web_<hash>`) so each visitor's conversation threads across messages and
shows up in the dashboard inbox (where an agent can take over). If the visitor
gives a name/phone, we capture it on their profile.
"""
import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import get_db
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message, MsgDirection, MsgSender
from app.models.user import User

router = APIRouter()
_log = logging.getLogger("neema.web")


def verify_storefront_key(x_storefront_key: str = Header(...)):
    """Every storefront → API call must carry the shared secret. Constant-time
    compare; 503 if the key isn't configured (endpoint disabled until it is)."""
    expected = settings.storefront_key
    if not expected:
        raise HTTPException(status_code=503, detail="Web chat is not configured (STOREFRONT_KEY unset).")
    if not hmac.compare_digest(x_storefront_key or "", expected):
        raise HTTPException(status_code=401, detail="Invalid storefront key.")


class WebChatIn(BaseModel):
    session_id: str            # stable per-visitor id from the storefront
    message: str
    name: str | None = None    # optional — enrich the profile / inbox display
    phone: str | None = None   # optional — captured for follow-up / linking


def _web_wa_id(session_id: str) -> str:
    """Namespaced conversation key for a web visitor. Deterministic (same session
    → same key), bounded to fit wa_id VARCHAR(30), and non-numeric so it never
    collides with a phone (WhatsApp) or Meta PSID."""
    return "web_" + hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:20]


@router.post("/chat", dependencies=[Depends(verify_storefront_key)])
async def web_chat(body: WebChatIn, request: Request, db: AsyncSession = Depends(get_db)):
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")
    if len(text) > 4000:
        text = text[:4000]
    sid = (body.session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id is required")

    wa_id = _web_wa_id(sid)
    redis = getattr(request.app.state, "redis", None)

    # Ensure a profile (for name + cross-conversation memory).
    u = (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()
    if u is None:
        u = User(wa_id=wa_id, phone=(body.phone or None), name=(body.name or None))
        db.add(u)
        await db.flush()
    else:
        if body.name and not u.name:
            u.name = body.name
        if body.phone and not u.phone:
            u.phone = body.phone

    # Ensure a conversation + persist the inbound turn (so history + the inbox see it).
    conv = (await db.execute(
        select(Conversation).where(Conversation.wa_id == wa_id)
    )).scalar_one_or_none()
    if conv is None:
        conv = Conversation(wa_id=wa_id)
        db.add(conv)
        await db.flush()
    db.add(Message(wa_id=wa_id, conversation_id=conv.id,
                   direction=MsgDirection.inbound, sender=MsgSender.user, text=text))
    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = text[:100]
    # Only an explicit human takeover (or pause) holds the AI back; anything else
    # (incl. a just-created conversation whose default isn't flushed yet) is AI-active.
    intercepted = conv.intercept_mode in (InterceptMode.human, InterceptMode.paused)
    await db.commit()

    try:
        from app.services.redis import broadcast
        await broadcast(redis, str(conv.id), {
            "type": "message", "conversationId": str(conv.id),
            "waId": wa_id, "direction": "inbound", "text": text,
        })
    except Exception:
        pass

    # If a human agent has taken over (or paused) this chat, don't let the AI talk
    # over them — hold the visitor while the operator replies in the dashboard.
    if intercepted:
        return {"reply": "Thanks — one of our team will reply here shortly.",
                "session_id": sid, "handled_by": "human"}

    from app.agent.runtime import run_turn, build_llm, route_model
    try:
        reply = await run_turn(db, redis, wa_id, text, build_llm(model=route_model(text)))
    except Exception:
        _log.exception("web chat turn failed for %s", wa_id)
        reply = "Sorry — I hit a snag on my end. Could you try that again in a moment?"

    # Persist + broadcast the reply (same path the WhatsApp agent uses).
    try:
        from app.services.n8n_bridge import save_outbound_message
        await save_outbound_message(db, redis, wa_id, reply)
    except Exception:
        _log.warning("web chat: saving outbound failed for %s", wa_id)

    return {"reply": reply, "session_id": sid, "handled_by": "ai"}
