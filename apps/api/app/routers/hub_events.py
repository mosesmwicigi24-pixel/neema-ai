"""POST /api/hub/events — the hub tells Neema what happened to her orders.

HMAC-verified (X-Hub-Events-Signature: sha256=<hexdigest of raw body with
HUB_EVENTS_SECRET>), idempotent on event id, acks fast and processes in the
background. INERT (503) until the secret is configured — deploys dark.

Payload: {"id": "...", "type": "order.paid", "order_number": "...",
          "customer_phone": "+2547...", "amount": 12000, "currency": "KES",
          "tracking": "...", "items": [...]}  — see docs/AGENTIC_PARTNER_PLAN.md.
"""
import asyncio
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import settings

router = APIRouter()
_log = logging.getLogger("neema.hubevents")

_bg: set = set()


def _valid_signature(raw: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.hub_events_secret.encode(), raw,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


@router.post("/events")
async def receive_event(request: Request):
    if not settings.hub_events_secret:
        return Response(status_code=503)          # phase not enabled yet
    raw = await request.body()
    if not _valid_signature(raw, request.headers.get("x-hub-events-signature")):
        _log.warning("hub event rejected: bad signature")
        return Response(status_code=403)
    try:
        event = json.loads(raw)
    except Exception:
        return JSONResponse({"ok": False, "reason": "bad_json"}, status_code=422)

    redis = getattr(request.app.state, "redis", None)

    async def _process():
        from app.database import AsyncSessionLocal
        from app.services import hub_events as svc
        try:
            async with AsyncSessionLocal() as db:
                out = await svc.handle_event(db, redis, event)
            _log.info("hub event %s (%s) → %s", event.get("id"),
                      event.get("type"), out)
        except Exception as exc:
            _log.exception("hub event processing failed: %s", exc)

    task = asyncio.create_task(_process())
    _bg.add(task)
    task.add_done_callback(_bg.discard)
    return JSONResponse({"ok": True})
