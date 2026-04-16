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
import logging as _logging

router = APIRouter()
_redis_log = _logging.getLogger("neema.redis")


async def _broadcast(redis, conv_id: str, payload: dict) -> None:
    """Publish a WebSocket event to all clients watching this conversation.
    Non-fatal — a read-only replica or transient Redis failure must never
    crash a request whose DB work already committed."""
    try:
        await redis.publish(f"ws:channel:{conv_id}", json.dumps(payload))
    except Exception as exc:
        _redis_log.warning(
            "Redis publish failed (channel=%s): %s — "
            "check REDIS_URL points to the primary node, not a read replica.",
            conv_id, exc,
        )


async def _redis_delete(redis, key: str) -> None:
    """Delete a Redis key. Non-fatal — cache invalidation failures are logged,
    not propagated."""
    try:
        await redis.delete(key)
    except Exception as exc:
        _redis_log.warning(
            "Redis delete failed (key=%s): %s — "
            "check REDIS_URL points to the primary node, not a read replica.",
            key, exc,
        )


async def _redis_publish(redis, channel: str, payload: dict) -> None:
    """Publish directly to a channel (no ws:channel: prefix added). Non-fatal."""
    try:
        await redis.publish(channel, json.dumps(payload))
    except Exception as exc:
        _redis_log.warning(
            "Redis publish failed (channel=%s): %s — "
            "check REDIS_URL points to the primary node, not a read replica.",
            channel, exc,
        )


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
    For audio replies (is_audio_reply=True), also saves the outbound audio message
    to DB and broadcasts it so agents see the voice note + text companion live.
    """
    result = await svc.outbound_gate(db, request.app.state.redis, body)

    # ── Audio reply: persist outbound audio message + broadcast ───────────────
    if body.is_audio_reply and body.audio_url and result.get("action") == "send":
        from sqlalchemy import select
        from app.models.conversation import Conversation
        from app.models.message import Message, MsgDirection, MsgSender
        from datetime import datetime, timezone

        db_result = await db.execute(
            select(Conversation).where(Conversation.wa_id == body.wa_id)
        )
        conv = db_result.scalar_one_or_none()
        if conv:
            companion_text = body.ai_reply or ""
            audio_msg = Message(
                wa_id=body.wa_id,
                conversation_id=conv.id,
                direction=MsgDirection.outbound,
                sender=MsgSender.ai,
                # text = readable AI reply shown below the audio player
                text=companion_text,
                media_type="audio",
                media_url=body.audio_url,
                # media_caption = cart summary shown in highlighted box (if any)
                media_caption=body.cart_text or None,
            )
            db.add(audio_msg)
            conv.last_message_at = datetime.now(timezone.utc)
            conv.last_message_preview = (
                f"🔊 {companion_text[:80]}" if companion_text else "🔊 Voice reply"
            )
            await db.commit()
            await db.refresh(audio_msg)

            redis = request.app.state.redis
            if redis:
                await _broadcast(redis, str(conv.id), {
                    "type":           "new_message",
                    "conversationId": str(conv.id),
                    "sender":         "ai",
                    "text":           companion_text,
                    "mediaType":      "audio",
                    "mediaUrl":       body.audio_url,
                    "mediaCaption":   body.cart_text or None,
                    "transcription":  body.transcription or None,
                })

    return result


# ── TTS audio save ────────────────────────────────────────
@router.post("/media/save-tts", dependencies=[Depends(verify_n8n_secret)])
async def save_tts_audio(request: Request):
    """
    Receives a raw MP3 binary from n8n (OpenAI TTS output), saves it to disk,
    and returns a stable public URL used by the audio reply workflow branch.
    n8n sends the filename via the X-Filename header.
    """
    import uuid, os
    from app.routers.media import MEDIA_DIR

    filename_header = request.headers.get("x-filename", "")
    filename = filename_header if (filename_header and filename_header.endswith(".mp3")) \
        else f"tts_{uuid.uuid4().hex}.mp3"

    filepath = os.path.join(MEDIA_DIR, filename)
    body_bytes = await request.body()
    if not body_bytes:
        raise HTTPException(status_code=400, detail="Empty body — no audio data received")

    with open(filepath, "wb") as f:
        f.write(body_bytes)

    base = str(request.base_url).rstrip("/")
    return {
        "ok":        True,
        "filename":  filename,
        "audio_url": f"{base}/api/admin/media/{filename}",
    }


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
    channel = f"ws:channel:agents:{agent_id}" if agent_id else "ws:channel:agents:all"
    await _redis_publish(redis, channel, {
        "event":  "notification",
        "type":   body.get("type"),
        "title":  body.get("title"),
        "body":   body.get("body"),
        "wa_id":  body.get("wa_id"),
        "ts":     body.get("ts"),
        "data":   body,
    })
    return {"ok": True}

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

        # Clear cached context so the next agent pick-up gets a fresh state.
        # Non-fatal: if Redis is unavailable the cache will simply expire
        # on its own (TTL=1h set in get_context).
        await _redis_delete(redis, f"context:{wa_id}")

    await db.commit()

    # ── 3. Broadcast to agents ────────────────────────────────────────────────
    # Always broadcast regardless of prior intercept state —
    # the agent needs to see the notification even if already assigned.
    notification_body = (
        f"📎 {reason}"
        if already_human
        else f"📎 {reason} — conversation is ready for pickup"
    )

    await _redis_publish(redis, "ws:channel:agents:all", {
        "event":          "notification",
        "type":           "media_escalation",
        "title":          "📎 Media Request",
        "body":           notification_body,
        "wa_id":          wa_id,
        "conv_id":        str(conv.id),
        "already_human":  already_human,
    })

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