from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
import json
import httpx
from datetime import datetime, timezone, timedelta

from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message, MsgDirection, MsgSender
from app.models.user import User
from app.models.order_event import OrderEvent
from app.models.customer_history import CustomerHistory
from app.models.session import Session
from app.models.intercept import Intercept, InterceptAction
from app.core.config import settings
from app.schemas.n8n import OutboundDto


# ── Shared timestamp helpers ──────────────────────────────

def _fmt_ts(dt: datetime | None) -> str:
    """UTC datetime → Firestore timestampValue string (no microseconds)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _fmt_ts_ms(dt: datetime | None) -> str:
    """UTC datetime → timestampValue/tsIso with millisecond precision (.000Z)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

def _fmt_precise(dt: datetime | None) -> str:
    """UTC datetime → createTime/updateTime string with microseconds."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

# Normalize wa_id by stripping leading + and whitespace to ensure consistent storage and lookup.
def _normalize_wa_id(wa_id: str) -> str:
    """Always store wa_id without a leading + to ensure consistent lookup."""
    return wa_id.lstrip("+").strip() if wa_id else wa_id


# ── Intercept Gate ────────────────────────────────────────

async def outbound_gate(db: AsyncSession, redis, body: OutboundDto) -> dict:
    body.wa_id = _normalize_wa_id(body.wa_id)

    result = await db.execute(
        select(Conversation).where(Conversation.wa_id == body.wa_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(wa_id=body.wa_id)
        db.add(conv)
        await db.flush()

    if conv.intercept_mode == InterceptMode.human:
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

    # ── Send to WhatsApp ──────────────────────────────────────────────────────
    if body.is_audio_reply and body.audio_url:
        # Send the TTS audio file via WABA
        await _send_waba_audio(body.wa_id, body.audio_url)
        # If there's a cart summary, send it as a follow-up text message
        if body.cart_text:
            await _send_waba(body.wa_id, body.cart_text)
    else:
        await _send_waba(body.wa_id, body.ai_reply)

    # ── Save outbound message to DB ───────────────────────────────────────────
    msg = Message(
        wa_id=body.wa_id,
        conversation_id=conv.id,
        direction=MsgDirection.outbound,
        sender=MsgSender.ai,
        text=body.ai_reply,            # the full text reply (shown as transcription in UI)
        media_type="audio" if (body.is_audio_reply and body.audio_url) else None,
        media_url=body.audio_url if body.is_audio_reply else None,
        media_caption=body.cart_text or None,   # cart summary shown below the player
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    broadcast_payload = {
        "type": "new_message",
        "conversationId": str(conv.id),
        "sender": "ai",
        "text": body.ai_reply,
    }
    if body.is_audio_reply and body.audio_url:
        broadcast_payload["mediaType"] = "audio"
        broadcast_payload["mediaUrl"] = body.audio_url
        broadcast_payload["mediaCaption"] = body.cart_text or None

    await _broadcast(redis, str(conv.id), broadcast_payload)
    return {"action": "send"}


async def _send_waba_audio(wa_id: str, audio_url: str) -> None:
    """Send a pre-generated TTS audio file to WhatsApp via a public link."""
    url = (f"https://graph.facebook.com/{settings.waba_api_version}"
           f"/{settings.waba_phone_number_id}/messages")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.waba_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": wa_id,
                "type": "audio",
                "audio": {"link": audio_url},
            },
            timeout=30.0,
        )
        if not resp.is_success:
            import logging
            logging.error(f"WABA audio error {resp.status_code}: {resp.text}")
            resp.raise_for_status()

# ── WABA Sender ───────────────────────────────────────────

async def _send_waba(wa_id: str, text: str) -> None:
    url = (f"https://graph.facebook.com/{settings.waba_api_version}"
           f"/{settings.waba_phone_number_id}/messages")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.waba_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": wa_id,
                "type": "text",
                "text": {"body": text},
            },
        )
        if not resp.is_success:
            import logging
            logging.error(f"WABA error {resp.status_code}: {resp.text}")
            resp.raise_for_status()


# ── Redis Broadcast ───────────────────────────────────────

async def _broadcast(redis, channel: str, payload: dict) -> None:
    await redis.publish(f"ws:channel:{channel}", json.dumps(payload))


# ── Context ───────────────────────────────────────────────

async def get_context(db: AsyncSession, redis, wa_id: str) -> dict:
    wa_id = _normalize_wa_id(wa_id)
    cache_key = f"context:{wa_id}"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()

    last_message_at: datetime | None = user.last_message_at if user else None
    last_message_ts: int | None = (
        int(last_message_at.astimezone(timezone.utc).timestamp() * 1000)
        if last_message_at else None
    )
    last_message_at_iso: str | None = (
        last_message_at.astimezone(timezone.utc).isoformat()
        if last_message_at else None
    )

    # ── Intercept / handover context ──────────────────────────────────────────
    conv_result = await db.execute(
        select(Conversation).where(Conversation.wa_id == wa_id)
    )
    conv = conv_result.scalar_one_or_none()

    recent_intercept = None
    intercept_mode   = "ai"

    if conv:
        intercept_mode = conv.intercept_mode.value if conv.intercept_mode else "ai"

        intercept_result = await db.execute(
            select(Intercept)
            .where(Intercept.conversation_id == conv.id)
            .order_by(Intercept.created_at.desc())
            .limit(1)
        )
        last_intercept = intercept_result.scalar_one_or_none()
        if last_intercept:
            recent_intercept = {
                "action":   last_intercept.action.value,
                "agent_id": str(last_intercept.agent_id) if last_intercept.agent_id else None,
                "at":       last_intercept.created_at.isoformat() if last_intercept.created_at else None,
            }

    ctx = {
        "wa_id":           wa_id,
        "state":           user.state if user else {"active": "active", "cart": {"items": [], "subtotal": 0}},
        "last_text":       user.last_text      if user else "",
        "last_direction":  user.last_direction if user else "inbound",
        "last_message_ts": last_message_ts,
        "last_message_at": last_message_at_iso,
        # ── Handover context — used by AI to acknowledge transitions ──────────
        "intercept_mode":   intercept_mode,
        "recent_intercept": recent_intercept,
    }

    await redis.setex(cache_key, 3600, json.dumps(ctx))
    return ctx

# ── Get User ──────────────────────────────────────────────

async def get_user(db: AsyncSession, wa_id: str) -> dict:
    wa_id = _normalize_wa_id(wa_id)
    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"found": False, "wa_id": wa_id}
    return {
        "found": True,
        "id": str(user.id),
        "wa_id": user.wa_id,
        "phone": user.phone,
        "name": user.name,
        "last_text": user.last_text,
        "last_direction": user.last_direction,
        "state": user.state,
    }


# ── Upsert User ───────────────────────────────────────────

async def upsert_user(db: AsyncSession, body) -> dict:
    stmt = pg_insert(User).values(
        wa_id=body.wa_id,
        phone=body.phone or body.wa_id,
        name=body.name or "",
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
# Stores media_type / media_url when present.
# Inbound media messages are automatically escalated to human mode so an
# agent can view the attachment and respond appropriately.
# Returns a Firestore-style document array so n8n can consume the output directly.

async def upsert_message(db: AsyncSession, redis, body) -> list:
    # Normalise wa_id so inbound and outbound messages always resolve to the
    # same Conversation row regardless of whether the '+' prefix is present.
    body.wa_id = _normalize_wa_id(body.wa_id)

    result = await db.execute(
        select(Conversation).where(Conversation.wa_id == body.wa_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(wa_id=body.wa_id)
        db.add(conv)
        await db.flush()

    sender    = MsgSender.user       if body.direction == "inbound" else MsgSender.ai
    direction = MsgDirection.inbound if body.direction == "inbound" else MsgDirection.outbound

    media_type    = getattr(body, "media_type",    None)
    media_url     = getattr(body, "media_url",     None)
    media_id      = getattr(body, "media_id",      None)
    media_caption = getattr(body, "media_caption", None)
    mime_type     = getattr(body, "mime_type",     None)
    filename      = getattr(body, "filename",      None)

    ts_ms: int | None = getattr(body, "ts_ms", None)
    ts_iso_raw: str | None = getattr(body, "ts_iso", None)
    if not ts_ms and ts_iso_raw:
        try:
            ts_ms = int(
                datetime.fromisoformat(ts_iso_raw.replace("Z", "+00:00"))
                .timestamp() * 1000
            )
        except (ValueError, AttributeError):
            pass
    if not ts_ms:
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    msg = Message(
        conversation_id=conv.id,
        wa_id=body.wa_id,
        direction=direction,
        sender=sender,
        text=body.text or (media_caption or f"[{media_type} received]" if media_type else ""),
        media_type=media_type,
        media_url=media_url,
        media_id=media_id,
        media_caption=media_caption,
        mime_type=mime_type,
        filename=filename,
        ts_ms=ts_ms,
    )
    db.add(msg)

    # ── Selective auto-escalation for inbound media ───────────────────────────
    # Audio voice notes are handled end-to-end by the AI (transcribed by Whisper,
    # replied to with TTS audio). They must NOT escalate to human mode.
    #
    # Images, videos, and documents cannot be processed by the AI and still
    # require a human agent to review and respond.
    escalated = False
    is_audio_media = media_type in ("audio",) or (
        mime_type and mime_type.startswith("audio/")
    )
    if direction == MsgDirection.inbound and media_type and not is_audio_media:
        if conv.intercept_mode != InterceptMode.human:
            conv.intercept_mode  = InterceptMode.human
            conv.intercept_since = datetime.now(timezone.utc)
            escalated = True

    await db.commit()
    await db.refresh(msg)

    # ── Broadcast WebSocket events ────────────────────────────────────────────
    await _broadcast(redis, str(conv.id), {
        "type":           "new_message",
        "conversationId": str(conv.id),
        "waId":           body.wa_id,
        "sender":         sender.value,
        "text":           msg.text,
        "mediaType":      media_type,
        "mediaId":        media_id,
        "mediaCaption":   media_caption,
        "mimeType":       mime_type,
        "filename":       filename,
    })

    if escalated:
        # Broadcast to all agents — anyone can pick it up
        await _broadcast(redis, "agents:all", {
            "event":          "notification",
            "type":           "human_transfer",
            "title":          f"Media received — {media_type}",
            "body":           f"{body.wa_id} sent a {media_type}{': ' + media_caption if media_caption else ''}",
            "waId":           body.wa_id,
            "conversationId": str(conv.id),
            "mediaType":      media_type,
        })
        # Also broadcast intercept change so conversation list updates
        await _broadcast(redis, str(conv.id), {
            "type":           "intercept_changed",
            "conversationId": str(conv.id),
            "mode":           "human",
        })

    # ── Build response ────────────────────────────────────────────────────────
    doc_id        = f"{msg.wa_id}_{ts_ms}"
    created_at    = msg.created_at or datetime.now(timezone.utc)
    ttl_expire_at = created_at + timedelta(days=120)
    ts_dt    = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    ts_iso   = _fmt_ts_ms(ts_dt)
    ttl_iso  = _fmt_ts_ms(ttl_expire_at)
    now_str  = _fmt_precise(created_at)

    fields = {
        "tsMs":        {"integerValue": str(ts_ms)},
        "direction":   {"stringValue": str(direction.value)},
        "ttlExpireAt": {"timestampValue": ttl_iso},
        "text":        {"stringValue": msg.text or ""},
        "tsIso":       {"stringValue": ts_iso},
        "wa_id":       {"stringValue": body.wa_id},
    }

    if media_type:
        fields["mediaType"]    = {"stringValue": media_type}
    if media_id:
        fields["mediaId"]      = {"stringValue": media_id}
    if media_url:
        fields["mediaUrl"]     = {"stringValue": media_url}
    if media_caption:
        fields["mediaCaption"] = {"stringValue": media_caption}
    if mime_type:
        fields["mimeType"]     = {"stringValue": mime_type}
    if filename:
        fields["filename"]     = {"stringValue": filename}
    if escalated:
        fields["escalated"]    = {"booleanValue": True}

    return [
        {
            "name": f"projects/neema-6037c/databases/(default)/documents/messages/{doc_id}",
            "fields": fields,
            "createTime": now_str,
            "updateTime": now_str,
        }
    ]

# ── Patch Message ─────────────────────────────────────────

async def patch_message(db: AsyncSession, docid: str, body) -> dict:
    """
    Patches an inbound message doc with its transcription/corrected text.

    The n8n 'patch inbound and outbound' node calls this with:
      - inbound_text  → corrected transcription for the inbound message
      - outbound_text → the AI reply text (NOT applied here — the outbound
                        Message row is already created by outbound_gate(), so
                        applying outbound_text here would overwrite the inbound
                        message's text field, causing a duplicate to appear in
                        the agent UI)
      - direction     → NOT applied; direction is set at insert time and must
                        never be changed by a patch, otherwise an inbound message
                        silently becomes outbound and renders on the wrong side.

    Only inbound_text updates are accepted. Everything else is a no-op.
    """
    from sqlalchemy import and_

    # ── Locate the message by UUID or by wa_id_tsMs composite key ────────────
    try:
        import uuid
        uuid.UUID(docid)
        result = await db.execute(
            select(Message).where(Message.id == docid)
        )
    except ValueError:
        # docid format: "{wa_id}_{ts_ms}" — strip '+' from wa_id so the lookup
        # matches the normalised form used when the message was inserted.
        parts = docid.rsplit("_", 1)
        if len(parts) == 2:
            wa_id = _norm_wa(parts[0])
            ts_ms = parts[1]
            result = await db.execute(
                select(Message).where(
                    and_(
                        Message.wa_id == wa_id,
                        Message.ts_ms == int(ts_ms),
                    )
                )
            )
        else:
            return {"ok": False, "error": f"Invalid docid format: {docid}"}

    msg = result.scalar_one_or_none()
    if not msg:
        # Silently skip — the inbound message may not have been upserted yet
        # (e.g. audio path where Upsert inbound audio message runs in parallel).
        return {"ok": True, "skipped": True, "docid": docid}

    # ── Only update inbound_text ──────────────────────────────────────────────
    # outbound_text is intentionally ignored: the outbound reply is already
    # stored as its own Message row by outbound_gate(). Applying it here would
    # overwrite the inbound message's text field, making it render on the
    # wrong side of the thread and appear as a duplicate of the outbound reply.
    #
    # direction is intentionally ignored: it is set at insert time and must
    # never be mutated post-hoc or inbound messages flip to the outbound side.
    if body.inbound_text is not None:
        msg.text = body.inbound_text

    await db.commit()
    return {"ok": True, "message_id": str(msg.id)}

# ── Touch Session ─────────────────────────────────────────

async def touch_session(db: AsyncSession, body) -> list:
    from app.models.session import Session as SessionModel

    def parse_dt(val):
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        return datetime.fromisoformat(val.replace("Z", "+00:00"))

    session_id = body.session_id or f"{body.wa_id}_{int(datetime.now(timezone.utc).timestamp())}"

    stmt = pg_insert(SessionModel).values(
        id=session_id,
        wa_id=body.wa_id,
        turns=body.turns,
        start_ts=parse_dt(body.start_ts),
        last_ts=parse_dt(body.last_ts),
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "turns": body.turns,
            "last_ts": parse_dt(body.last_ts),
        },
    )
    await db.execute(stmt)
    await db.commit()

    # Re-fetch the persisted row so timestamps reflect actual DB values
    result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
    row = result.scalar_one()

    now_precise = _fmt_precise(datetime.now(timezone.utc))

    return [
        {
            "name": f"projects/neema-6037c/databases/(default)/documents/sessions/{session_id}",
            "fields": {
                "turns":   {"integerValue": str(row.turns)},
                "lastTs":  {"timestampValue": _fmt_ts(row.last_ts)},
                "wa_id":   {"stringValue": row.wa_id},
                "startTs": {"timestampValue": _fmt_ts(row.start_ts)},
            },
            "createTime": _fmt_precise(row.start_ts),
            "updateTime": now_precise,
        }
    ]


# ── Get Messages ──────────────────────────────────────────

async def get_messages(db: AsyncSession, wa_id: str) -> list:
    result = await db.execute(
        select(Message)
        .where(Message.wa_id == wa_id)
        .order_by(Message.created_at.desc())
        .limit(50)
    )
    msgs = result.scalars().all()

    rows = []
    for m in msgs:
        created_at = m.created_at

        # ts_ms: prefer the stored ts_ms column; fall back to created_at
        if m.ts_ms is not None:
            ts_ms = m.ts_ms
        elif created_at:
            ts_ms = int(created_at.astimezone(timezone.utc).timestamp() * 1000)
        else:
            ts_ms = None

        # ts_iso: millisecond-precision ISO string for sorting consistency
        if ts_ms is not None:
            ts_iso = _fmt_ts_ms(datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc))
        elif created_at:
            ts_iso = _fmt_ts_ms(created_at.astimezone(timezone.utc))
        else:
            ts_iso = None

        rows.append({
            "id":         str(m.id),
            "wa_id":      m.wa_id,
            "direction":  m.direction,
            "sender":     m.sender,
            "text":       m.text,
            "media_type": m.media_type,
            "media_url":  m.media_url,
            "ts_ms":      ts_ms,       # integer ms — used by Bundle messages for sort
            "ts_iso":     ts_iso,      # ISO string with ms precision
            "created_at": created_at.isoformat() if created_at else None,
        })

    return rows


# ── Save User Facts ───────────────────────────────────────

async def save_user_facts(db: AsyncSession, body) -> dict:
    # Normalize wa_id — strip leading + to match how it's stored
    wa_id = (body.wa_id or "").lstrip("+").strip()
    
    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"ok": False, "error": "User not found"}

    only_if_empty = getattr(body, 'only_if_empty', [])
    for field in ("name", "email", "phone", "location", "age", "country", "country_iso", "flag_url"):
        val = getattr(body, field, None)
        if val is None:
            continue
        if field in only_if_empty and getattr(user, field, None):
            continue
        setattr(user, field, val)

    await db.commit()
    return {"ok": True}


# ── Upsert Order Event ────────────────────────────────────

async def upsert_order_event(db: AsyncSession, body) -> dict:
    from app.models.order_event import OrderEvent

    event_id = f"{body.wa_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"

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

