"""Short tap-to-order links.

`GET /api/o/{ref}` 302-redirects to the pre-filled wa.me target stored in redis
under `waref:{ref}`. This lets a comment reply show a short, clean, on-brand link
(`neema.bethanyhouse.co.ke/api/o/7F7EC8`) instead of a scary 300-char
`wa.me?text=…` URL, and lets us see the click. If the ref has expired, we fall
back to the bare WhatsApp chat so the customer still reaches us.
"""
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings

router = APIRouter()
_log = logging.getLogger("neema.short")


@router.get("/o/{ref}")
async def order_redirect(ref: str, request: Request):
    target = None
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            raw = await redis.get(f"waref:{ref}")
            if raw:
                target = (json.loads(raw) or {}).get("target")
        except Exception:
            pass
    if not target:                                  # expired/unknown ref → bare chat
        num = (settings.whatsapp_handoff_number or "").lstrip("+").strip()
        target = f"https://wa.me/{num}" if num else "https://facebook.com"
    return RedirectResponse(target, status_code=302)
