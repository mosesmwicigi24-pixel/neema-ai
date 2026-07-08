"""Meta Messenger + Instagram webhook — verification handshake + inbound capture.

This is the neema-hosted Callback URL for the Meta app's Messenger/Instagram
webhook (docs/MULTICHANNEL_IDENTITY_PLAN.md, Phase 1). It handles:

  * GET  /api/meta/webhook  — Meta's subscription handshake: echo `hub.challenge`
    iff `hub.verify_token` matches settings.meta_verify_token.
  * POST /api/meta/webhook  — inbound events: verify the X-Hub-Signature-256,
    then CAPTURE the sender as a person/identity (channel = messenger | instagram,
    external_id = PSID | IGSID) and log the event. Always acks 200 fast.

**Scope note (intentional):** this captures *identity* — every unanswered
Messenger/IG DM becomes a person + identity row (the plan's "mine the backlog as
an identity-capture list"), which is safe and additive. It does NOT yet create
conversation/message rows or reply — the inbox/answering path is wa_id-keyed
(`UNIQUE(conversations.wa_id)`) and moving it to per-channel conversations is the
deferred query-layer cutover. So: verification works, identities flow, full
two-way Messenger chat lands with that cutover.

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

    try:
        await _capture_events(db, channel, payload)
    except Exception as exc:                     # never let capture break the ack
        _log.warning("meta webhook capture failed (%s) — acking anyway: %s", channel, exc)

    return PlainTextResponse("EVENT_RECEIVED")


async def _capture_events(db: AsyncSession, channel: str, payload: dict) -> None:
    """For each inbound messaging event, ensure a person/identity exists for the
    sender (identity capture). Best-effort; commits once."""
    from app.services.identity import resolve_or_create_person

    captured = 0
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []) or entry.get("standby", []):
            sender = (event.get("sender") or {}).get("id")
            if not sender:
                continue
            # Skip our own echoes.
            if event.get("message", {}).get("is_echo"):
                continue
            text = (event.get("message") or {}).get("text")
            await resolve_or_create_person(
                db, channel, str(sender),
                source=f"{channel}_inbound", confidence="deterministic",
                raw_profile={"last_text": text} if text else None,
            )
            captured += 1

    if captured:
        await db.commit()
        _log.info("meta webhook: captured %d %s sender identit%s",
                  captured, channel, "y" if captured == 1 else "ies")
