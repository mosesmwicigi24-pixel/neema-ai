from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.core.config import settings
from app.services import n8n_bridge as svc
from app.schemas.n8n import (
    OutboundDto, SessionDto, MessageDto, UpsertMessagePatchDto,
    UserDto, OrderEventDto, CustomerHistoryDto, UserFactsDto,
    UsageDto, RouteDto,
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


# ── Profile bundle (one-call replacement for the n8n Customer-Profile assembly)
@router.get("/profile/{wa_id}", dependencies=[Depends(verify_n8n_secret)])
async def get_profile(wa_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    redis = request.app.state.redis
    profile = await svc.get_profile(db, redis, wa_id)

    # Tier 2 routing: for enabled numbers, fire the agent in the background and
    # tell n8n NOT to run the Tier 1 AI (the agent sends its own reply). This is
    # the coexistence seam — everyone else falls through to Tier 1 untouched.
    from app.agent import runtime
    norm = svc._normalize_wa_id(wa_id)
    if runtime.is_tier2(norm):
        last = await svc.latest_inbound_message(db, norm)
        if last:
            text = (last.get("text") or "").strip()
            mtype = last.get("media_type")
            is_image = mtype == "image" and bool(last.get("media_url"))
            # Images go to the agent as a photo (vision). Other media (video,
            # document) can't be seen — pass the caption so it still responds.
            if not text and not is_image:
                text = (last.get("media_caption") or "").strip() or (
                    f"(the customer sent a {mtype})" if mtype else "")
            media = {"type": mtype, "url": last.get("media_url"),
                     "caption": last.get("media_caption")} if is_image else None
            if text or is_image:
                await runtime.schedule_reply(redis, norm, text, last["id"], media=media)
        profile["should_run_ai"] = False
        profile["route_reason"] = "tier2_agent"
    return profile


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
async def upsert_order_event(body: OrderEventDto, request: Request, db: AsyncSession = Depends(get_db)):
    return await svc.upsert_order_event(db, body, request.app.state.redis)


# ── Customer History ──────────────────────────────────────
@router.post("/customer-history", dependencies=[Depends(verify_n8n_secret)])
async def upsert_customer_history(body: CustomerHistoryDto, db: AsyncSession = Depends(get_db)):
    return await svc.upsert_customer_history(db, body)


# ── AI cost controls ──────────────────────────────────────
@router.post("/usage", dependencies=[Depends(verify_n8n_secret)])
async def log_usage(body: UsageDto, db: AsyncSession = Depends(get_db)):
    """n8n logs each LLM call's token usage here so spend is measurable."""
    return await svc.log_usage(db, body)


@router.post("/route", dependencies=[Depends(verify_n8n_secret)])
async def route_message(body: RouteDto, request: Request, db: AsyncSession = Depends(get_db)):
    """Server-side cost governor: dedupe retries, short-circuit trivial turns
    to a cheap path, and enforce a per-conversation cool-off — no tokens spent."""
    return await svc.route_message(db, request.app.state.redis, body)


# ── INTERCEPT GATE ────────────────────────────────────────
@router.post("/outbound", dependencies=[Depends(verify_n8n_secret)])
async def outbound_gate(body: OutboundDto, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Called by n8n after AI generates a reply.
    Returns {"action": "send"} or {"action": "hold"}.
    svc.outbound_gate handles everything: saving the message row (audio or text),
    sending to WhatsApp, and broadcasting the WS new_message event.
    """
    result = await svc.outbound_gate(db, request.app.state.redis, body)
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
async def get_catalog(request: Request, db: AsyncSession = Depends(get_db)):
    """Live catalogue for n8n price lookups — from the Bethany House hub (the
    single source of truth), falling back to Neema's local table if the hub is
    unreachable."""
    return await svc.catalog_items(db, request.app.state.redis)

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
    from datetime import timedelta
    msg_created_at = datetime.now(timezone.utc)
    if msg_text:
        inbound_msg = Message(
            wa_id=conv.wa_id,
            conversation_id=conv.id,
            direction=MsgDirection.inbound,
            sender=MsgSender.user,
            text=msg_text,
            created_at=msg_created_at,
        )
        db.add(inbound_msg)
        conv.last_message_at      = msg_created_at
        conv.last_message_preview = msg_text[:100]

    # ── 2. Intercept only if not already in human mode ────────────────────────
    already_human = conv.intercept_mode == InterceptMode.human

    if not already_human:
        # Switch to human mode, but leave assigned_agent_id as NULL so
        # any available agent can freely pick up the conversation.
        conv.intercept_mode    = InterceptMode.human
        conv.assigned_agent_id = None
        conv.intercept_since   = msg_created_at

        # Pin the Intercept row 1s after the inbound message so it always
        # sorts below it in the conversation thread.
        log = Intercept(
            conversation_id=conv.id,
            agent_id=None,           # system-triggered, not by a human agent
            action=InterceptAction.intercept,
            note=reason,
            created_at=msg_created_at + timedelta(seconds=1),
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

    # Broadcast the inbound message so agents viewing this conversation live
    # see what the customer wrote before the escalation pill appears.
    if msg_text:
        await _broadcast(redis, str(conv.id), {
            "type":           "new_message",
            "conversationId": str(conv.id),
            "waId":           wa_id,
            "direction":      "inbound",
            "sender":         "user",
            "text":           msg_text,
            "created_at":     msg_created_at.isoformat(),
        })

    # Broadcast intercept_changed so:
    # 1. The conversation list updates its mode indicator immediately.
    # 2. ConversationsView injects the escalation pill into the thread.
    # Always broadcast (even if already_human) so the escalation pill is
    # visible to agents who have this conversation open right now.
    await _broadcast(redis, str(conv.id), {
        "type":            "intercept_changed",
        "conversationId":  str(conv.id),
        "mode":            "human",
        "assignedAgentId": None,
        "eventKind":       "intercept",   # renders the escalation pill
        "eventReason":     reason,        # shown inside the pill
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