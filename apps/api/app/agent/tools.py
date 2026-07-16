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
from app.core.config import settings
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
    channel: str = "whatsapp"  # source channel (whatsapp | messenger | instagram)


def _display(kes, ctx: "ToolContext"):
    """Convert a KES amount to the customer's display currency. Catalogue/cart
    amounts are stored in KES; Kenyan customers see KES, everyone else sees
    USD = round(KES / rate). Whole-number USD keeps quotes clean — but small
    items (communion cups, wafers) keep cents: whole-dollar rounding floored a
    real KES price to '$0' and the agent told a customer cups were free."""
    if kes is None:
        return None
    if ctx.currency == "USD":
        try:
            usd = float(kes) / (ctx.usd_rate or 100)
        except (TypeError, ValueError):
            return kes
        if usd <= 0:
            return 0
        return round(usd) if usd >= 1 else max(round(usd, 2), 0.01)
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
            return round(v) if v >= 1 else round(v, 2)   # cents for small items, never $0
    except (TypeError, ValueError):
        pass
    return _display(kes, ctx)


# ── Tool schemas (Anthropic format) ──────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "search_catalog",
        "description": "Search the live Bethany House catalogue for products by name, "
                       "category or keyword. Use this before quoting any price — "
                       "never invent products, prices or availability. Some products "
                       "return a `variants` list (size/colour, each with its OWN price): "
                       "quote the variant the customer picks, or give the `price_range` "
                       "and ask which one — never a single flat price for a varied item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What the customer is looking for, e.g. 'cassock', 'communion cups', 'anointing oil'"},
                "currency": {"type": "string", "enum": ["KES", "USD"],
                             "description": "Override the display currency: set 'KES' when the customer says they are in Kenya or asks for Kenyan shillings (our native prices); otherwise leave unset."},
            },
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
                "product": {"type": "string", "description": "Product name or SKU (ignored for clear). "
                            "For a product with variants, pass the chosen variant's SKU (e.g. "
                            "'COM-T-001-L-GOL') so the cart is priced for that exact size/colour."},
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
    {
        "name": "whatsapp_checkout_link",
        "description": "Give a Messenger/Instagram customer a ONE-TAP WhatsApp link to finish "
                       "their order — checkout and payment happen on WhatsApp. Use this the "
                       "moment they show buying intent ('how do I pay', 'I'll take it', a clear "
                       "yes). Pass a SHORT product summary (a few words, never the full order "
                       "breakdown); share the returned tiny link exactly as given.",
        "input_schema": {
            "type": "object",
            "properties": {"product": {"type": "string",
                                       "description": "SHORT product summary to pre-fill, max ~8 words, "
                                                      "e.g. 'white cassock full set'"}},
            "required": [],
        },
    },
    {
        "name": "capture_contact",
        "description": "Save a Messenger/Instagram customer's details to their profile: name, "
                       "phone, and city/country. We CANNOT read Messenger names automatically, so "
                       "when someone new starts chatting, warmly ask their name (and city & "
                       "country for delivery) and call this. If they give a phone/WhatsApp "
                       "number, pass it too — it links their Messenger and WhatsApp into one customer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "the customer's name"},
                "phone": {"type": "string", "description": "phone/WhatsApp number if they shared it"},
                "location": {"type": "string", "description": "city and/or country, e.g. 'Kampala, Uganda'"},
            },
            "required": [],
        },
    },
    {
        "name": "pause_conversation",
        "description": "Pause this conversation for 2 hours. Use ONLY after ~3 consecutive "
                       "customer turns that stay outside Bethany House business (legal advice, "
                       "ministry counselling, off-topic chat) despite gentle redirection — send "
                       "one brief kind closing line, then call this. Never use it on a buying "
                       "customer, a complaint, or an open order.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "share_catalog",
        "description": "Share a link to our online catalog so the customer can SEE product "
                       "photos, prices and details and order in one tap. Use when they ask to "
                       "see products, ask 'do you have photos', want to browse, or you're "
                       "describing an item that has a picture. Pass the product name to link "
                       "straight to that item; omit it to share the whole catalog.",
        "input_schema": {
            "type": "object",
            "properties": {"product": {"type": "string",
                                       "description": "a specific product to link to, e.g. 'black cassock'; omit for the full catalog"}},
            "required": [],
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
    # A customer can tell us where they are mid-conversation ("Kenyan money plz")
    # — the model then re-fetches with currency="KES"/"USD" instead of being
    # trapped by the channel default (Meta defaults to USD).
    cur = (args.get("currency") or "").upper()
    if cur in ("KES", "USD") and cur != ctx.currency:
        from dataclasses import replace as _dc_replace
        ctx = _dc_replace(ctx, currency=cur)
    query = (args.get("query") or "").lower().strip()
    catalog = await svc.catalog_items(ctx.db, ctx.redis)
    toks = [t for t in query.split() if t]

    def _hay(p: dict) -> str:
        return " ".join([p.get("name", ""), p.get("category", ""),
                         " ".join(p.get("aliases") or [])]).lower()

    def hit(p: dict) -> bool:
        return all(t in _hay(p) for t in toks) if toks else True

    matched = [p for p in catalog if hit(p)]
    if not matched and len(toks) > 1:
        # All-token match found nothing ("clerical shirt", "cassock set") — fall
        # back to any-token so the model gets candidates instead of a dead end,
        # best matches (most tokens hit) first.
        scored = [(sum(t in _hay(p) for t in toks), p) for p in catalog]
        matched = [p for s, p in sorted(scored, key=lambda x: -x[0]) if s > 0]

    results = []
    for p in matched:
        mto = p.get("product_type") == "variable" and bool(p.get("is_producible"))
        row = {
            "name": p.get("name"),
            "sku": p.get("sku"),
            "category": p.get("category"),
            "made_to_order": mto,
            # Stock is an internal SOURCING concern, never a sales answer: the
            # business produces and sources on demand, so every item is sold as
            # available and no counts are ever exposed to the model. A hub
            # shortfall is flagged to the team at order time (_sourcing_gaps).
            "availability": "available",
        }
        row["price"] = _to_display(p.get("price"), ctx, p.get("price_usd"))
        row["currency"] = ctx.currency
        # Variants each carry their OWN price (a Thurible in S ≠ L). Surface them
        # so the agent quotes the exact size/colour the customer wants — and a
        # price range when they haven't chosen yet — instead of one flat number.
        variants = p.get("variants") or []
        if variants:
            row["variants"] = [
                {"options": v.get("attributes") or v.get("name"),
                 "sku": v.get("sku"),
                 "price": _to_display(v.get("price_kes"), ctx, v.get("price_usd"))}
                for v in variants
            ]
            prices = [vr["price"] for vr in row["variants"] if isinstance(vr["price"], (int, float))]
            if prices and min(prices) != max(prices):
                row["price_range"] = {"from": min(prices), "to": max(prices)}
                row["price_note"] = ("price depends on the variant — quote the one the "
                                     "customer picks, or give the range and ask")
        results.append(row)
        if len(results) >= 8:
            break
    return {"count": len(results), "currency": ctx.currency, "results": results}


async def _cart_display(cart: dict, ctx: ToolContext) -> tuple[list, object]:
    """Cart items + total in the customer's display currency, preferring hub USD.

    KES customers get the raw items and cart_total untouched. For USD we map each
    line to its hub `price_usd` (falling back to KES/rate), convert per line, and
    sum the converted lines so the shown total matches the shown unit prices. The
    catalogue is only loaded for the USD path (and it's cached), so the common
    Kenyan turn does no extra work."""
    # `in_stock`/`price_usd` on a cart line are internal bookkeeping — never shown
    # to the model (in_stock feeds the sourcing flag; price_usd feeds USD display).
    _hidden = ("in_stock", "price_usd")
    items = [{k: v for k, v in i.items() if k not in _hidden} for i in cart.get("items", [])]
    raw = cart.get("items", [])
    if ctx.currency != "USD":
        return items, cartmod.cart_total(cart)
    catalog = await svc.catalog_items(ctx.db, ctx.redis)
    usd_by_id = {p.get("hub_product_id"): p.get("price_usd") for p in catalog}
    out, total = [], 0
    for i, r in zip(items, raw):
        # Prefer the line's OWN usd (a variant's price) over the product default.
        line_usd = r.get("price_usd") or usd_by_id.get(i.get("hub_product_id"))
        unit = _to_display(i.get("unit_price"), ctx, line_usd)
        d = dict(i)
        d["unit_price"] = unit
        out.append(d)
        try:
            total += (unit or 0) * int(i.get("qty") or 1)
        except (TypeError, ValueError):
            pass
    return out, total


async def _get_cart(args: dict, ctx: ToolContext) -> dict:
    cart = await cartmod.get_cart(ctx.db, ctx.wa_id, ctx.channel)
    items, total = await _cart_display(cart, ctx)
    return {"items": items, "total": total, "currency": ctx.currency}


async def _update_cart(args: dict, ctx: ToolContext) -> dict:
    action = (args.get("action") or "").lower()
    cart = await cartmod.get_cart(ctx.db, ctx.wa_id, ctx.channel)
    items = cart["items"]

    if action == "clear":
        cart = await cartmod.clear_cart(ctx.db, ctx.wa_id, ctx.channel)
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
            # Store the VARIANT sku when this line is a variant, so order-time
            # re-resolution finds the exact variant (its price + variant_id) and
            # the order total matches what was quoted.
            "sku": (line.get("variant_sku") or cat.get("sku") or ""),
            "qty": new_qty,
            "unit_price": line["unit_price"],
            "price_usd": line.get("unit_price_usd"),   # variant's own USD (for USD display)
            "in_stock": bool(cat.get("in_stock", True)),
            "made_to_order": line.get("product_type") == "variable" and bool(line.get("is_producible")),
        }
        if existing:
            items[items.index(existing)] = row
        else:
            items.append(row)
        cart["items"] = items

    cart = await cartmod.save_cart(ctx.db, ctx.wa_id, cart, ctx.channel)
    items, total = await _cart_display(cart, ctx)
    return {"ok": True, "items": items, "total": total, "currency": ctx.currency}


def _sourcing_gaps(cart_items: list, catalog: list) -> list[str]:
    """Lines the hub can't currently cover (out of stock, or fewer than ordered).
    The customer is NEVER told — these become a team flag so the item is sourced
    before delivery/pickup. Made-to-order lines are produced, never a gap."""
    by_id = {p.get("hub_product_id"): p for p in catalog}
    gaps = []
    for i in cart_items:
        p = by_id.get(i.get("hub_product_id"))
        if not p:
            continue
        if p.get("product_type") == "variable" and bool(p.get("is_producible")):
            continue
        try:
            qty = max(int(i.get("qty") or 1), 1)
        except (TypeError, ValueError):
            qty = 1
        avail = p.get("available_qty")
        try:
            avail = int(avail) if avail is not None else None
        except (TypeError, ValueError):
            avail = None
        if not p.get("in_stock", True):
            gaps.append(f"{i.get('name')} ×{qty} (hub: out of stock)")
        elif avail is not None and avail < qty:
            gaps.append(f"{i.get('name')} ×{qty} (hub: only {avail} on hand)")
    return gaps


async def _order_identity(ctx: ToolContext):
    """(phone, first_name, person_id) to bill this order to. WhatsApp IS the
    phone. A Meta customer has only a page-scoped PSID — never a phone — so we
    use the number they shared (capture_contact stored it on their person).
    Returns phone=None when we don't have one yet: the order CANNOT be created,
    because a PSID as the hub's customer phone is exactly the phantom-contact bug."""
    if ctx.channel == "whatsapp":
        user = (await ctx.db.execute(
            select(User).where(User.wa_id == ctx.wa_id))).scalar_one_or_none()
        name = ((user.name if user else None) or "WhatsApp Customer").split()[0]
        return ctx.wa_id, name, (user.person_id if user else None)

    from app.models.person import Person, Identity, Identifier
    name, phone = "Customer", None
    ident = (await ctx.db.execute(select(Identity).where(
        Identity.channel == ctx.channel,
        Identity.external_id == ctx.wa_id))).scalar_one_or_none()
    if ident is None:
        return None, name, None
    person = await ctx.db.get(Person, ident.person_id)
    if person is not None and person.display_name:
        name = person.display_name.split()[0]
    ph = (await ctx.db.execute(select(Identifier).where(
        Identifier.person_id == ident.person_id,
        Identifier.type == "phone"))).scalars().first()
    if ph and ph.value:
        phone = ph.value.lstrip("+")
    else:
        u = (await ctx.db.execute(select(User).where(
            User.person_id == ident.person_id))).scalar_one_or_none()
        if u is not None and u.phone:
            phone = u.phone.lstrip("+")
        if u is not None and u.name and name == "Customer":
            name = u.name.split()[0]
    return phone, name, ident.person_id


async def _create_order(args: dict, ctx: ToolContext) -> dict:
    cart = await cartmod.get_cart(ctx.db, ctx.wa_id, ctx.channel)
    if not cart["items"]:
        return {"error": "cart is empty — add items before creating an order"}

    # Every order — WhatsApp, Messenger or Instagram — is billed to a real phone
    # and lands in the hub's WhatsApp Orders. No phone, no order.
    order_wa_id, first_name, order_person_id = await _order_identity(ctx)
    if not order_wa_id:
        return {"error": "no phone number for this customer yet",
                "next_step": "Warmly ask for their WhatsApp/phone number (for the order "
                             "confirmation and delivery), save it with capture_contact, "
                             "then call create_order again."}

    country_iso = (resolve_country(order_wa_id) or {}).get("country_iso")
    catalog = await svc.catalog_items(ctx.db, ctx.redis)

    try:
        pushed = await hub_client.push_pending_order(
            catalog, wa_id=order_wa_id, first_name=first_name,
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

    # A hub shortfall never reaches the customer — it becomes a SOURCING flag in
    # the Activity log so the team buys/produces it before delivery or pickup.
    gaps = _sourcing_gaps(cart["items"], catalog)
    if gaps:
        try:
            from sqlalchemy import or_
            from app.models.conversation import Conversation
            from app.models.intercept import Intercept, InterceptAction
            conv = (await ctx.db.execute(select(Conversation).where(
                Conversation.channel == ctx.channel,
                or_(Conversation.external_id == ctx.wa_id,
                    Conversation.wa_id == ctx.wa_id)))).scalars().first()
            if conv is not None:
                ctx.db.add(Intercept(
                    conversation_id=conv.id, action=InterceptAction.flag,
                    note=f"SOURCING NEEDED — order {pushed.get('order_number') or hub_order_id}: "
                         + "; ".join(gaps)
                         + ". Customer was told it's available; please source before "
                           "delivery/pickup."))
        except Exception:
            _log.warning("sourcing flag failed for order %s", hub_order_id, exc_info=True)

    # Persist the order-event with hub linkage (feeds check_order_status + /profile
    # openOrder). Keyed on the PHONE (so a Messenger buyer's order is found again
    # on WhatsApp — one customer), tagged with the channel that actually sold it.
    event_id = f"{order_wa_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    ctx.db.add(OrderEvent(
        id=event_id, wa_id=order_wa_id, event_type="confirmed",
        person_id=order_person_id,
        items=cart["items"], subtotal=cartmod.cart_total(cart),
        currency=pushed.get("currency_code") or "KES",
        status="pending", channel=ctx.channel,
        hub_order_id=hub_order_id, hub_order_number=pushed.get("order_number"),
        hub_currency=pushed.get("currency_code"), hub_total=pushed.get("total_amount"),
        hub_payment_url=payment_url, hub_push_status="pushed",
        hub_pushed_at=datetime.now(timezone.utc),
    ))
    await ctx.db.commit()
    await cartmod.clear_cart(ctx.db, ctx.wa_id, ctx.channel)

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
    # Orders are keyed on the customer's PHONE and stamped with their person — a
    # Messenger/IG buyer's handle is a PSID, so look them up by either, or their
    # own order comes back "not found".
    from sqlalchemy import or_
    phone, _name, person_id = await _order_identity(ctx)
    conds = []
    if person_id is not None:
        conds.append(OrderEvent.person_id == person_id)
    if phone:
        conds.append(OrderEvent.wa_id == phone)
    if not conds:
        return {"found": False}
    row = (await ctx.db.execute(
        select(OrderEvent)
        .where(or_(*conds), OrderEvent.hub_order_id.isnot(None))
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


async def _capture_contact(args: dict, ctx: ToolContext) -> dict:
    """Messenger/IG: save the customer's name (Meta blocks reading it) and, if they
    share a phone, attach it and LINK their Messenger↔WhatsApp into one person."""
    from app.services.identity import _select_identity, resolve_or_create_person, WHATSAPP
    from app.models.person import Person
    name = (args.get("name") or "").strip()
    phone = (args.get("phone") or "").strip()
    location = (args.get("location") or "").strip()

    ident = await _select_identity(ctx.db, ctx.channel, ctx.wa_id)
    if ident is None:
        ident = await resolve_or_create_person(ctx.db, ctx.channel, ctx.wa_id,
                                               source=f"{ctx.channel}_capture")
    out = {"ok": True}
    person = await ctx.db.get(Person, ident.person_id)

    if name:
        # Fuller name wins everywhere: a self-stated "Meshack" must never shadow
        # the profile's "Meshack Munyao" — and a fuller self-stated name upgrades
        # a partial one. All three stores end up showing the SAME name.
        full = name[:200]
        for existing in ((ident.display_name or ""),
                         ((person.display_name or "") if person is not None else "")):
            e = existing.strip()
            if e and full.lower() in e.lower() and len(e) > len(full):
                full = e
        ident.display_name = full
        if person is not None:
            person.display_name = full
        _u = (await ctx.db.execute(
            select(User).where(User.person_id == ident.person_id))).scalar_one_or_none()
        if _u is not None:
            cur = (_u.name or "").strip()
            if not cur or (cur.lower() in full.lower() and len(full) > len(cur)):
                _u.name = full[:100]              # the CRM panel reads user.name
        out["name"] = full

    if location and person is not None:
        from sqlalchemy.orm.attributes import flag_modified
        from app.core.countries import iso_from_text as _iso_txt, name_for_iso, flag_url_for
        state = dict(person.state or {})
        state["location"] = location[:200]
        loc_iso = _iso_txt(location)
        if loc_iso:
            # Country derived from what THEY said — fills the profile (a later
            # shared phone prefix, a stronger signal, may overwrite it).
            state["country_iso"] = loc_iso
            state["country"] = name_for_iso(loc_iso)
            state["flag_url"] = flag_url_for(loc_iso)
            _shim = (await ctx.db.execute(
                select(User).where(User.person_id == ident.person_id))).scalar_one_or_none()
            if _shim is not None and not _shim.country_iso:
                _shim.country_iso = loc_iso
                _shim.country = state["country"]
                _shim.flag_url = state["flag_url"]
            out["country"] = state["country"]
        person.state = state
        flag_modified(person, "state")
        out["location"] = location
        # "Kenya money" case: the moment their location resolves to Kenya, this
        # very turn switches to the Kenyan market — the next search_catalog call
        # returns real KES catalogue prices (never a USD conversion).
        from app.core.countries import iso_from_text
        if iso_from_text(location) == "KE" and ctx.currency != "KES":
            ctx.currency = "KES"
            out["currency_now"] = "KES"
            out["note"] = ("Customer is in Kenya — re-run search_catalog and quote "
                           "the real KES catalogue prices; do NOT convert from USD.")

    if phone:
        from app.core.countries import iso_from_text
        from app.core.phone import to_e164
        from app.services.reconcile import attach_identifier
        # A number shared without a country code ("0799223329") must be resolved
        # against THEIR country, not Kenya's — we know it from their captured
        # location (this turn's or the profile's).
        _user = (await ctx.db.execute(
            select(User).where(User.person_id == ident.person_id))).scalar_one_or_none()
        region = (iso_from_text(location)
                  or iso_from_text((person.state or {}).get("location") if person else None)
                  or iso_from_text(_user.location if _user else None)   # panel-edited location
                  or "KE")
        e164 = to_e164(phone, region)
        if e164:
            await attach_identifier(ctx.db, ident.person_id, "phone", e164,
                                    source=f"{ctx.channel}_capture", confidence="self_reported")
            # Link to the WhatsApp person for that number, if one exists — keep the
            # phone-anchored WhatsApp person as primary (it can transact + be paid).
            wa_ident = await _select_identity(ctx.db, WHATSAPP, e164.lstrip("+"))
            if wa_ident is not None and wa_ident.person_id != ident.person_id:
                from app.services.merge import merge_persons
                try:
                    await merge_persons(ctx.db, primary_person_id=wa_ident.person_id,
                                        secondary_person_id=ident.person_id,
                                        primary_wa_id=e164.lstrip("+"))
                    out["linked_whatsapp"] = True
                except Exception as exc:
                    _log.warning("capture_contact link failed for %s: %s", ctx.wa_id, exc)
            # The phone becomes the customer's primary contact identity: show it
            # on their profile (the shim User row), keeping the Messenger id
            # linked so future DMs still resolve to the same customer.
            user = (await ctx.db.execute(
                select(User).where(User.person_id == ident.person_id))).scalar_one_or_none()
            if user is not None and not user.phone:
                user.phone = e164
            # The dialing prefix is the strongest country signal — set the
            # profile's country from it (overwrites a location-derived guess).
            loc = resolve_country(e164)
            if loc.get("country_iso"):
                if person is not None:
                    from sqlalchemy.orm.attributes import flag_modified as _fm
                    st = dict(person.state or {})
                    st.update({"country_iso": loc["country_iso"],
                               "country": loc["country"], "flag_url": loc["flag_url"]})
                    person.state = st
                    _fm(person, "state")
                if user is not None:
                    user.country_iso = loc["country_iso"]
                    user.country = loc["country"]
                    user.flag_url = loc["flag_url"]
                out["country"] = loc["country"]
            out["phone"] = e164

    await ctx.db.commit()
    return out


async def _remember(args: dict, ctx: ToolContext) -> dict:
    fact = (args.get("fact") or "").strip()
    if not fact:
        return {"error": "fact is required"}
    facts = await memorymod.add_fact(ctx.db, ctx.wa_id, fact, channel=ctx.channel)
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
    """Route this conversation to a person. Channel-aware: a Meta contact's handle
    is a page-scoped PSID, so we match on (channel, external_id) — never mint a
    Conversation with a PSID in wa_id, which is how phantom contacts were born."""
    from sqlalchemy import or_
    from app.models.conversation import Conversation, InterceptMode
    conv = (await ctx.db.execute(select(Conversation).where(
        Conversation.channel == ctx.channel,
        or_(Conversation.external_id == ctx.wa_id, Conversation.wa_id == ctx.wa_id),
    ))).scalars().first()
    if conv is None and ctx.channel == "whatsapp":
        conv = Conversation(wa_id=ctx.wa_id, channel="whatsapp", external_id=ctx.wa_id)
        ctx.db.add(conv)
    if conv is None:                      # Meta thread we can't find — never invent one
        _log.warning("handoff: no %s conversation for %s", ctx.channel, ctx.wa_id)
        return {"ok": False, "reason": args.get("reason"),
                "note": "conversation not found — tell the customer a colleague will follow up"}
    conv.intercept_mode = InterceptMode.human
    await ctx.db.commit()
    return {"ok": True, "reason": args.get("reason")}


async def _resolve_cart_items(product: str, ctx: ToolContext) -> list[dict]:
    """The product the customer agreed to, as a REAL cart line (hub product id,
    variant SKU, hub price) — never free text. Empty when it can't be matched."""
    if not product:
        return []
    try:
        catalog = await svc.catalog_items(ctx.db, ctx.redis)
        line = hub_client.resolve_hub_line({"name": product, "sku": product, "qty": 1}, catalog)
    except Exception:
        return []
    if not line:
        return []
    return [{
        "hub_product_id": line["product_id"],
        "name":           line["name"],
        "sku":            line.get("variant_sku") or "",
        "qty":            line["quantity"],
        "unit_price":     line["unit_price"],
        "made_to_order":  bool(line.get("is_producible")),
    }]


async def _whatsapp_checkout_link(args: dict, ctx: ToolContext) -> dict:
    """A TINY tap-to-order link that opens WhatsApp with the order READY — not
    order details typed into a message.

    The item is resolved to a real CART LINE here (hub product id + variant SKU +
    hub price) and stored with the ref. When the customer lands on WhatsApp, that
    ref rebuilds their cart server-side (reconcile_waref), so Neema confirms and
    pushes a proper order to the hub — no re-parsing text, no lost details.

    Returns our own short URL (…/api/o/{ref}) that 302-redirects to the wa.me
    target; falls back to the raw wa.me link when no public host is configured
    (or redis is down, so nothing is lost)."""
    import secrets
    from urllib.parse import quote
    num = (settings.whatsapp_handoff_number or "").lstrip("+").strip()
    if not num:
        return {"error": "WhatsApp checkout number not configured"}
    product = " ".join((args.get("product") or "").split())
    hint = product[:80].strip()                  # short opener, never the full breakdown
    ref = secrets.token_hex(3).upper()          # e.g. '9F2A7C'
    body = (f"Hi Bethany House! I'd like to order {hint}. (ref {ref})"
            if hint else f"Hi Bethany House! I'd like to order. (ref {ref})")
    target = f"https://wa.me/{num}?text={quote(body)}"
    # Carry the WHOLE cart they built, not just the one named item — so the
    # fallback WhatsApp handover rebuilds the complete order, nothing dropped.
    cart = await cartmod.get_cart(ctx.db, ctx.wa_id, ctx.channel)
    items = cart.get("items") or await _resolve_cart_items(product, ctx)
    stored = False
    try:
        if ctx.redis is not None:
            await ctx.redis.set(
                f"waref:{ref}",
                json.dumps({"channel": ctx.channel, "external_id": ctx.wa_id,
                            "target": target, "product": product[:200],
                            "items": items}),
                ex=14 * 24 * 3600,
            )
            stored = True
    except Exception:
        pass                                     # attribution is best-effort
    base = (settings.media_public_url or "").rstrip("/")
    link = f"{base}/api/o/{ref}" if (base and stored) else target
    return {"link": link, "ref": ref, "cart_prepared": bool(items),
            "note": "Share this exact short link — one tap opens WhatsApp with their "
                    "cart already built, ready to confirm and pay."}


async def _customer_currency(ctx: ToolContext) -> str:
    """This customer's own currency for the shared catalog: Kenya → KES, Zambia
    → ZMW, etc., from their phone prefix (WhatsApp) or captured country (Meta).
    USD for anyone we can't place. The catalog shows their currency where the
    hub prices it, else USD."""
    from app.core.countries import currency_for_country, iso_from_text
    iso = None
    if ctx.channel == "whatsapp":
        iso = (resolve_country(ctx.wa_id) or {}).get("country_iso")
    else:
        try:
            from app.models.person import Identity, Person
            ident = (await ctx.db.execute(select(Identity).where(
                Identity.channel == ctx.channel,
                Identity.external_id == ctx.wa_id))).scalar_one_or_none()
            if ident is not None:
                person = await ctx.db.get(Person, ident.person_id)
                st = (person.state or {}) if person else {}
                iso = st.get("country_iso") or iso_from_text(st.get("location"))
        except Exception:
            pass
    if iso:
        return currency_for_country(iso)
    return "KES" if ctx.currency == "KES" else "USD"


async def _share_catalog(args: dict, ctx: ToolContext) -> dict:
    """Return a shareable catalog link — the whole storefront, or a deep link to
    one product when named. The link carries the customer's currency so they see
    prices in their own money (KES / USD / ZMW …). Photos + prices, order in a tap."""
    base = (settings.media_public_url or "").rstrip("/")
    if not base:
        return {"error": "catalog URL not configured"}
    ccy = await _customer_currency(ctx)
    q = f"?ccy={ccy}"
    product = (args.get("product") or "").strip()
    if not product:
        return {"link": f"{base}/catalog{q}",
                "note": f"Share this so the customer can browse our products with photos "
                        f"and prices (shown in {ccy})."}

    catalog = await svc.catalog_items(ctx.db, ctx.redis)
    pn = product.lower().strip()
    match = None
    for p in catalog:                                   # exact name first
        if p.get("slug") and (p.get("name") or "").lower().strip() == pn:
            match = p
            break
    if not match:                                       # then substring (longest wins)
        cands = [p for p in catalog if p.get("slug") and pn
                 and (pn in (p.get("name") or "").lower() or (p.get("name") or "").lower() in pn)]
        cands.sort(key=lambda p: len(p.get("name") or ""), reverse=True)
        match = cands[0] if cands else None

    if match:
        return {"link": f"{base}/catalog/{match['slug']}{q}", "product": match.get("name"),
                "note": "Share this so the customer can see this product's photos and price, and order in one tap."}
    return {"link": f"{base}/catalog{q}",
            "note": "Couldn't find that exact product — sharing the full catalog instead."}


async def _pause_conversation(args: dict, ctx: ToolContext) -> dict:
    """Code-enforced cooldown: the reply schedulers skip this contact while the
    key lives, so drift costs zero tokens for 2 hours. Best-effort — no redis,
    no pause (the agent's polite close still went out)."""
    try:
        if ctx.redis is not None:
            await ctx.redis.set(f"agent:pause:{ctx.channel}:{ctx.wa_id}", "1", ex=2 * 3600)
            # Activity log: the pause must be visible to the team, not silent.
            try:
                from sqlalchemy import or_
                from app.models.conversation import Conversation
                from app.models.intercept import Intercept, InterceptAction
                conv = (await ctx.db.execute(select(Conversation).where(
                    Conversation.channel == ctx.channel,
                    or_(Conversation.external_id == ctx.wa_id,
                        Conversation.wa_id == ctx.wa_id)))).scalars().first()
                if conv is not None:
                    ctx.db.add(Intercept(conversation_id=conv.id,
                                         action=InterceptAction.flag,
                                         note="AI paused this conversation for 2 hours "
                                              "(repeated off-topic drift)"))
                    await ctx.db.commit()
            except Exception:
                pass
            return {"ok": True, "paused_hours": 2}
    except Exception as exc:
        _log.warning("pause_conversation failed for %s: %s", ctx.wa_id, exc)
    return {"ok": False}


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
    "pause_conversation": _pause_conversation,
    "capture_contact": _capture_contact,
    "whatsapp_checkout_link": _whatsapp_checkout_link,
    "share_catalog": _share_catalog,
}
