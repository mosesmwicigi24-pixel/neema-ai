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

from fastapi import APIRouter, Depends, Header, HTTPException, Query
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
