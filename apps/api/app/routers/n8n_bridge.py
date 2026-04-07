from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.core.config import settings
from app.services import n8n_bridge as svc
from app.schemas.n8n import (
    OutboundDto, SessionDto, MessageDto, UpsertMessagePatchDto,
    UserDto, OrderEventDto, CustomerHistoryDto, UserFactsDto
)
import json

router = APIRouter()


def verify_n8n_secret(x_n8n_secret: str = Header(...)):
    """All n8n → API calls must include this header."""
    if x_n8n_secret != settings.n8n_api_secret:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Context ───────────────────────────────────────────────
@router.get("/context/{wa_id}", dependencies=[Depends(verify_n8n_secret)])
async def get_context(wa_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await svc.get_context(db, request.app.state.redis, wa_id)


# ── Session ───────────────────────────────────────────────
@router.post("/session", dependencies=[Depends(verify_n8n_secret)])
async def touch_session(body: SessionDto, db: AsyncSession = Depends(get_db)):
    return await svc.touch_session(db, body)


# ── Messages ──────────────────────────────────────────────
@router.get("/messages/{wa_id}", dependencies=[Depends(verify_n8n_secret)])
async def get_messages(wa_id: str, db: AsyncSession = Depends(get_db)):
    return await svc.get_messages(db, wa_id)


@router.post("/message", dependencies=[Depends(verify_n8n_secret)])
async def upsert_message(
    body: MessageDto,
    request: Request,                    
    db: AsyncSession = Depends(get_db)
):
    return await svc.upsert_message(db, request.app.state.redis, body)  


@router.patch("/message/{docid}", dependencies=[Depends(verify_n8n_secret)])
async def patch_message(docid: str, body: UpsertMessagePatchDto, db: AsyncSession = Depends(get_db)):
    return await svc.patch_message(db, docid, body)


# ── Users ─────────────────────────────────────────────────
@router.post("/user", dependencies=[Depends(verify_n8n_secret)])
async def upsert_user(body: UserDto, db: AsyncSession = Depends(get_db)):
    return await svc.upsert_user(db, body)


@router.post("/user/facts", dependencies=[Depends(verify_n8n_secret)])
async def save_user_facts(body: UserFactsDto, db: AsyncSession = Depends(get_db)):
    return await svc.save_user_facts(db, body)

@router.get("/user/{wa_id}", dependencies=[Depends(verify_n8n_secret)])
async def get_user(wa_id: str, db: AsyncSession = Depends(get_db)):
    return await svc.get_user(db, wa_id)


# ── Orders ────────────────────────────────────────────────
@router.post("/order-event", dependencies=[Depends(verify_n8n_secret)])
async def upsert_order_event(body: OrderEventDto, db: AsyncSession = Depends(get_db)):
    return await svc.upsert_order_event(db, body)


# ── Customer History ──────────────────────────────────────
@router.post("/customer-history", dependencies=[Depends(verify_n8n_secret)])
async def upsert_customer_history(body: CustomerHistoryDto, db: AsyncSession = Depends(get_db)):
    return await svc.upsert_customer_history(db, body)


# ── INTERCEPT GATE ────────────────────────────────────────
@router.post("/outbound", dependencies=[Depends(verify_n8n_secret)])
async def outbound_gate(body: OutboundDto, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Called by n8n after AI generates a reply.
    Returns {"action": "send"} or {"action": "hold"}.
    """
    return await svc.outbound_gate(db, request.app.state.redis, body)


# ── Catalog (for n8n price lookups) ───────────────────────────────────────────
@router.get("/catalog", dependencies=[Depends(verify_n8n_secret)])
async def get_catalog(db: AsyncSession = Depends(get_db)):
    """
    Returns all in-stock catalog items so n8n can build a live price map
    instead of relying on the hardcoded fallback map.
    """
    from sqlalchemy import select
    from app.models.catalog import Catalog
    result = await db.execute(
        select(Catalog).where(Catalog.in_stock == True).order_by(Catalog.category, Catalog.name)
    )
    items = result.scalars().all()
    return [
        {
            "sku": str(i.sku),
            "name": str(i.name),
            "category": str(i.category or ""),
            "price": float(i.price),
            "unit": str(i.unit or ""),
            "description": str(i.description or ""),
            "aliases": i.aliases or [],
            "in_stock": i.in_stock,
        }
        for i in items
    ]

@router.post("/notify", dependencies=[Depends(verify_n8n_secret)])
async def post_notify(body: dict, request: Request):
    redis = request.app.state.redis
    agent_id = body.get("agent_id")
    # Broadcast to specific agent or all agents
    channel = f"agents:{agent_id}" if agent_id else "agents:all"
    await redis.publish(f"ws:channel:{channel}", json.dumps({
        "event":  "notification",
        "type":   body.get("type"),
        "title":  body.get("title"),
        "body":   body.get("body"),
        "wa_id":  body.get("wa_id"),
        "ts":     body.get("ts"),
        "data":   body,
    }))
    return {"ok": True}

# Add to app/routers/n8n_bridge.py router
@router.post("/media/download", dependencies=[Depends(verify_n8n_secret)])
async def n8n_download_media(body: dict, request: Request):
    media_id  = body.get("media_id")
    mime_type = body.get("mime_type", "application/octet-stream")

    if not media_id:
        return {"ok": False, "error": "media_id required"}

    from app.routers.media import MEDIA_DIR, _mime_to_ext
    import os, httpx

    ext      = _mime_to_ext(mime_type)
    filename = f"{media_id}{ext}"
    filepath = os.path.join(MEDIA_DIR, filename)

    if not os.path.exists(filepath):
        async with httpx.AsyncClient(timeout=30) as client:

            # Step 1 — get the current download URL from Graph API using media_id
            meta_resp = await client.get(
                f"https://graph.facebook.com/v19.0/{media_id}",
                headers={"Authorization": f"Bearer {settings.waba_token}"},
            )
            if not meta_resp.is_success:
                return {"ok": False, "error": f"Graph API metadata failed: {meta_resp.status_code}"}

            download_url = meta_resp.json().get("url")
            if not download_url:
                return {"ok": False, "error": "No URL in Graph API response"}

            # Step 2 — download the actual file using the fresh URL + token
            file_resp = await client.get(
                download_url,
                headers={"Authorization": f"Bearer {settings.waba_token}"},
                follow_redirects=True,
            )
            if not file_resp.is_success:
                return {"ok": False, "error": f"File download failed: {file_resp.status_code}"}

            with open(filepath, "wb") as f:
                f.write(file_resp.content)

    base = str(request.base_url).rstrip("/")
    return {
        "ok":         True,
        "filename":   filename,
        "media_id":   media_id,
        "stable_url": f"{base}/api/admin/media/{filename}",
        "mime_type":  mime_type,
    }

    # f"{base}/api/media/serve/{filename}",

# ── Media Escalation (system-triggered intercept by wa_id) ───────────────────
@router.post("/escalate", dependencies=[Depends(verify_n8n_secret)])
async def escalate_to_human(body: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Called by n8n when a media request is detected.

    1. Saves the customer's inbound message so agents can see what was written.
    2. If conversation is already in human mode → leave it as-is (keep current agent).
    3. If conversation is in AI mode → switch to human, unassigned so any agent can pick it up.
    4. Broadcasts a notification to all agents.
    No message is sent to the customer.
    """
    from sqlalchemy import select
    from app.models.conversation import Conversation, InterceptMode
    from app.models.message import Message, MsgDirection, MsgSender
    from app.models.intercept import Intercept, InterceptAction
    from datetime import datetime, timezone

    wa_id      = str(body.get("wa_id", "")).strip()
    msg_text   = str(body.get("msg_text", "")).strip()
    reason     = str(body.get("reason", "Customer requested images or files"))

    if not wa_id:
        raise HTTPException(status_code=400, detail="wa_id required")

    # ── Find conversation ─────────────────────────────────────────────────────
    result = await db.execute(
        select(Conversation).where(Conversation.wa_id == wa_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail=f"No conversation found for wa_id={wa_id}")

    redis = request.app.state.redis

    # ── 1. Save the customer's inbound message ────────────────────────────────
    # This ensures the agent can see exactly what the customer wrote
    # before the escalation happened.
    if msg_text:
        inbound_msg = Message(
            wa_id=conv.wa_id,
            conversation_id=conv.id,
            direction=MsgDirection.inbound,
            sender=MsgSender.user,
            text=msg_text,
        )
        db.add(inbound_msg)
        conv.last_message_at      = datetime.now(timezone.utc)
        conv.last_message_preview = msg_text[:100]

    # ── 2. Intercept only if not already in human mode ────────────────────────
    already_human = conv.intercept_mode == InterceptMode.human

    if not already_human:
        # Switch to human mode, but leave assigned_agent_id as NULL so
        # any available agent can freely pick up the conversation.
        conv.intercept_mode    = InterceptMode.human
        conv.assigned_agent_id = None
        conv.intercept_since   = datetime.now(timezone.utc)

        # Log the system-triggered intercept (no agent_id — system action)
        log = Intercept(
            conversation_id=conv.id,
            agent_id=None,           # system-triggered, not by a human agent
            action=InterceptAction.intercept,
        )
        db.add(log)

        # Clear cached context so the next agent pick-up gets a fresh state
        await redis.delete(f"context:{wa_id}")

    await db.commit()

    # ── 3. Broadcast to agents ────────────────────────────────────────────────
    # Always broadcast regardless of prior intercept state —
    # the agent needs to see the notification even if already assigned.
    notification_body = (
        f"📎 {reason}"
        if already_human
        else f"📎 {reason} — conversation is ready for pickup"
    )

    await redis.publish("ws:channel:agents:all", json.dumps({
        "event":          "notification",
        "type":           "media_escalation",
        "title":          "📎 Media Request",
        "body":           notification_body,
        "wa_id":          wa_id,
        "conv_id":        str(conv.id),
        "already_human":  already_human,
    }))

    # Also broadcast intercept_changed so the conversation list
    # updates its mode indicator in the agent UI immediately.
    if not already_human:
        await _broadcast(redis, str(conv.id), {
            "type":            "intercept_changed",
            "conversationId":  str(conv.id),
            "mode":            "human",
            "assignedAgentId": None,
        })

    return {
        "ok":            True,
        "wa_id":         wa_id,
        "conv_id":       str(conv.id),
        "mode":          "human",
        "already_human": already_human,
        "msg_saved":     bool(msg_text),
        "reason":        reason,
    }