"""Meta Messenger + Instagram webhook — verification handshake + inbound capture.

This is the neema-hosted Callback URL for the Meta app's Messenger/Instagram
webhook (docs/MULTICHANNEL_IDENTITY_PLAN.md, Phase 1). It handles:

  * GET  /api/meta/webhook  — Meta's subscription handshake: echo `hub.challenge`
    iff `hub.verify_token` matches settings.meta_verify_token.
  * POST /api/meta/webhook  — inbound events: verify the X-Hub-Signature-256,
    then CAPTURE the sender as a person/identity (channel = messenger | instagram,
    external_id = PSID | IGSID) and log the event. Always acks 200 fast.

**Scope:** inbound DMs now land in the unified inbox — each event resolves the
sender to a person/identity, gets-or-creates the (channel, sender) conversation,
and stores the message (idempotent on the Meta message id). Outbound *replies*
(agent answering Messenger/IG) are the next slice (C4) — a Send-API sender.

The webhook is INERT until `meta_verify_token` is configured (handshake 403s),
so deploying this changes nothing until you switch it on in the Meta app.
"""
import hashlib
import hmac
import logging

from fastapi import APIRouter, Request, Response, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import get_db

router = APIRouter()
_log = logging.getLogger("neema.meta")


@router.get("/webhook")
async def verify_webhook(request: Request):
    """Meta subscription handshake. Returns the challenge as plain text on a
    matching verify token, else 403."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    if not settings.meta_verify_token:
        _log.warning("Meta webhook GET hit but META_VERIFY_TOKEN is unset — refusing.")
        return Response(status_code=403)
    if mode == "subscribe" and token and hmac.compare_digest(token, settings.meta_verify_token):
        return PlainTextResponse(challenge)
    return Response(status_code=403)


def _valid_signature(raw_body: bytes, header: str | None) -> bool:
    """Verify Meta's X-Hub-Signature-256 (HMAC-SHA256 of the raw body with the
    app secret). Skipped (returns True) when meta_app_secret is unset — dev only."""
    if not settings.meta_app_secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.meta_app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


@router.post("/webhook")
async def receive_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive Messenger/Instagram events. Verifies the signature, captures the
    sender identity, logs, and always acks 200 (Meta retries on non-200)."""
    raw = await request.body()
    if not _valid_signature(raw, request.headers.get("x-hub-signature-256")):
        _log.warning("Meta webhook POST rejected: bad X-Hub-Signature-256")
        return Response(status_code=403)

    try:
        payload = await request.json()
    except Exception:
        return PlainTextResponse("EVENT_RECEIVED")

    # object=page → Messenger; object=instagram → Instagram DM. Same event shape.
    channel = "instagram" if payload.get("object") == "instagram" else "messenger"

    redis = getattr(request.app.state, "redis", None)
    try:
        await _capture_events(db, channel, payload, redis=redis)
    except Exception as exc:                     # never let capture break the ack
        _log.warning("meta webhook capture failed (%s) — acking anyway: %s", channel, exc)

    return PlainTextResponse("EVENT_RECEIVED")


def _event_text(message: dict) -> str:
    """Human-readable text for an inbound event — the message text, else a
    placeholder for an attachment (image/sticker/etc.)."""
    text = (message.get("text") or "").strip()
    if text:
        return text
    atts = message.get("attachments") or []
    if atts:
        return f"[{atts[0].get('type', 'attachment')}]"
    return ""


async def _capture_events(db: AsyncSession, channel: str, payload: dict, redis=None) -> None:
    """For each inbound Messenger/IG event: resolve the sender to a person/identity,
    get-or-create the (channel, sender) conversation, and store the inbound
    message — so the DM lands in the unified inbox. Idempotent on the Meta message
    id (mid) so a redelivered webhook doesn't duplicate rows. Commits once; the
    caller always acks 200 regardless."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.services.identity import resolve_or_create_person
    from app.services.channel import get_or_create_conversation
    from app.models.message import Message, MsgDirection, MsgSender
    from app.models.conversation import InterceptMode

    broadcasts: list[tuple[str, dict]] = []
    replies: list[tuple[str, str, str | None]] = []   # (sender, text, mid) to hand the agent
    captured = 0
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []) or entry.get("standby", []):
            sender = (event.get("sender") or {}).get("id")
            message = event.get("message") or {}
            if not sender or message.get("is_echo"):    # skip page echoes / non-message events
                continue
            sender = str(sender)
            mid = message.get("mid")

            # Idempotency: a redelivered webhook must not create a duplicate.
            if mid:
                dup = (await db.execute(
                    select(Message.id).where(Message.channel == channel,
                                             Message.waba_msg_id == mid).limit(1)
                )).scalar_one_or_none()
                if dup is not None:
                    continue

            text = _event_text(message)
            ident = await resolve_or_create_person(
                db, channel, sender,
                source=f"{channel}_inbound", confidence="deterministic",
                raw_profile={"last_text": text} if text else None,
            )
            conv = await get_or_create_conversation(db, channel, sender, person_id=ident.person_id)

            db.add(Message(
                channel=channel, external_id=sender, wa_id=None,
                person_id=ident.person_id, conversation_id=conv.id,
                direction=MsgDirection.inbound, sender=MsgSender.user,
                text=text, waba_msg_id=mid,
            ))
            conv.last_message_at = datetime.now(timezone.utc)
            conv.last_message_preview = (text or f"[{channel} message]")[:100]
            broadcasts.append((str(conv.id), {
                "type": "new_message", "conversationId": str(conv.id),
                "channel": channel, "sender": "user", "text": text,
            }))
            # Only hand the agent a real text turn (skip attachment placeholders),
            # and only when the conversation is AI-mode (never talk over a human).
            if message.get("text") and conv.intercept_mode == InterceptMode.ai:
                replies.append((sender, message["text"].strip(), mid))
            captured += 1

    if captured:
        await db.commit()
        _log.info("meta webhook: captured %d %s message(s) into the inbox", captured, channel)
        if redis is not None:
            import json
            for conv_id, ev in broadcasts:
                try:
                    await redis.publish(f"ws:channel:{conv_id}", json.dumps(ev))
                except Exception:
                    pass   # broadcast is best-effort

        # ── Neema answers (gated by META_AGENT_REPLY) ─────────────────────────
        # Same Tier-2 agent, same KES hub catalogue; reply goes out via the Graph
        # Send API. Fires after the inbound is persisted; deduped on the Meta mid.
        if settings.meta_agent_reply:
            from app.agent import runtime
            for sender, text, mid in replies:
                try:
                    await runtime.schedule_meta_reply(redis, channel, sender, text, dedup_id=mid)
                except Exception as exc:
                    _log.warning("meta agent reply failed to schedule for %s: %s", sender, exc)
