"""READ-ONLY ACCESS TO THE REAL RECORD, BY KEY (owner, 2026-11-15: "Build
access key so that you can read the record").

An investigation of a real conversation used to work from screenshots. This
gives a reader holding `OPS_READ_KEY` the record itself — and nothing else:

  * OFF unless the server has a key of 32+ characters (every route is 404);
  * GET only; nothing here writes, sends, or changes a conversation;
  * the key is compared in constant time and is never logged;
  * phone numbers come back masked (last four digits);
  * every read is logged (which route, which conversation — not the key);
  * wrong keys are counted and the door closes for a while after too many.

The key travels in the `X-Ops-Key` header. To turn the access off, remove
`OPS_READ_KEY` from the server's environment and restart.
"""
from __future__ import annotations

import hmac
import logging
import time
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import get_db
from app.models.conversation import Conversation
from app.models.message import Message

router = APIRouter()
_log = logging.getLogger("neema.ops_read")

MIN_KEY = 32
_MAX_BAD = 10                 # wrong keys …
_BAD_WINDOW = 600             # … within this many seconds close the door
_bad: list[float] = []


def mask(v: str | None) -> str:
    """A contact handle with all but its last four characters hidden."""
    s = str(v or "")
    return ("•" * max(len(s) - 4, 0) + s[-4:]) if len(s) > 4 else "••••"


def _configured() -> str:
    key = (getattr(settings, "ops_read_key", "") or "").strip()
    return key if len(key) >= MIN_KEY else ""


async def require_key(x_ops_key: str | None = Header(default=None)) -> None:
    key = _configured()
    if not key:
        raise HTTPException(status_code=404, detail="Not Found")
    now = time.monotonic()
    _bad[:] = [t for t in _bad if now - t < _BAD_WINDOW]
    if len(_bad) >= _MAX_BAD:
        raise HTTPException(status_code=429, detail="Too many attempts")
    if not x_ops_key or not hmac.compare_digest(x_ops_key.encode(), key.encode()):
        _bad.append(now)
        _log.warning("ops read: wrong or missing key (%d recent)", len(_bad))
        raise HTTPException(status_code=401, detail="Unauthorized")


def _conv_row(c: Conversation) -> dict:
    return {"id": str(c.id), "channel": c.channel,
            "contact": mask(c.wa_id or c.external_id),
            "mode": getattr(c.intercept_mode, "value", str(c.intercept_mode)),
            "status": getattr(c.status, "value", str(c.status)),
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None}


@router.get("/conversations")
async def conversations(ends_with: str = Query("", max_length=12),
                        channel: str = Query("", max_length=20),
                        limit: int = Query(20, ge=1, le=50),
                        db: AsyncSession = Depends(get_db),
                        _: None = Depends(require_key)) -> dict:
    """Recent conversations, newest first. `ends_with` = the last digits of
    the contact's number (4 or more), to find one thread without ever
    sending the whole number."""
    q = select(Conversation).order_by(Conversation.last_message_at.desc().nullslast())
    tail = "".join(ch for ch in ends_with if ch.isalnum())
    if tail:
        if len(tail) < 4:
            raise HTTPException(status_code=422, detail="ends_with needs 4 or more characters")
        q = q.where(or_(Conversation.wa_id.like(f"%{tail}"),
                        Conversation.external_id.like(f"%{tail}")))
    if channel:
        q = q.where(Conversation.channel == channel)
    rows = (await db.execute(q.limit(limit))).scalars().all()
    _log.info("ops read: conversations list (%d)", len(rows))
    return {"conversations": [_conv_row(c) for c in rows]}


