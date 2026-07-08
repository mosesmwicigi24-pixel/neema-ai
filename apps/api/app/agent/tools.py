"""Tier 2 agent tools — the actions Neema can take.

Each tool wraps capability we already built for the hub integration, exposed to
the model as a callable. The model decides WHEN to call them; these functions
own the how (server-authoritative pricing, stock, order creation).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import hub_client
from app.core.countries import resolve_country
from app.models.order_event import OrderEvent
from app.models.user import User
from app.services import n8n_bridge as svc
from app.agent import cart as cartmod
from app.agent import memory as memorymod

_log = logging.getLogger("neema.agent")


@dataclass
class ToolContext:
    db: AsyncSession
    redis: object
    wa_id: str
    currency: str = "KES"   # display currency for THIS customer (KES | USD)
    usd_rate: int = 100     # KES per 1 USD (config.usd_kes_rate)


def _display(kes, ctx: "ToolContext"):
    """Convert a KES amount to the customer's display currency. Catalogue/cart
    amounts are stored in KES; Kenyan customers see KES, everyone else sees
    USD = round(KES / rate). Whole-number USD keeps quotes clean."""
    if kes is None:
        return None
    if ctx.currency == "USD":
        try:
            return round(float(kes) / (ctx.usd_rate or 100))
        except (TypeError, ValueError):
            return kes
    return kes


def _to_display(kes, ctx: "ToolContext", price_usd=None):
    """Display price for THIS customer, preferring the hub's own USD price.

    Kenya → raw KES. Everyone else → the product's hub `price_usd` when it's a
    valid positive number, otherwise fall back to KES / rate so a missing/zero
    USD price never surfaces as $0. Catalogue and cart both go through this so
    quotes and totals stay consistent."""
    if ctx.currency != "USD":
        return kes
    try:
        v = float(price_usd)
        if v > 0:
            return round(v)
    except (TypeError, ValueError):
        pass
    return _display(kes, ctx)


# ── Tool schemas (Anthropic format) ──────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "search_catalog",
        "description": "Search the live Bethany House catalogue for products by name, "
                       "category or keyword. Use this before quoting any price or stock — "
                       "never invent products, prices or availability.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What the customer is looking for, e.g. 'cassock', 'communion cups', 'anointing oil'"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_cart",
        "description": "Return the customer's current cart (items, quantities, line and total price).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_cart",
        "description": "Add, set the quantity of, remove, or clear an item in the cart. "
                       "The product must exist in the catalogue (call search_catalog if unsure).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "set", "remove", "clear"]},
                "product": {"type": "string", "description": "Product name or SKU (ignored for clear)"},
                "quantity": {"type": "integer", "description": "Quantity for add/set (default 1)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "create_order",
        "description": "Place the current cart as an order in the hub. Call ONLY after the "
                       "customer has explicitly confirmed they want to order. Returns the order "
                       "number, total, and a secure payment link to give the customer.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_order_status",
        "description": "Look up the live status of the customer's most recent order "
                       "(payment + fulfilment) to answer 'where's my order?'.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "capture_customer",
        "description": "Save details the customer shares (their name and/or delivery location) "
                       "so the order and receipt are correct.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "location": {"type": "string"},
            },
        },
    },
    {
        "name": "add_tags",
        "description": "Tag this customer with short attributes you learn from the chat — "
                       "interests or the products they care about (e.g. 'vestments', "
                       "'communion supplies', 'wholesale', 'clergy'). Helps segment leads. "
                       "1-3 word tags; don't tag their country (that's automatic).",
        "input_schema": {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
            "required": ["tags"],
        },
    },
    {
        "name": "set_lead_source",
        "description": "Record where this customer first heard about us, when it comes up "
                       "naturally (don't interrogate). Use one of: facebook, instagram, tiktok, "
                       "youtube, whatsapp, referral, walk_in, website, google, other.",
        "input_schema": {
            "type": "object",
            "properties": {"source": {"type": "string"}},
            "required": ["source"],
        },
    },
    {
        "name": "remember",
        "description": "Save a durable fact about this customer (a preference, their church, "
                       "size, etc.) so you recall it in future chats. Use sparingly for "
                       "genuinely useful, lasting facts.",
        "input_schema": {
            "type": "object",
            "properties": {"fact": {"type": "string"}},
            "required": ["fact"],
        },
    },
    {
        "name": "handoff_to_human",
        "description": "Escalate to a human agent when the customer asks for one, is upset, or "
                       "needs something you cannot do (refunds, complaints, bespoke requests).",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]


# ── Dispatch ─────────────────────────────────────────────────────────────────

async def run_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    try:
        fn = _HANDLERS.get(name)
        if fn is None:
            return {"error": f"unknown tool {name}"}
        return await fn(args or {}, ctx)
    except Exception as exc:  # tools never crash the loop — the model sees the error
        _log.warning("tool %s failed for %s: %s", name, ctx.wa_id, exc)
        return {"error": str(exc)[:300]}


async def _search_catalog(args: dict, ctx: ToolContext) -> dict:
    query = (args.get("query") or "").lower().strip()
    catalog = await svc.catalog_items(ctx.db, ctx.redis)
    toks = [t for t in query.split() if t]

    def hit(p: dict) -> bool:
        hay = " ".join([p.get("name", ""), p.get("category", ""),
                        " ".join(p.get("aliases") or [])]).lower()
        return all(t in hay for t in toks) if toks else True

    results = [{
        "name": p.get("name"),
        "sku": p.get("sku"),
        "price": _to_display(p.get("price"), ctx, p.get("price_usd")),
        "currency": ctx.currency,
        "in_stock": p.get("in_stock"),
        "available_qty": p.get("available_qty"),
        "category": p.get("category"),
        "made_to_order": p.get("product_type") == "variable" and bool(p.get("is_producible")),
    } for p in catalog if hit(p)][:8]
    return {"count": len(results), "currency": ctx.currency, "results": results}


async def _cart_display(cart: dict, ctx: ToolContext) -> tuple[list, object]:
    """Cart items + total in the customer's display currency, preferring hub USD.

    KES customers get the raw items and cart_total untouched. For USD we map each
    line to its hub `price_usd` (falling back to KES/rate), convert per line, and
    sum the converted lines so the shown total matches the shown unit prices. The
    catalogue is only loaded for the USD path (and it's cached), so the common
    Kenyan turn does no extra work."""
    items = cart.get("items", [])
    if ctx.currency != "USD":
        return list(items), cartmod.cart_total(cart)
    catalog = await svc.catalog_items(ctx.db, ctx.redis)
    usd_by_id = {p.get("hub_product_id"): p.get("price_usd") for p in catalog}
    out, total = [], 0
    for i in items:
        unit = _to_display(i.get("unit_price"), ctx, usd_by_id.get(i.get("hub_product_id")))
        d = dict(i)
        d["unit_price"] = unit
        out.append(d)
        try:
            total += (unit or 0) * int(i.get("qty") or 1)
        except (TypeError, ValueError):
            pass
    return out, total


async def _get_cart(args: dict, ctx: ToolContext) -> dict:
    cart = await cartmod.get_cart(ctx.db, ctx.wa_id)
    items, total = await _cart_display(cart, ctx)
    return {"items": items, "total": total, "currency": ctx.currency}


async def _update_cart(args: dict, ctx: ToolContext) -> dict:
    action = (args.get("action") or "").lower()
    cart = await cartmod.get_cart(ctx.db, ctx.wa_id)
    items = cart["items"]

    if action == "clear":
        cart = await cartmod.clear_cart(ctx.db, ctx.wa_id)
        return {"ok": True, "items": [], "total": 0, "currency": ctx.currency}

    prod = (args.get("product") or "").strip()
    if not prod:
        return {"error": "product is required for add/set/remove"}
    qty = args.get("quantity")
    try:
        qty = max(int(qty), 1) if qty is not None else 1
    except (TypeError, ValueError):
        qty = 1

    catalog = await svc.catalog_items(ctx.db, ctx.redis)
    line = hub_client.resolve_hub_line({"name": prod, "sku": prod, "qty": qty}, catalog)
    if not line and action in ("add", "set"):
        return {"error": f"'{prod}' not found in the catalogue", "suggestion": "call search_catalog"}

    key = (line or {}).get("name") or prod

    def find(name):
        return next((i for i in items if i.get("name", "").lower() == name.lower()), None)

    existing = find(key)
    if action == "remove":
        cart["items"] = [i for i in items if i.get("name", "").lower() != key.lower()]
    elif action in ("add", "set"):
        new_qty = qty if action == "set" else (int(existing["qty"]) + qty if existing else qty)
        cat = next((p for p in catalog if p.get("hub_product_id") == line["product_id"]), {})
        row = {
            "hub_product_id": line["product_id"],
            "name": line["name"],
            "sku": (cat.get("sku") or ""),
            "qty": new_qty,
            "unit_price": line["unit_price"],
            "in_stock": bool(cat.get("in_stock", True)),
            "made_to_order": line.get("product_type") == "variable" and bool(line.get("is_producible")),
        }
        if existing:
            items[items.index(existing)] = row
        else:
            items.append(row)
        cart["items"] = items

    cart = await cartmod.save_cart(ctx.db, ctx.wa_id, cart)
    items, total = await _cart_display(cart, ctx)
    return {"ok": True, "items": items, "total": total, "currency": ctx.currency}


async def _create_order(args: dict, ctx: ToolContext) -> dict:
    cart = await cartmod.get_cart(ctx.db, ctx.wa_id)
    if not cart["items"]:
        return {"error": "cart is empty — add items before creating an order"}

    user = (await ctx.db.execute(select(User).where(User.wa_id == ctx.wa_id))).scalar_one_or_none()
    first_name = ((user.name if user else None) or "WhatsApp Customer").split()[0]
    country_iso = (resolve_country(ctx.wa_id) or {}).get("country_iso")
    catalog = await svc.catalog_items(ctx.db, ctx.redis)

    try:
        pushed = await hub_client.push_pending_order(
            catalog, wa_id=ctx.wa_id, first_name=first_name,
            country_iso=country_iso, items=cart["items"],
        )
    except ValueError as exc:
        return {"error": "none of the cart items could be matched to the hub",
                "unmatched": getattr(exc, "unmatched", [])}

    hub_order_id = pushed.get("order_id")
    payment_url = None
    try:
        payment_url = await hub_client.fetch_payment_link(hub_order_id)
    except Exception as exc:
        _log.warning("payment link fetch failed for order %s: %s", hub_order_id, exc)

    # Persist the order-event with hub linkage (feeds check_order_status + /profile openOrder).
    event_id = f"{ctx.wa_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    ctx.db.add(OrderEvent(
        id=event_id, wa_id=ctx.wa_id, event_type="confirmed",
        items=cart["items"], subtotal=cartmod.cart_total(cart),
        currency=pushed.get("currency_code") or "KES",
        status="pending", channel="whatsapp",
        hub_order_id=hub_order_id, hub_order_number=pushed.get("order_number"),
        hub_currency=pushed.get("currency_code"), hub_total=pushed.get("total_amount"),
        hub_payment_url=payment_url, hub_push_status="pushed",
        hub_pushed_at=datetime.now(timezone.utc),
    ))
    await ctx.db.commit()
    await cartmod.clear_cart(ctx.db, ctx.wa_id)

    return {
        "ok": True,
        "order_number": pushed.get("order_number"),
        "total": pushed.get("total_amount"),
        "currency": pushed.get("currency_code"),
        "payment_url": payment_url,
        "made_to_order_items": [l["name"] for l in pushed.get("production_lines", [])],
        "unmatched": pushed.get("unmatched") or [],
    }


async def _check_order_status(args: dict, ctx: ToolContext) -> dict:
    row = (await ctx.db.execute(
        select(OrderEvent)
        .where(OrderEvent.wa_id == ctx.wa_id, OrderEvent.hub_order_id.isnot(None))
        .order_by(OrderEvent.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if row is None:
        return {"found": False}
    out = {"found": True, "order_number": row.hub_order_number,
           "payment_url": row.hub_payment_url}
    try:
        live = await hub_client.fetch_order_status(row.hub_order_id, ctx.redis)
        if live:
            out.update({k: live.get(k) for k in ("status", "payment_status", "fulfillment_status", "total_amount")})
    except Exception:
        pass
    return out


async def _capture_customer(args: dict, ctx: ToolContext) -> dict:
    user = (await ctx.db.execute(select(User).where(User.wa_id == ctx.wa_id))).scalar_one_or_none()
    if user is None:
        return {"ok": False}
    if args.get("name"):
        user.name = args["name"].strip()
        user.name_confirmed = True
    if args.get("location"):
        user.location = args["location"].strip()
    await ctx.db.commit()
    return {"ok": True, "name": user.name, "location": user.location}


async def _remember(args: dict, ctx: ToolContext) -> dict:
    fact = (args.get("fact") or "").strip()
    if not fact:
        return {"error": "fact is required"}
    facts = await memorymod.add_fact(ctx.db, ctx.wa_id, fact)
    return {"ok": True, "memory": facts}


_SOURCE_ALIASES = {
    "fb": "facebook", "meta": "facebook", "ig": "instagram", "insta": "instagram",
    "tik tok": "tiktok", "tik-tok": "tiktok", "wa": "whatsapp", "friend": "referral",
    "referred": "referral", "walk in": "walk_in", "walkin": "walk_in", "web": "website",
    "yt": "youtube",
}


def _norm_source(s: str) -> str:
    s = (s or "").strip().lower()
    return _SOURCE_ALIASES.get(s, s.replace(" ", "_")) or "other"


async def _set_lead_source(args: dict, ctx: ToolContext) -> dict:
    from sqlalchemy.orm.attributes import flag_modified
    source = _norm_source(args.get("source", ""))
    user = (await ctx.db.execute(select(User).where(User.wa_id == ctx.wa_id))).scalar_one_or_none()
    if user is None:
        return {"ok": False}
    state = dict(user.state or {})
    state["lead_source"] = source
    user.state = state
    flag_modified(user, "state")
    await ctx.db.commit()
    return {"ok": True, "lead_source": source}


async def _add_tags(args: dict, ctx: ToolContext) -> dict:
    from sqlalchemy.orm.attributes import flag_modified
    new_tags = [str(t).strip() for t in (args.get("tags") or []) if str(t).strip()][:10]
    if not new_tags:
        return {"error": "tags is required"}
    user = (await ctx.db.execute(select(User).where(User.wa_id == ctx.wa_id))).scalar_one_or_none()
    if user is None:
        return {"ok": False}
    state = dict(user.state or {})
    tags = list(state.get("tags") or [])
    lower = {t.strip().lower() for t in tags}
    for t in new_tags:
        if t.lower() not in lower:
            tags.append(t)
            lower.add(t.lower())
    state["tags"] = tags[:30]
    user.state = state
    flag_modified(user, "state")
    await ctx.db.commit()
    return {"ok": True, "tags": state["tags"]}


async def _handoff_to_human(args: dict, ctx: ToolContext) -> dict:
    from app.models.conversation import Conversation, InterceptMode
    conv = (await ctx.db.execute(
        select(Conversation).where(Conversation.wa_id == ctx.wa_id)
    )).scalar_one_or_none()
    if conv is None:
        conv = Conversation(wa_id=ctx.wa_id)
        ctx.db.add(conv)
    conv.intercept_mode = InterceptMode.human
    await ctx.db.commit()
    return {"ok": True, "reason": args.get("reason")}


_HANDLERS = {
    "search_catalog": _search_catalog,
    "get_cart": _get_cart,
    "update_cart": _update_cart,
    "create_order": _create_order,
    "check_order_status": _check_order_status,
    "capture_customer": _capture_customer,
    "set_lead_source": _set_lead_source,
    "remember": _remember,
    "add_tags": _add_tags,
    "handoff_to_human": _handoff_to_human,
}
