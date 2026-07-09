"""Public, unauthenticated storefront — the customer-facing shareable catalog.

Reads the hub's PUBLIC product data (via the same cached client the agent sells
from) and returns ONLY customer-relevant fields. A shared catalog link therefore
never exposes Neema's internal database, order data, customer records, or the
admin surface — the whole point of a customer-faced view.

Mounted at /api/public with NO auth dependency.
"""
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import hub_client
from app.core.config import settings
from app.database import get_db

router = APIRouter()


def _clean_phone(raw: str | None) -> str:
    """Digits only, no leading +/0-cc juggling beyond stripping symbols."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return digits.lstrip("0") if digits.startswith("0") and len(digits) > 9 else digits


def _order_url(name: str | None) -> str | None:
    """A one-tap WhatsApp order link, pre-filled with the product name. Built
    server-side so the number stays out of the client bundle. None if unset."""
    num = (settings.whatsapp_handoff_number or "").lstrip("+").strip()
    if not num:
        return None
    msg = f"Hi Bethany House! I'm interested in {name}." if name else "Hi Bethany House!"
    return f"https://wa.me/{num}?text={quote(msg)}"


def _card(p: dict) -> dict:
    """The customer-safe projection of a catalogue product."""
    return {
        "slug":          p.get("slug"),
        "name":          p.get("name"),
        "category":      p.get("category"),
        "description":   p.get("description"),
        "price_kes":     p.get("price_kes"),
        "price_usd":     p.get("price_usd"),
        "image_url":     p.get("image_url"),
        "thumbnail_url": p.get("thumbnail_url"),
        # Producible items are made-to-order — the catalog shows "Made to order"
        # rather than a stock count, so they're never wrongly "out of stock".
        "made_to_order": bool(p.get("is_producible")),
        "in_stock":      bool(p.get("in_stock", True)),
        "order_url":     _order_url(p.get("name")),
    }


async def _catalog(request: Request) -> list[dict]:
    redis = getattr(request.app.state, "redis", None)
    try:
        return await hub_client.fetch_hub_catalog(redis)
    except Exception:
        raise HTTPException(status_code=503, detail="Catalog temporarily unavailable")


@router.get("/catalog")
async def public_catalog(request: Request):
    """Every sellable product as a customer card (name + price + image)."""
    items = await _catalog(request)
    return [_card(p) for p in items if p.get("name") and p.get("slug")]


@router.get("/catalog/{slug}")
async def public_product(slug: str, request: Request):
    """One product's detail — includes the full image gallery."""
    items = await _catalog(request)
    p = next((x for x in items if x.get("slug") == slug), None)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    card = _card(p)
    card["images"] = p.get("images") or []
    return card