async def _conv(db: AsyncSession, conv_id: str) -> Conversation:
    try:
        cid = uuid.UUID(conv_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not Found")
    c = await db.get(Conversation, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return c


@router.get("/conversations/{conv_id}/messages")
async def messages(conv_id: str, limit: int = Query(200, ge=1, le=500),
                   offset: int = Query(0, ge=0),
                   db: AsyncSession = Depends(get_db),
                   _: None = Depends(require_key)) -> dict:
    """The thread, oldest first: who said what and when, what kind of media
    came with it, and the photo's number and reading when it has one. Media
    files themselves are not served here."""
    c = await _conv(db, conv_id)
    rows = (await db.execute(
        select(Message).where(Message.conversation_id == c.id)
        .order_by(Message.created_at.asc()).offset(offset).limit(limit))).scalars().all()
    _log.info("ops read: messages of %s (%d)", c.id, len(rows))
    out = []
    for m in rows:
        meta = m.raw_meta if isinstance(m.raw_meta, dict) else {}
        out.append({
            "at": m.created_at.isoformat() if m.created_at else None,
            "direction": getattr(m.direction, "value", str(m.direction)),
            "sender": getattr(m.sender, "value", str(m.sender)),
            "text": m.text, "media_type": m.media_type,
            "media_caption": m.media_caption, "has_media": bool(m.media_url),
            "photo": meta.get("photo") if isinstance(meta.get("photo"), dict) else None,
            "kind": meta.get("kind"),
            "reply_to_text": m.reply_to_text,
        })
    return {"conversation": _conv_row(c), "messages": out}


@router.get("/conversations/{conv_id}/order")
async def order_state(conv_id: str, db: AsyncSession = Depends(get_db),
                      _: None = Depends(require_key)) -> dict:
    """The order as the system holds it for this contact: the cart's lines
    (who each piece is for) and what awaits a colleague's price."""
    from app.agent import cart as cartmod, order_sheet
    c = await _conv(db, conv_id)
    key = c.wa_id if c.channel == "whatsapp" else c.external_id
    cart = await cartmod.get_cart(db, key, c.channel)
    _log.info("ops read: order of %s", c.id)
    keep = ("name", "sku", "qty", "unit_price", "price_usd", "made_to_order", "units")
    return {"conversation": _conv_row(c),
            "items": [{k: i.get(k) for k in keep if k in i} for i in cart.get("items", [])],
            "total_kes": cartmod.cart_total(cart),
            "awaiting_price": order_sheet.pending_of(cart)}


# ── who among the people who wrote to us was served (owner, 2026-11-23) ──────
_PAID = {"paid", "completed", "settled", "success", "successful", "complete"}


def _when(v):
    from datetime import datetime, timezone
    if not v:
        return None
    try:
        d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def served_reading(first_chat_at, hub_summary: dict | None) -> dict:
    """One contact against their hub record: were they in the hub at all, did
    they buy on or after the day they first wrote to us, and through which
    kind of order (the hub's own `order_type`: till, chat, invoice …). Pure:
    counts and amounts only, never a name or a number."""
    out = {"in_hub": bool(hub_summary), "orders": 0, "after": [], "before": 0}
    if not hub_summary:
        return out
    first = _when(first_chat_at)
    day0 = first.replace(hour=0, minute=0, second=0, microsecond=0) if first else None
    for o in hub_summary.get("orders") or []:
        out["orders"] += 1
        made = _when(o.get("created_at"))
        if day0 is not None and made is not None and made < day0:
            out["before"] += 1
            continue
        out["after"].append({
            "type": str(o.get("order_type") or "unknown").lower(),
            "paid": str(o.get("payment_status") or "").lower() in _PAID,
            "total": float(o.get("total") or 0),
            "currency": str(o.get("currency_code") or "").upper() or "?",
            "undated": made is None,
            "days": (made - day0).days if (made is not None and day0 is not None) else None})
    return out


@router.get("/served")
async def served(request: Request, channel: str = Query("whatsapp", max_length=20),
                 days: int = Query(30, ge=1, le=120),
                 limit: int = Query(60, ge=1, le=100), offset: int = Query(0, ge=0),
                 db: AsyncSession = Depends(get_db),
                 _: None = Depends(require_key)) -> dict:
    """How many of the people who wrote to us on a channel were SERVED,
    by the hub's own record of till orders, chat orders and invoices.

    Each contact active in the last `days` is matched to their hub customer
    by phone ON THE SERVER (the hub's own number formats, country-aware), and
    only counts come back: no name, no number, no order line. One page of
    contacts per call (`limit`/`offset`), so the hub is asked gently."""
    import asyncio
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func
    from app.core import hub_client
    from app.core.phone import is_plausible_phone
    from app.models.order_event import OrderEvent

    since = datetime.now(timezone.utc) - timedelta(days=days)
    raw = (await db.execute(
        select(Conversation.id, Conversation.wa_id, Conversation.person_id)
        .where(Conversation.channel == channel, Conversation.last_message_at >= since)
        .order_by(Conversation.last_message_at.desc()).offset(offset).limit(limit))).all()
    # THE NUMBER THAT LINKS A CHAT TO A PURCHASE: WhatsApp is its own number;
    # on Messenger, Instagram, TikTok and the website it is the phone the
    # customer gave us in the chat (saved on their person), when they gave one.
    saved: dict = {}
    if channel != "whatsapp":
        from app.models.person import Identifier
        pids = [r[2] for r in raw if r[2] is not None]
        if pids:
            for pid, val in (await db.execute(
                    select(Identifier.person_id, Identifier.value)
                    .where(Identifier.person_id.in_(pids), Identifier.type == "phone"))).all():
                saved.setdefault(pid, (val or "").lstrip("+"))
    rows = [(r[0], (r[1] if channel == "whatsapp" else saved.get(r[2])) or "") for r in raw]
    ids = [r[0] for r in rows]
    firsts = dict((await db.execute(
        select(Message.conversation_id, func.min(Message.created_at))
        .where(Message.conversation_id.in_(ids)).group_by(Message.conversation_id))).all()) if ids else {}
    numbers = [r[1] for r in rows if is_plausible_phone(r[1])]
    neema = (await db.execute(
        select(OrderEvent.wa_id, OrderEvent.hub_payment_status)
        .where(OrderEvent.wa_id.in_(numbers), OrderEvent.hub_order_id.isnot(None),
               OrderEvent.created_at >= since))).all() if numbers else []
    redis = getattr(request.app.state, "redis", None)
    gate = asyncio.Semaphore(4)

    async def one(conv_id, wa_id):
        if not is_plausible_phone(wa_id):
            return None
        async with gate:
            try:
                summ = await hub_client.fetch_customer_summary(wa_id, redis)
            except Exception:
                return "error"
        return served_reading(firsts.get(conv_id), summ)

    results = await asyncio.gather(*(one(cid, wa) for cid, wa in rows))
    tally = {"contacts": len(rows), "no_number_saved": 0, "hub_error": 0, "in_hub": 0,
             "bought_before_only": 0, "ordered_since_first_chat": 0, "paid_since_first_chat": 0}
    by_type: dict = {}
    value: dict = {}
    # how long after the first chat the first purchase came (per contact)
    lag = {"same_day": 0, "1_to_3_days": 0, "4_to_14_days": 0, "15_days_or_more": 0, "date_unknown": 0}
    for r in results:
        if r is None:
            tally["no_number_saved"] += 1
            continue
        if r == "error":
            tally["hub_error"] += 1
            continue
        if r["in_hub"]:
            tally["in_hub"] += 1
        if r["after"]:
            tally["ordered_since_first_chat"] += 1
            _d = [o["days"] for o in r["after"] if o.get("days") is not None]
            if not _d:
                lag["date_unknown"] += 1
            else:
                _m = min(_d)
                lag["same_day" if _m <= 0 else "1_to_3_days" if _m <= 3
                    else "4_to_14_days" if _m <= 14 else "15_days_or_more"] += 1
            if any(o["paid"] for o in r["after"]):
                tally["paid_since_first_chat"] += 1
        elif r["before"]:
            tally["bought_before_only"] += 1
        seen_types = set()
        for o in r["after"]:
            t = by_type.setdefault(o["type"], {"orders": 0, "paid_orders": 0, "contacts": 0})
            t["orders"] += 1
            t["paid_orders"] += 1 if o["paid"] else 0
            if o["type"] not in seen_types:
                t["contacts"] += 1
                seen_types.add(o["type"])
            if o["paid"]:
                value[o["currency"]] = round(value.get(o["currency"], 0) + o["total"], 2)
    _log.info("ops read: served report %s days=%d offset=%d (%d contacts)", channel, days, offset, len(rows))
    return {"channel": channel, "days": days, "offset": offset, "page": tally,
            "orders_since_first_chat_by_type": by_type, "paid_value_by_currency": value,
            "first_purchase_after_first_chat": lag,
            "orders_neema_created": {"contacts": len({w for w, _s in neema}), "orders": len(neema),
                                     "paid": sum(1 for _w, s in neema if str(s or "").lower() in _PAID)},
            "more": len(rows) == limit}
