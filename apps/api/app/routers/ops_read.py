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
import re as _re
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


def order_kind(o: dict) -> str:
    """The hub's own channel for an order — till, web, chat — with an invoice
    told apart from a plain quote (both arrive as "quoted")."""
    ch = str(o.get("channel") or o.get("order_type") or "unknown").lower()
    if ch == "quoted":
        return "invoice" if o.get("invoice_number") else "quote"
    return ch


def record_shape(body: dict, into: dict) -> dict:
    """What a hub customer record LOOKS like, so an empty order list is seen
    for what it is (third run, 2026-11-23: 19 customers found, every one with
    an order Neema had created, and not one order read). Field NAMES and
    counts only — never a value."""
    body = body if isinstance(body, dict) else {}
    cust = body.get("customer") if isinstance(body.get("customer"), dict) else {}
    stats = body.get("stats") if isinstance(body.get("stats"), dict) else {}
    into["records"] = into.get("records", 0) + 1
    for label, d in (("top_keys", body), ("customer_keys", cust), ("stats_keys", stats)):
        into[label] = sorted(set(into.get(label, [])) | {str(k)[:40] for k in d})[:60]
    lists = into.setdefault("lists_of_records", {})
    for where, d in (("", body), ("customer.", cust)):
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                lists[where + str(k)[:40]] = lists.get(where + str(k)[:40], 0) + 1
    try:
        counted = int(float(stats.get("total_orders") or 0))
    except (TypeError, ValueError):
        counted = 0
    listed = len(cust.get("orders") or []) if isinstance(cust.get("orders"), list) else 0
    into["stats_say_orders"] = into.get("stats_say_orders", 0) + (1 if counted else 0)
    into["orders_listed"] = into.get("orders_listed", 0) + (1 if listed else 0)
    into["stats_say_orders_but_none_listed"] = (into.get("stats_say_orders_but_none_listed", 0)
                                                + (1 if counted and not listed else 0))
    return into


