"""Inbound SMS bridge — the business SIM's texts, visible in Neema.

WhatsApp Cloud API numbers cannot receive OTP/template messages sent by other
businesses (Meta strips the content — error 131051, an empty stub). But the SIM
behind the number still receives plain SMS. A forwarder app on the phone holding
that SIM POSTs each text here, and it appears in the inbox as an `sms`
conversation — verification codes included.

Receive-only: Neema cannot send SMS, so these conversations are created
human-held and the reply path refuses them with a clear error.

Phone-side setup (any SMS forwarder that can POST JSON, e.g. "SMS Forwarder —
Auto forward SMS" on Android):
    URL     https://neema.bethanyhouse.co.ke/api/sms/inbound
    Method  POST, Content-Type: application/json
    Header  Authorization: Bearer <SMS_INBOUND_TOKEN>
    Body    {"from": "{sender}", "body": "{message}"}
The endpoint is disabled (404) until SMS_INBOUND_TOKEN is set in the API env.
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import get_db

router = APIRouter()
_log = logging.getLogger("neema.sms")


@router.post("/inbound")
async def inbound_sms(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    token = getattr(settings, "sms_inbound_token", "") or ""
    if not token:
        raise HTTPException(status_code=404, detail="SMS bridge is not enabled")
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=403, detail="Bad token")

    sender = "".join(ch for ch in str(body.get("from") or "") if ch.isdigit())
    text = str(body.get("body") or body.get("text") or "").strip()
    if not sender or not text:
        raise HTTPException(status_code=422, detail="from and body are required")

    from app.models.conversation import InterceptMode
    from app.models.message import Message, MsgDirection, MsgSender
    from app.services.channel import get_or_create_conversation
    from app.services.identity import resolve_or_create_person

    # The phone-sibling adoption in resolve_or_create_person binds this SMS to
    # the SAME person as their WhatsApp chat when the numbers match.
    ident = await resolve_or_create_person(db, "sms", sender, source="sms")
    conv = await get_or_create_conversation(db, "sms", sender,
                                            person_id=ident.person_id)
    # Receive-only channel: the AI must never engage (nothing can be sent back).
    if conv.intercept_mode != InterceptMode.human:
        conv.intercept_mode = InterceptMode.human
    db.add(Message(
        channel="sms", external_id=sender, wa_id=None,
        person_id=ident.person_id, conversation_id=conv.id,
        direction=MsgDirection.inbound, sender=MsgSender.user, text=text,
    ))
    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = text[:100]
    await db.commit()
    _log.info("sms bridge: stored SMS from +%s (%d chars)", sender, len(text))

    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            await redis.publish("ws:channel:agents:all", json.dumps({
                "event": "notification", "type": "new_message",
                "title": f"SMS to the business number from +{sender}",
                "body": text[:160], "conversationId": str(conv.id)}))
            await redis.publish(f"ws:channel:{conv.id}", json.dumps({
                "type": "new_message", "conversationId": str(conv.id),
                "channel": "sms", "sender": "user", "text": text}))
        except Exception:
            pass
    return {"ok": True, "conversation_id": str(conv.id)}
