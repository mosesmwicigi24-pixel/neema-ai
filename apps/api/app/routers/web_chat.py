"""Web storefront chat endpoint — POST /web/chat.

The bethanyhouse.co.ke storefront's chat widget calls THIS agent instead of
running its own model, as a new "web" channel. Same brain (route_model, tools,
prompt caching, memory, hub grounding) as WhatsApp/Messenger — the difference is
that the CART and PAYMENT live on the storefront, so the agent never transacts
here. Instead of update_cart/create_order it returns product cards (with the hub
slug the storefront/POS use) and one-tap actions the site renders against its own
cart + M-Pesa/Card checkout. A human handoff comes back as a wa.me link, since the
widget can't send WhatsApp itself.

Auth is server-to-server: the storefront's server sends a shared secret in the
`X-Storefront-Key` header (the browser never sees it). It's mounted at /web so the
public path is POST /web/chat; on the same VPS the storefront can also reach it
directly at http://127.0.0.1:8000/web/chat with no nginx hop.
"""
from __future__ import annotations

import hmac
import logging
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent import runtime
from app.core.config import settings

router = APIRouter()
_log = logging.getLogger("neema.agent")

# Sensible caps so a malformed caller can't blow up a turn (the storefront is
# trusted, but defensive limits are cheap).
_MAX_MSG = 4000
_MAX_HISTORY = 24


# ── Auth ──────────────────────────────────────────────────────────────────────

async def verify_storefront_key(x_storefront_key: str | None = Header(default=None)) -> None:
    """Gate /web/chat on the shared storefront secret (constant-time compare).
    Unset secret → 503 (channel not configured) so a misconfigured deploy is
    obvious; wrong/missing header → 401."""
    if not settings.storefront_key:
        raise HTTPException(status_code=503, detail="web chat channel is not configured")
    if not x_storefront_key or not hmac.compare_digest(x_storefront_key, settings.storefront_key):
        raise HTTPException(status_code=401, detail="invalid or missing X-Storefront-Key")


# ── Request / response shapes ─────────────────────────────────────────────────

class HistoryTurn(BaseModel):
    role: str = "user"          # "user" | "assistant"
    content: str = ""


class WebChatRequest(BaseModel):
    session_id: str                                   # stable per-browser id (memory/conversation key)
    message: str = ""                                 # the customer's latest text
    history: list[HistoryTurn] = Field(default_factory=list)
    page_context: dict | None = None                  # {path, product_slug, category}
    locale: str | None = None                         # e.g. "en-KE"
    phone: str | None = None                          # "2547…" — if present, unify memory with WhatsApp
    image: str | None = None                          # data:image/…;base64,… (vision/measurement)


# ── Currency / handoff helpers ────────────────────────────────────────────────

def _web_currency(locale: str | None, phone: str | None) -> str:
    """KES for a Kenyan shopper (phone prefix wins, then the storefront locale),
    USD for everyone else — the same display gate WhatsApp/Meta use. The
    storefront prices cards in the shopper's own currency; this only governs the
    figures the agent quotes in chat."""
    from app.core.countries import resolve_country, iso_from_locale
    iso = None
    if phone:
        iso = (resolve_country(phone) or {}).get("country_iso")
    if not iso and locale:
        iso = iso_from_locale(str(locale).replace("-", "_"))
    return "KES" if (iso or "").upper() == "KE" else "USD"


def _wa_handoff_url(page_context: dict | None) -> str | None:
    """A wa.me link the storefront offers so the shopper can continue with a human
    on WhatsApp (the widget can't send WhatsApp itself). None if no number is set."""
    num = (settings.whatsapp_handoff_number or "").lstrip("+").strip()
    if not num:
        return None
    msg = "Hi Bethany House! I was chatting on your website and would like to talk to someone."
    slug = str((page_context or {}).get("product_slug") or "").strip()
    if slug:
        msg = (f"Hi Bethany House! I was on your website ({slug}) and would like to "
               "talk to someone.")
    return f"https://wa.me/{num}?text={quote(msg)}"


def _action_label(atype: str, name: str) -> str:
    if atype == "add_to_cart":
        return f"Add {name} to cart"
    if atype == "request_quote":
        return f"Request a quote — {name}"
    return f"View {name}"