@router.get("/served")
async def served(request: Request, channel: str = Query("whatsapp", max_length=20),
                 days: int = Query(30, ge=1, le=120),
                 limit: int = Query(60, ge=1, le=100), offset: int = Query(0, ge=0),
                 pause: float = Query(1.0, ge=0.2, le=10.0),
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
    gate = asyncio.Semaphore(1)
    # THE HUB LIMITS HOW FAST IT IS ASKED (second run, 2026-11-23: 867 of 913
    # look-ups answered 429). One at a time, a pause between, and the page
    # STOPS at the first 429: it says how many contacts it finished and how
    # long the hub asked us to wait, and the reader resumes from there. The
    # same hub key serves live customers — the report must never crowd them.
    limited = {"hit": False, "retry_after": None, "limit": None, "remaining": None}
    # WHY A LOOK-UP FAILED IS COUNTED, NEVER SWALLOWED (first run, 2026-11-23:
    # 4 of 909 WhatsApp contacts "found" while 38 of them held orders Neema
    # herself had put in the hub — hub_client's search hides every error as
    # "no such customer"). The search is made here so its outcome is seen.
    import httpx
    probe = {"search_ok": 0, "search_http_error": {}, "search_failed": 0, "no_match_in_results": 0,
             "results_returned": 0, "orders_truncated": 0, "till_sale_without_customer_record": 0}
    base = settings.hub_api_url.rstrip("/")
    has_neema_order = {w for w, _s in neema}
    known = {"contacts_with_a_neema_order": len(has_neema_order), "of_those_found_in_hub": 0}

    async def one(conv_id, wa_id):
        if not is_plausible_phone(wa_id):
            return None
        async with gate:
            if limited["hit"]:
                return "skipped"
            await asyncio.sleep(pause)
            # ONE CALL PER PERSON: the hub's orders-by-phone (2026-11-24). It
            # also finds a till sale where the cashier typed a phone and no
            # customer record was made — the owner's rule exactly ("we
            # capture the same number"). The whole number with its country
            # code is sent: a bare number would be read as Kenyan.
            digits = "".join(ch for ch in str(wa_id) if ch.isdigit())
            # no `since`: an order from BEFORE the first chat tells an existing
            # customer from a new one (the hub sends the newest 50)
            params = {"phone": "+" + digits}
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(f"{base}/api/v1/admin/orders/by-phone",
                                            headers=hub_client._api_headers(), params=params)
                limited["limit"] = resp.headers.get("x-ratelimit-limit") or limited["limit"]
                limited["remaining"] = resp.headers.get("x-ratelimit-remaining") or limited["remaining"]
                if resp.status_code == 429:
                    limited["hit"] = True
                    limited["retry_after"] = resp.headers.get("retry-after")
                    return "skipped"
                if resp.status_code != 200:
                    # 403 = Neema's hub account lacks the Customer History
                    # Reader role; 422 = the hub would not read the number.
                    k = str(resp.status_code)
                    probe["search_http_error"][k] = probe["search_http_error"].get(k, 0) + 1
                    return "error"
                body = resp.json() or {}
            except Exception:
                probe["search_failed"] += 1
                return "error"
            probe["search_ok"] += 1
            custs = [c for c in (body.get("customers") or []) if isinstance(c, dict)]
            orders = [o for o in (body.get("orders") or []) if isinstance(o, dict)]
            probe["results_returned"] += 1 if (custs or orders) else 0
            probe["orders_truncated"] += 1 if body.get("orders_truncated") else 0
            probe["till_sale_without_customer_record"] += (
                1 if any(o.get("customer_id") is None for o in orders) else 0)
            if not custs and not orders:
                return served_reading(firsts.get(conv_id), None)
            summ = {"orders": [dict(hub_client._map_hub_order(o), order_type=order_kind(o))
                               for o in orders]}
        if wa_id in has_neema_order:
            known["of_those_found_in_hub"] += 1
        return served_reading(firsts.get(conv_id), summ)

    results = []
    for cid, wa in rows:                      # in order, so "finished" is a clean offset
        r = await one(cid, wa)
        if r == "skipped":
            break
        results.append(r)
    finished = len(results)
    tally = {"contacts": finished, "no_number_saved": 0, "hub_error": 0, "in_hub": 0,
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
            "hub_lookup": probe, "check_known_customers": known, 
            "orders_neema_created": {"contacts": len({w for w, _s in neema}), "orders": len(neema),
                                     "paid": sum(1 for _w, s in neema if str(s or "").lower() in _PAID)},
            "finished": finished, "rate_limit": limited,
            "more": len(rows) == limit or finished < len(rows)}


# ── where the unpaid chat orders stopped (owner, 2026-11-24) ─────────────────
# 77 chat orders in the hub, 1 marked paid. For each order Neema put in the
# hub that is not paid, the thread AFTER the order is read on the server and
# only the tally leaves: no name, no number, no message text.
_SAYS_PAID = _re.compile(
    r"\b(i\s*(have|'ve)?\s*(paid|sent)|payment\s+(made|done|sent)|paid\b|nimelipa|nimetuma|"
    r"nishalipa|nimeshalipa|transaction|confirmation\s+code|receipt|j'ai\s+pay[ée]|pagu[ée]|pago\s+hecho)", _re.I)
_ASKS_HOW = _re.compile(
    r"(how\s+(do|can|to)\s+i?\s*pay|payment\s+(details|number|method|link)|till\s+number|paybill|"
    r"account\s+(number|details)|bank\s+details|western\s+union|mukuru|moneygram|world\s*remit|"
    r"mobile\s+money|momo|send\s+(the\s+)?money|where\s+(do|to)\s+i\s+(pay|send)|nilipe|nitume|"
    r"comment\s+payer|c[oó]mo\s+pag)", _re.I)
_COLLEAGUE = _re.compile(r"\b(colleague|a\s+member\s+of\s+(our|the)\s+team|team\s+will|mwenzangu)\b", _re.I)


def stall_reading(order_at, msgs: list) -> dict:
    """Where one unpaid order stopped. `msgs` is the thread oldest-first as
    (when, sender, text, is_note). One reason per order, the most actionable
    first. Pure."""
    t0 = _when(order_at)
    after = [m for m in msgs if not m[3] and t0 is not None and _when(m[0]) is not None
             and _when(m[0]) >= t0]
    cust = [m for m in after if m[1] == "user"]
    staff = [m for m in after if m[1] == "human_agent"]
    ours = [m for m in after if m[1] in ("ai", "human_agent")]
    said_paid = any(_SAYS_PAID.search(m[2] or "") for m in cust)
    asked_how = any(_ASKS_HOW.search(m[2] or "") for m in cust)
    promised = [m for m in after if m[1] == "ai" and _COLLEAGUE.search(m[2] or "")]
    staff_after_promise = bool(promised) and any(
        _when(s[0]) > _when(promised[0][0]) for s in staff)
    last = after[-1][1] if after else None
    if said_paid:
        reason = "customer_says_paid_order_still_unpaid"
    elif last == "user":
        reason = "customer_wrote_last_no_reply"
    elif promised and not staff_after_promise:
        reason = "colleague_promised_none_came"
    elif asked_how:
        reason = "asked_how_to_pay_then_stopped"
    elif not cust:
        reason = "customer_silent_since_order"
    else:
        reason = "talked_on_then_went_quiet"
    return {"reason": reason, "customer_messages_after": len(cust),
            "staff_replied_after": bool(staff), "we_wrote_after": bool(ours),
            "colleague_promised": bool(promised), "asked_how_to_pay": asked_how}


@router.get("/orders/stalled")
async def orders_stalled(channel: str = Query("", max_length=20),
                         days: int = Query(30, ge=1, le=120),
                         db: AsyncSession = Depends(get_db),
                         _: None = Depends(require_key)) -> dict:
    """Counts only: of the orders Neema put in the hub in the last `days`,
    how many are unpaid and where each one's conversation stopped."""
    from datetime import datetime, timedelta, timezone
    from app.models.order_event import OrderEvent
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = select(OrderEvent).where(OrderEvent.hub_order_id.isnot(None), OrderEvent.created_at >= since)
    if channel:
        q = q.where(OrderEvent.channel == channel)
    orders = (await db.execute(q.order_by(OrderEvent.created_at.asc()))).scalars().all()
    now = datetime.now(timezone.utc)
    out = {"orders": len(orders), "paid": 0, "unpaid": 0, "no_conversation_found": 0,
           "reasons": {}, "by_channel": {}, "hub_status": {}, "currency": {},
           "unpaid_value_by_currency": {}, "had_payment_link": 0, "staff_replied_after": 0,
           "colleague_promised": 0, "asked_how_to_pay": 0, "customer_never_wrote_again": 0,
           "order_age": {"under_2_days": 0, "2_to_7_days": 0, "over_7_days": 0},
           "hub_status_never_updated": 0}
    for oe in orders:
        if str(oe.hub_payment_status or oe.payment_status or "").lower() in _PAID:
            out["paid"] += 1
            continue
        out["unpaid"] += 1
        ch = oe.channel or "whatsapp"
        out["by_channel"][ch] = out["by_channel"].get(ch, 0) + 1
        hs = str(oe.hub_status or "not_reported").lower()
        out["hub_status"][hs] = out["hub_status"].get(hs, 0) + 1
        out["hub_status_never_updated"] += 0 if oe.hub_status_at else 1
        cur = str(oe.hub_currency or oe.currency or "?").upper()
        out["currency"][cur] = out["currency"].get(cur, 0) + 1
        try:
            amt = float(oe.hub_total if oe.hub_total is not None else oe.subtotal or 0)
        except (TypeError, ValueError):
            amt = 0.0
        out["unpaid_value_by_currency"][cur] = round(out["unpaid_value_by_currency"].get(cur, 0) + amt, 2)
        out["had_payment_link"] += 1 if (oe.hub_payment_url or oe.hub_public_url) else 0
        made = _when(oe.created_at)
        age = (now - made).days if made else 0
        out["order_age"]["under_2_days" if age < 2 else "2_to_7_days" if age <= 7 else "over_7_days"] += 1
        cq = select(Conversation.id).where(Conversation.channel == ch)
        if oe.person_id is not None:
            cq = cq.where(or_(Conversation.person_id == oe.person_id, Conversation.wa_id == oe.wa_id,
                              Conversation.external_id == oe.wa_id))
        else:
            cq = cq.where(or_(Conversation.wa_id == oe.wa_id, Conversation.external_id == oe.wa_id))
        cid = (await db.execute(cq.order_by(Conversation.last_message_at.desc().nullslast()).limit(1))).scalar()
        if cid is None:
            out["no_conversation_found"] += 1
            continue
        rows = (await db.execute(
            select(Message.created_at, Message.sender, Message.text, Message.raw_meta)
            .where(Message.conversation_id == cid, Message.created_at >= oe.created_at)
            .order_by(Message.created_at.asc()).limit(400))).all()
        msgs = [(r[0], getattr(r[1], "value", str(r[1])), r[2] or "",
                 isinstance(r[3], dict) and r[3].get("kind") == "note") for r in rows]
        r = stall_reading(oe.created_at, msgs)
        out["reasons"][r["reason"]] = out["reasons"].get(r["reason"], 0) + 1
        out["staff_replied_after"] += 1 if r["staff_replied_after"] else 0
        out["colleague_promised"] += 1 if r["colleague_promised"] else 0
        out["asked_how_to_pay"] += 1 if r["asked_how_to_pay"] else 0
        out["customer_never_wrote_again"] += 1 if not r["customer_messages_after"] else 0
    _log.info("ops read: stalled orders days=%d (%d orders)", days, len(orders))
    return out


@router.get("/outage")
async def outage(_: None = Depends(require_key)) -> dict:
    """Counts only: the comments the credit outage left with a set reply —
    how many are still to be picked up, how many are owed, with staff or
    answered, and what was left alone and why. No name, number or text."""
    from app.services import outage_backfill
    _log.info("ops read: outage counts")
    return await outage_backfill.counts()