@router.post("/order/measure")
async def submit_measurement(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """A customer's free-form made-to-order request (measurements + notes) for a
    catalogue item. This is an ENQUIRY, not a hub order: it lands flagged in the
    staff inbox (as an inbound message on the customer's phone-keyed conversation,
    switched to human mode) so a colleague reviews it and sets up production. No
    anonymous web form ever writes a real order/payment to the hub."""
    slug = (body.get("slug") or "").strip()
    name = (body.get("name") or "").strip()
    phone = _clean_phone(body.get("phone"))
    if not name or len(phone) < 9:
        raise HTTPException(status_code=422, detail="Please provide your name and a valid phone number.")

    items = await _catalog(request)
    prod = next((x for x in items if x.get("slug") == slug), None)
    prod_name = (prod or {}).get("name") or (body.get("product") or "a made-to-order item")

    # Rate-limit: one submission per (phone, product) per 5 min — stops accidental
    # double-taps and casual spam without blocking a genuine second request.
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            ok = await redis.set(f"measure:{phone}:{slug or 'x'}", "1", nx=True, ex=300)
            if not ok:
                return {"ok": True, "message": "We've already received your request — we'll be in touch shortly!"}
        except HTTPException:
            raise
        except Exception:
            pass

    # Compose the enquiry text from whatever free-form fields were sent.
    measurements = body.get("measurements") or {}
    notes = (body.get("notes") or "").strip()
    location = (body.get("location") or "").strip()
    lines = [f"🧵 Made-to-order request — {prod_name}", f"From: {name} ({phone})"]
    if isinstance(measurements, dict):
        for k, v in measurements.items():
            if str(v).strip():
                lines.append(f"• {k}: {str(v).strip()}")
    elif str(measurements).strip():
        lines.append(f"• Measurements: {str(measurements).strip()}")
    if location:
        lines.append(f"• Delivery: {location}")
    if notes:
        lines.append(f"Notes: {notes}")
    text = "\n".join(lines)

    from app.services.n8n_bridge import provision_user
    from app.services.channel import get_or_create_conversation
    from app.models.message import Message, MsgDirection, MsgSender
    from app.models.conversation import InterceptMode
    from app.models.intercept import Intercept, InterceptAction
    from app.models.production_enquiry import ProductionEnquiry

    user = await provision_user(db, phone, name=name)
    conv = await get_or_create_conversation(db, "whatsapp", phone, person_id=user.person_id)
    conv.intercept_mode = InterceptMode.human          # hand to a human, don't auto-sell
    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = f"🧵 Made-to-order: {prod_name}"[:100]
    db.add(Message(
        channel="whatsapp", external_id=phone, wa_id=phone,
        person_id=user.person_id, conversation_id=conv.id,
        direction=MsgDirection.inbound, sender=MsgSender.user, text=text,
    ))
    db.add(Intercept(
        conversation_id=conv.id, action=InterceptAction.flag,
        note=f"Made-to-order measurement request — {prod_name}",
    ))
    # Structured record so a colleague can push it to the hub in one tap.
    enq = ProductionEnquiry(
        product_slug=slug or None,
        product_name=prod_name,
        hub_product_id=(prod or {}).get("hub_product_id"),
        customer_name=name,
        phone=phone,
        country_iso=(getattr(user, "country_iso", None) or None),
        measurements=(measurements if isinstance(measurements, dict) else {"notes": str(measurements)}),
        notes=notes or None,
        location=location or None,
        conversation_id=conv.id,
        person_id=user.person_id,
        status="new",
    )
    db.add(enq)
    await db.commit()

    if redis is not None:
        try:
            import json
            await redis.publish(f"ws:channel:{conv.id}", json.dumps({
                "type": "new_message", "conversationId": str(conv.id),
                "channel": "whatsapp", "sender": "user", "text": text,
            }))
        except Exception:
            pass

    return {"ok": True, "reference": str(enq.id),
            "message": "Thank you! We've received your measurements and will confirm your made-to-order shortly."}


# ── Customer order tracking ───────────────────────────────────────────────────
# The enquiry's UUID is an unguessable capability token (given to the customer on
# submit), so tracking needs no login and orders can't be enumerated. Returns
# ONLY a coarse stage + product name — never phone, prices, or internal ids.

_TRACK_STAGES = ["received", "in_production", "ready", "delivered"]


@router.get("/order/track/{ref}")
async def track_order(ref: str, request: Request, db: AsyncSession = Depends(get_db)):
    from app.models.production_enquiry import ProductionEnquiry
    import uuid as _uuid
    try:
        eid = _uuid.UUID(ref)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Order not found")
    e = await db.get(ProductionEnquiry, eid)
    if not e:
        raise HTTPException(status_code=404, detail="Order not found")

    stage = "received"
    if e.status == "declined":
        stage = "closed"
    elif e.status == "pushed":
        stage = "in_production"
        if e.hub_order_id:
            try:
                redis = getattr(request.app.state, "redis", None)
                st = await hub_client.fetch_order_status(e.hub_order_id, redis) or {}
                fulfil = (st.get("fulfillment_status") or "").lower()
                sraw = (st.get("status") or "").lower()
                if fulfil in ("delivered", "fulfilled") or sraw in ("delivered", "completed"):
                    stage = "delivered"
                elif fulfil in ("ready", "ready_for_pickup", "packed", "picked"):
                    stage = "ready"
            except Exception:
                pass  # keep "in_production" on any hub hiccup

    return {
        "product_name": e.product_name,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "order_number": e.hub_order_number,
        "stage": stage,                         # received | in_production | ready | delivered | closed
        "stages": _TRACK_STAGES,
    }