def _qr_id(label: str, i: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    return slug or f"qr-{i + 1}"


# ── Identity: create the web contact + (optionally) unify with WhatsApp ────────

async def _prepare_web_contact(db, session_id: str, phone: str | None, locale: str | None):
    """Ensure a person/identity exists for this web session (so memory persists
    across sessions) and, when a phone is given, link it to the matching WhatsApp
    customer so the two share ONE memory + order history. Also ensures the
    conversation row exists, so a handoff during the turn finds it and the unified
    inbox shows the web chat. Returns the conversation (committed) or None on
    failure (the turn can still run without persistence)."""
    from app.services.identity import resolve_or_create_person, _select_identity, WHATSAPP
    from app.services.channel import get_or_create_conversation

    ident = await resolve_or_create_person(db, "web", session_id, source="web_chat",
                                           confidence="deterministic")
    primary_person_id = ident.person_id

    if phone:
        from app.core.phone import to_e164
        from app.core.countries import iso_from_locale
        from app.services.reconcile import attach_identifier
        region = iso_from_locale(str(locale or "").replace("-", "_")) or "KE"
        e164 = to_e164(phone, region)
        if e164:
            await attach_identifier(db, primary_person_id, "phone", e164,
                                    source="web_chat", confidence="self_reported")
            # Link to the phone-anchored WhatsApp person (it can transact + be
            # paid), keeping it primary — the web identity merges onto it.
            wa_ident = await _select_identity(db, WHATSAPP, e164.lstrip("+"))
            if wa_ident is not None and wa_ident.person_id != primary_person_id:
                from app.services.merge import merge_persons
                try:
                    await merge_persons(db, primary_person_id=wa_ident.person_id,
                                        secondary_person_id=primary_person_id,
                                        primary_wa_id=e164.lstrip("+"))
                    primary_person_id = wa_ident.person_id
                except Exception as exc:
                    _log.warning("web/chat phone link failed for %s: %s", session_id, exc)

    conv = await get_or_create_conversation(db, "web", session_id, person_id=primary_person_id)
    # A returning web session whose phone just merged it onto a WhatsApp person:
    # re-point the conversation at the surviving person (get_or_create only adopts
    # when it was None), so the inbox groups the web chat under the right customer.
    if conv.person_id != primary_person_id:
        conv.person_id = primary_person_id
    await db.commit()
    return conv


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/chat", dependencies=[Depends(verify_storefront_key)])
async def web_chat(body: WebChatRequest, request: Request):
    session_id = (body.session_id or "").strip()[:128]
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    message = (body.message or "").strip()[:_MAX_MSG]
    image = body.image if (body.image or "").startswith("data:") else None
    if not message and not image:
        raise HTTPException(status_code=422, detail="message or image is required")

    redis = getattr(request.app.state, "redis", None)
    from app.database import AsyncSessionLocal

    currency = _web_currency(body.locale, body.phone)
    history = [{"role": h.role, "content": h.content} for h in body.history][-_MAX_HISTORY:]
    page_context = body.page_context if isinstance(body.page_context, dict) else None
    media = {"type": "image", "url": image} if image else None

    # 1) Resolve/unify the contact + persist the inbound (own session, so nothing
    #    here can poison the turn). Best-effort: the turn still runs if it fails.
    try:
        async with AsyncSessionLocal() as db0:
            conv = await _prepare_web_contact(db0, session_id, (body.phone or "").strip() or None,
                                              body.locale)
            if conv is not None:
                from app.models.message import Message, MsgDirection, MsgSender
                from datetime import datetime, timezone
                preview = message or "[image]"
                db0.add(Message(
                    channel="web", external_id=session_id, wa_id=None,
                    person_id=conv.person_id, conversation_id=conv.id,
                    direction=MsgDirection.inbound, sender=MsgSender.user,
                    text=preview, media_type=("image" if image else None),
                ))
                conv.last_message_at = datetime.now(timezone.utc)
                conv.last_message_preview = preview[:100]
                await db0.commit()
    except Exception:
        _log.warning("web/chat contact prep failed for %s", session_id, exc_info=True)

    # 2) Run the agent turn (own session). A photo always takes the main model —
    #    vision + catalogue matching is never "light" work.
    sink: dict = {}
    model = settings.tier2_model if media else runtime.route_model(message)
    try:
        async with AsyncSessionLocal() as db:
            reply = await runtime.run_turn(
                db, redis, wa_id="", user_text=message,
                llm=runtime.build_llm(model=model), media=media,
                channel="web", external_id=session_id,
                history=history, page_context=page_context,
                currency=currency, web_sink=sink,
            )
    except Exception:
        _log.exception("web/chat turn failed for %s", session_id)
        # Never leave the widget hanging — a warm fallback + a WhatsApp option.
        reply = ("Sorry, I hit a snag just now. Please try again in a moment — or reach us "
                 "on WhatsApp and we'll help you right away.")
        sink = {"handoff": {"reason": "web turn error"}}

    # 3) Persist the outbound reply (own session, best-effort — inbox visibility).
    try:
        async with AsyncSessionLocal() as db2:
            from app.services import n8n_bridge as svc
            await svc.save_outbound_channel_message(db2, redis, "web", session_id, reply)
    except Exception:
        _log.warning("web/chat outbound persist failed for %s", session_id, exc_info=False)

    # 4) Shape the response the storefront renders.
    products_raw = sink.get("products") or []
    products = [{"slug": p["slug"], "reason": p.get("reason", "")} for p in products_raw]

    actions = []
    for p in products_raw:
        atype = p.get("action") or "view_product"
        actions.append({"type": atype, "label": _action_label(atype, p.get("name") or p["slug"]),
                        "value": p["slug"]})

    wa_url = _wa_handoff_url(page_context)
    handoff_requested = sink.get("handoff") is not None
    handoff = {"required": handoff_requested, "url": wa_url}
    if handoff_requested and wa_url:
        actions.append({"type": "whatsapp", "label": "Continue on WhatsApp", "value": wa_url})

    quick_replies = [{"id": _qr_id(q, i), "label": q}
                     for i, q in enumerate(sink.get("quick_replies") or [])]

    return {
        "reply": reply,
        "products": products,
        "actions": actions,
        "quick_replies": quick_replies,
        "handoff": handoff,
    }
