"""Tier 2 agent tools — the actions Neema can take.

Each tool wraps capability we already built for the hub integration, exposed to
the model as a callable. The model decides WHEN to call them; these functions
own the how (server-authoritative pricing, stock, order creation).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
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
    currency: str = "KES"   # display currency for THIS customer (KES | USD | ZMW)
    usd_rate: int = 100     # KES per 1 USD (config.usd_kes_rate)
    channel: str = "whatsapp"  # source channel (whatsapp | messenger | instagram)
    # Catalogue rows the agent actually looked at this turn, in order — full hub
    # dicts (so they carry `slug`, which the model's own view deliberately omits).
    # Lets a caller link to the EXACT product the agent priced instead of
    # re-guessing it from the reply text. Survives dataclasses.replace().
    seen_products: list = field(default_factory=list)
    # Draft/preview mode: look-only. Tools must not write ANYTHING — not even a
    # best-effort side log like a demand signal.
    read_only: bool = False


def _channel_label(ctx: "ToolContext") -> str:
    """The honest channel for records: a web-chat session runs through the
    WhatsApp code path but is NOT WhatsApp — label its data 'web'."""
    return "web" if str(ctx.wa_id or "").startswith("web_") else ctx.channel


def _kes_rate_for(ctx: "ToolContext", ccy: str):
    """KES per 1 unit of a display currency — the conversion fallback when the
    hub carries no explicit price row in that currency."""
    return {"USD": ctx.usd_rate or 100,
            "ZMW": settings.zmw_kes_rate or 5}.get(ccy)


def _display(kes, ctx: "ToolContext"):
    """Convert a KES amount to the customer's display currency. Catalogue/cart
    amounts are stored in KES; Kenyan customers see KES, everyone else sees
    KES / their currency's rate (USD ÷100, ZMW ÷5). Whole numbers keep quotes
    clean — but small items (communion cups, wafers) keep cents: whole-dollar
    rounding floored a real KES price to '$0' and the agent told a customer
    cups were free."""
    if kes is None:
        return None
    rate = _kes_rate_for(ctx, ctx.currency)
    if rate:
        try:
            v = float(kes) / rate
        except (TypeError, ValueError):
            return kes
        if v <= 0:
            return 0
        return round(v) if v >= 1 else max(round(v, 2), 0.01)
    return kes


def _to_display(kes, ctx: "ToolContext", price_usd=None, prices=None):
    """Display price for THIS customer, preferring the hub's OWN price in their
    currency (the per-currency `prices` map — USD, ZMW, …), then the legacy
    `price_usd` field for USD, then KES / rate — so a missing/zero currency row
    never surfaces as 0. Kenya → raw KES. Catalogue and cart both go through
    this so quotes and totals stay consistent."""
    if ctx.currency == "KES":
        return kes
    own = (prices or {}).get(ctx.currency)
    if own is None and ctx.currency == "USD":
        own = price_usd
    try:
        v = float(own)
        if v > 0:
            return round(v) if v >= 1 else round(v, 2)   # cents for small items, never 0
    except (TypeError, ValueError):
        pass
    return _display(kes, ctx)


def _fmt_price(v, currency: str) -> str:
    """Human price string for a card body: 'KES 4,000', '$40', '$0.50'."""
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if currency == "USD":
        return f"${f:,.0f}" if f >= 1 else f"${f:,.2f}"
    return f"{currency} {f:,.0f}"


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
                "currency": {"type": "string", "enum": ["KES", "USD", "ZMW"],
                             "description": "Override the display currency: set 'KES' when the customer says they are in Kenya or asks for Kenyan shillings (our native prices), 'ZMW' when they say they are in Zambia (our own Kwacha prices); otherwise leave unset."},
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
                       "(payment + fulfilment). Call it to answer 'where's my order?', "
                       "to VERIFY any payment claim in the SAME turn the customer says "
                       "they've paid — never confirm payment without it — and before "
                       "answering any complaint about an order.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "capture_customer",
        "description": "Save details the customer shares — their name, delivery location, "
                       "role/title (Bishop, Rev, Pastor, Founder…) and church/ministry/"
                       "organization — so orders are correct and the team knows who they "
                       "serve. Capture what comes up naturally; never interrogate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "location": {"type": "string"},
                "role": {"type": "string", "description": "Their title/role, e.g. Bishop, Pastor, Founder & CEO"},
                "organization": {"type": "string", "description": "Their church/ministry/organization name"},
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
        "description": "Escalate to a human agent when the customer explicitly asks for a "
                       "person, or needs a human-only decision OUTSIDE any complaint (a "
                       "discount, a bespoke commission). A REFUND request, a COMPLAINT, or "
                       "any dissatisfaction goes through raise_complaint instead — that "
                       "keeps you in the conversation while the team is brought in, so the "
                       "customer is never left waiting in silence.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
    {
        "name": "raise_complaint",
        "description": "Put a complaint in front of the team as a COMPLETE CASE, after you "
                       "have acknowledged it and looked into it. Use this for any "
                       "dissatisfaction — a late or missing order, a wrong or damaged item, "
                       "being charged incorrectly, nobody replying, or a customer telling us "
                       "something is wrong. Call it ONLY after you have checked what you can "
                       "(check_order_status, the catalogue) so the team inherits your "
                       "findings, not just 'customer is upset'. A colleague always follows up "
                       "and has the final word — but you STAY in the conversation and keep "
                       "answering factual questions until they do. Never promise a refund, a "
                       "discount, a replacement or a specific resolution: say a colleague is "
                       "picking it up and, when you can, by when.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue": {"type": "string",
                          "description": "what the customer says went wrong, in their terms"},
                "findings": {"type": "string",
                             "description": "what YOU checked and found (order status, dates, "
                                            "the catalogue) — the facts the colleague needs"},
                "wanted": {"type": "string",
                           "description": "what the customer is asking for (refund, replacement, "
                                          "delivery, an explanation) — say 'unclear' if unstated"},
                "severity": {"type": "string", "enum": ["low", "normal", "high"],
                             "description": "high = money lost, an event/date at risk, or public anger"},
            },
            "required": ["issue"],
        },
    },
    {
        "name": "check_availability",
        "description": "Ask the team to confirm whether we can supply an item you cannot "
                       "confirm yourself (not in the catalogue, or an unusual variant). Use "
                       "this INSTEAD of telling the customer we don't have something — we "
                       "never say that. It alerts the team without ending your conversation, "
                       "so you keep serving them in the same breath. Pass the item in the "
                       "customer's own words.",
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string",
                                    "description": "The item to confirm, in the customer's words"}},
            "required": ["item"],
        },
    },
    {
        "name": "whatsapp_checkout_link",
        "description": "LAST RESORT ONLY — a one-tap WhatsApp link for a customer you cannot "
                       "serve where they already are. Buying intent is NOT a reason to call "
                       "this: 'I'll take it' / 'how do I pay' means CLOSE THE SALE HERE "
                       "(capture_contact for their number, then create_order). Call this ONLY "
                       "when they decline to share a phone number, they ask to move to "
                       "WhatsApp themselves, or the order genuinely cannot be placed in this "
                       "chat. Never use it to move a willing buyer — sending a ready customer "
                       "away loses the sale. Pass a SHORT product summary (a few words, never "
                       "the full order breakdown); share the returned tiny link exactly as given.",
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
                       "phone, and city/country. Their profile name is usually already in your "
                       "context — NEVER re-ask a name you can see there; only when no name has "
                       "appeared may you ask once, warmly (with city & country for delivery), "
                       "then call this. If they give a phone/WhatsApp number, pass it too — it "
                       "links their Messenger and WhatsApp into one customer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "the customer's name"},
                "phone": {"type": "string", "description": "phone/WhatsApp number if they shared it"},
                "location": {"type": "string", "description": "city and/or country, e.g. 'Kampala, Uganda'"},
                "role": {"type": "string", "description": "their title/role if mentioned, e.g. Bishop, Pastor, Founder"},
                "organization": {"type": "string", "description": "their church/ministry/organization if mentioned"},
            },
            "required": [],
        },
    },
    {
        "name": "pause_conversation",
        "description": "Pause this conversation for 2 hours. Two uses: (1) after ~3 consecutive "
                       "customer turns that stay outside Bethany House business (legal advice, "
                       "ministry counselling, off-topic chat) despite gentle redirection — send "
                       "one brief kind closing line, then call this; (2) to END a persistent "
                       "gift/hardship appeal AFTER your one scripture blessing (see GIFT "
                       "REQUESTS AND HARDSHIP APPEALS). Never use it on a buying customer, a "
                       "complaint, or an open order.",
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
    {
        "name": "save_parish",
        "description": "Record which CHURCH/PARISH this customer belongs to, the moment "
                       "they mention it ('I'm from St Mary's Nakuru', 'our cathedral needs "
                       "…', 'kanisa letu…'). The parish is the real buyer behind many "
                       "individual contacts — recording it groups the priest, the secretary "
                       "and the choir master into one institutional customer. Pass the "
                       "church name as they said it, and the town if mentioned.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "the church/parish name, e.g. \"St Mary's Nakuru\""},
                "location": {"type": "string", "description": "town/area if they mentioned it"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "church_calendar",
        "description": "The Church season right now, the vestment COLOUR it calls for, "
                       "and which seasons are coming up soon. Use it whenever colour or "
                       "timing matters — 'what colour for Advent?', 'will it be ready for "
                       "Easter?', or when a customer is choosing a vestment and the next "
                       "season is near. Never guess a season's date or colour: the dates "
                       "move every year (Easter is a moveable feast) — call this.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "save_measurements",
        "description": "Save the customer's body measurements so we NEVER ask for them "
                       "again. Call this the moment they give you any figure — chest, "
                       "length, sleeve, waist, shoulder, height, head size, collar, "
                       "shoe — even one at a time, and even mid-sentence. Pass what "
                       "they said, with units as they said them (e.g. chest '42in', "
                       "height '5ft10'). Merges with what's already on file, so "
                       "sending one corrected figure never wipes the rest.",
        "input_schema": {
            "type": "object",
            "properties": {
                "measurements": {
                    "type": "object",
                    "description": "Label → value, e.g. {\"chest\": \"42in\", \"length\": \"58in\"}",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["measurements"],
        },
    },
    {
        "name": "send_product_cards",
        "description": "Show the customer PRODUCT CARDS — each with the product photo, name, "
                       "price and a 'View' button that opens the product page. This is the "
                       "visual way to present products on WhatsApp (like a mini shop): use it "
                       "instead of typing product names/prices/links as text whenever you show "
                       "catalogue items, alternatives, or what's in their cart. Call "
                       "search_catalog first, then pass the EXACT product names (or SKUs) to "
                       "display. After the cards are sent, add only a short line (e.g. ask which "
                       "one, or their size) — never re-list the names, prices or links in text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "products": {"type": "array", "items": {"type": "string"},
                             "description": "Exact product names or SKUs to show as cards, in order (max 6)."},
            },
            "required": ["products"],
        },
    },
    {
        "name": "schedule_check_in",
        "description": "Book a future check-in the customer agreed to — the moment they "
                       "name a time ('in two weeks', 'end month', 'after Sunday', "
                       "'next month'). TWO cases, both count: (a) when they'll next "
                       "need supplies (divai, wafers, cups…), and (b) when they've said "
                       "they'll GET BACK TO US on a purchase they're still deciding — "
                       "a reminder about that order, or when to have the delivery "
                       "ready. The system messages them then, automatically. Call it IN "
                       "THE SAME TURN they name the time; then tell them plainly you'll "
                       "check in then. A named time is a promise we keep, never a "
                       "pleasantry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_from_now": {"type": "integer",
                                  "description": "When to check in, in days (e.g. 'two weeks' = 14, 'end month' = 30)."},
                "reason": {"type": "string",
                           "description": "What to check on, in plain words — e.g. \"they expect their divai and communion cups to run out around then; offer the next delivery\"."},
            },
            "required": ["days_from_now", "reason"],
        },
    },
    {
        "name": "prepare_quotation",
        "description": "Prepare a formal written quotation from the current cart — for a "
                       "parish, committee or organisation that needs it in writing before "
                       "approving the purchase. Build the cart with update_cart first. "
                       "Returns the quotation text: send it as your message exactly as "
                       "returned (you may add ONE warm line before it) — never retype or "
                       "alter the figures.",
        "input_schema": {
            "type": "object",
            "properties": {
                "addressed_to": {
                    "type": "string",
                    "description": "Who it is for — e.g. \"St Mary's Parish, Nakuru\" or the customer's name."},
            },
            "required": [],
        },
    },
]

# Registered only when a guide image is configured: the tool list must be
# byte-stable per deploy (it heads the prompt-cache prefix), and settings are
# fixed at boot — so this is a deploy-time constant, not a per-turn branch.
if settings.measurement_guide_url:
    TOOLS.append({
        "name": "send_measurement_guide",
        "description": "Send our labelled how-to-measure diagram to this customer. Use it "
                       "the FIRST time you ask for measurements (chest, length, sleeve…) so "
                       "they can see exactly how to take each one — then ask for the figures "
                       "in your own short line. Never re-send it in the same conversation.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    })


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
    if cur in ("KES", "USD", "ZMW") and cur != ctx.currency:
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
        row["price"] = _to_display(p.get("price"), ctx, p.get("price_usd"),
                                   prices=p.get("prices"))
        row["currency"] = ctx.currency
        # An unpriced hub row (e.g. "Bread container", KES 0 — no price set)
        # must NEVER surface as 0 or "free". Strip the number and say why, so
        # the model confirms with the team instead of quoting nothing-money.
        try:
            _pv = float(row["price"])
        except (TypeError, ValueError):
            _pv = None
        if not _pv or _pv <= 0:
            row["price"] = ""
            row["price_status"] = ("no price set in the hub — NEVER quote 0 or "
                                   "'free'; call check_availability, tell them "
                                   "you're confirming the price, keep selling "
                                   "the rest")
        # The hub's enriched product copy (fabric, embroidery, care, contents) —
        # this is what makes Neema's product talk SPECIFIC instead of generic.
        details = (p.get("description") or "").strip()
        if details:
            row["details"] = details[:260]
        # The workshop's own measurement spec for THIS item (production items
        # carry it in the hub) — the source of truth for WHAT to ask when
        # measuring. Compacted to one line; required figures lead.
        specs = p.get("measurements") or []
        if specs:
            req = [s.get("name") for s in specs if s.get("required") and s.get("name")]
            opt = [s.get("name") for s in specs if not s.get("required") and s.get("name")]
            unit = (specs[0].get("unit") or "").strip().lower()
            unit = "inches" if unit in ("in", "inch", "inches") else unit
            needed = ", ".join(req) if req else ""
            if opt:
                needed = (needed + f" (+ optional: {', '.join(opt)})").strip()
            if needed:
                row["measurements_needed"] = needed + (f" — in {unit}" if unit else "")
        # Variants each carry their OWN price (a Thurible in S ≠ L). Surface them
        # so the agent quotes the exact size/colour the customer wants — and a
        # price range when they haven't chosen yet — instead of one flat number.
        variants = p.get("variants") or []
        if variants:
            row["variants"] = [
                {"options": v.get("attributes") or v.get("name"),
                 "sku": v.get("sku"),
                 "price": _to_display(v.get("price_kes"), ctx, v.get("price_usd"),
                                      prices=v.get("prices"))}
                for v in variants
            ]
            prices = [vr["price"] for vr in row["variants"] if isinstance(vr["price"], (int, float))]
            if prices and min(prices) != max(prices):
                row["price_range"] = {"from": min(prices), "to": max(prices)}
                row["price_note"] = ("price depends on the variant — quote the one the "
                                     "customer picks, or give the range and ask")
        results.append(row)
        # Remember the FULL hub row (it has `slug`) so the caller can link to the
        # exact product the agent priced — the model's row above omits the slug.
        if p.get("slug"):
            ctx.seen_products.append(p)
        if len(results) >= 8:
            break
    if not results and query and not ctx.read_only:
        # Nothing in the catalogue answers this. That's unmet demand — the most
        # valuable thing a shop can learn — so log it instead of losing it.
        # (Skipped in read-only/draft mode: previews must write nothing.)
        from app.services import demand
        try:
            pid = await _person_id_of(ctx)
        except Exception:
            pid = None
        await demand.record(ctx.db, query, kind="no_match", channel=_channel_label(ctx),
                            wa_id=ctx.wa_id, person_id=pid)
    return {"count": len(results), "currency": ctx.currency, "results": results}


async def _cart_display(cart: dict, ctx: ToolContext) -> tuple[list, object]:
    """Cart items + total in the customer's display currency, preferring the
    hub's own price in that currency.

    KES customers get the raw items and cart_total untouched. For USD/ZMW we
    map each line to the hub's price in that currency (the line's own `prices`
    map, then the catalogue's; KES/rate as the last fallback), convert per
    line, and sum the converted lines so the shown total matches the shown
    unit prices. The catalogue is only loaded for the non-KES path (and it's
    cached), so the common Kenyan turn does no extra work."""
    # `in_stock`/`price_usd`/`prices` on a cart line are internal bookkeeping —
    # never shown to the model (in_stock feeds the sourcing flag; the price
    # fields feed non-KES display).
    _hidden = ("in_stock", "price_usd", "prices")
    items = [{k: v for k, v in i.items() if k not in _hidden} for i in cart.get("items", [])]
    raw = cart.get("items", [])
    if ctx.currency == "KES":
        return items, cartmod.cart_total(cart)
    catalog = await svc.catalog_items(ctx.db, ctx.redis)
    usd_by_id = {p.get("hub_product_id"): p.get("price_usd") for p in catalog}
    prices_by_id = {p.get("hub_product_id"): p.get("prices") or {} for p in catalog}
    out, total = [], 0
    for i, r in zip(items, raw):
        # Prefer the line's OWN prices (a variant's) over the product default.
        line_usd = r.get("price_usd") or usd_by_id.get(i.get("hub_product_id"))
        line_prices = r.get("prices") or prices_by_id.get(i.get("hub_product_id")) or {}
        unit = _to_display(i.get("unit_price"), ctx, line_usd, prices=line_prices)
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
            "prices": line.get("prices") or {},        # per-currency map (ZMW display)
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
        # A WEB session key is not a phone. Billing an order to "web_<hash>" is the
        # phantom-contact bug the Meta path explicitly guards against — fall back
        # to the captured phone, or make the agent ask for one (phone=None).
        from app.core.phone import is_plausible_phone as _plausible
        if not _plausible(ctx.wa_id):
            captured = (user.phone if user else None)
            phone = captured.lstrip("+") if (captured and _plausible(captured)) else None
            return phone, name, (user.person_id if user else None)
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


async def _save_profile_fields(db, person_id, role: str | None = None,
                               organization: str | None = None) -> dict | None:
    """Person-scoped role/organization (the human's title + ministry) — stored on
    persons.state['profile'] so it survives channel hops and merges.

    None = leave the field unchanged; an empty/whitespace string CLEARS it (the
    sidebar's way to remove a mis-captured role). Returns the resulting profile
    dict, or None when no person row was available to write to."""
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.person import Person
    if person_id is None or (role is None and organization is None):
        return None
    p = await db.get(Person, person_id)
    if p is None:
        return None
    st = dict(p.state or {})
    prof = dict(st.get("profile") or {})
    for key, val, limit in (("role", role, 100), ("organization", organization, 200)):
        if val is None:
            continue
        v = val.strip()
        if v:
            prof[key] = v[:limit]
        else:
            prof.pop(key, None)
    st["profile"] = prof
    p.state = st
    flag_modified(p, "state")
    return prof


async def _capture_customer(args: dict, ctx: ToolContext) -> dict:
    user = (await ctx.db.execute(select(User).where(User.wa_id == ctx.wa_id))).scalar_one_or_none()
    if user is None:
        return {"ok": False}
    if args.get("name"):
        user.name = args["name"].strip()
        user.name_confirmed = True
    if args.get("location"):
        user.location = args["location"].strip()
    prof = await _save_profile_fields(ctx.db, user.person_id,
                                      args.get("role"), args.get("organization"))
    await ctx.db.commit()
    out = {"ok": True, "name": user.name, "location": user.location}
    if prof:
        out["profile"] = prof
    return out


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

    prof = await _save_profile_fields(ctx.db, ident.person_id,
                                      args.get("role"), args.get("organization"))
    if prof:
        out["profile"] = prof

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
    # FIRST TOUCH STANDS. A webhook-captured ad origin ("facebook_ad") is ground
    # truth — the customer later SAYING "I saw you on Facebook" must not
    # downgrade it. Only an empty origin is filled here; operators can correct
    # via the CRM panel.
    existing = state.get("lead_source")
    if existing:
        return {"ok": True, "lead_source": existing,
                "note": "origin already recorded — kept the first touch"}
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


async def _check_availability(args: dict, ctx: ToolContext) -> dict:
    """Ask the team to confirm an item — WITHOUT ending the conversation.

    `handoff_to_human` flips the thread to human mode, which stops Neema
    replying at all. For "do you have a metal jug?" that is far too heavy: the
    customer is mid-purchase, and a thread parked in human mode is one nobody
    answers. This records the demand, drops a note in the thread and pings the
    team, while Neema stays on and keeps selling the rest of the table."""
    item = str(args.get("item") or "").strip()
    if not item:
        return {"error": "name the item to confirm"}
    if ctx.read_only:
        return {"ok": True, "item": item}

    from sqlalchemy import or_
    from app.models.conversation import Conversation
    from app.models.message import Message, MsgDirection, MsgSender
    from app.services import demand

    try:
        _pid = await _person_id_of(ctx)
    except Exception:
        _pid = None
    await demand.record(ctx.db, item, kind="availability_check",
                        channel=_channel_label(ctx), wa_id=ctx.wa_id, person_id=_pid)

    conv = (await ctx.db.execute(select(Conversation).where(
        Conversation.channel == ctx.channel,
        or_(Conversation.external_id == ctx.wa_id, Conversation.wa_id == ctx.wa_id),
    ))).scalars().first()
    if conv is not None:
        ctx.db.add(Message(
            channel=conv.channel, wa_id=conv.wa_id,
            external_id=getattr(conv, "external_id", None),
            person_id=conv.person_id, conversation_id=conv.id,
            direction=MsgDirection.outbound, sender=MsgSender.human_agent,
            text=(f"🔎 AVAILABILITY CHECK — the customer asked for: {item}\n"
                  "They were told we're confirming, NOT that we lack it. "
                  "Please confirm and reply here."),
            media_type="note",
        ))
        await ctx.db.commit()
        if ctx.redis is not None:
            try:
                import json as _json
                await ctx.redis.publish("ws:channel:agents:all", _json.dumps({
                    "event": "notification", "type": "availability_check",
                    "title": "🔎 Confirm availability",
                    "body": f"{item} — asked by {conv.wa_id or conv.external_id}",
                    "conv_id": str(conv.id),
                }))
            except Exception:
                pass

    return {"ok": True, "item": item,
            "note": "The team has been asked to confirm. Tell them you're checking and "
                    "will come back shortly — never that we don't have it — and in the "
                    "SAME message show the closest items from the same family."}


async def _handoff_to_human(args: dict, ctx: ToolContext) -> dict:
    """Route this conversation to a person. Channel-aware: a Meta contact's handle
    is a page-scoped PSID, so we match on (channel, external_id) — never mint a
    Conversation with a PSID in wa_id, which is how phantom contacts were born."""
    from sqlalchemy import or_
    from app.models.conversation import Conversation, InterceptMode
    # An escalation usually means "they want something we don't carry" — capture it
    # as demand before routing, so the reason becomes stock/production evidence.
    reason = str(args.get("reason") or "")
    if reason and not ctx.read_only:
        from app.services import demand
        try:
            _pid = await _person_id_of(ctx)
        except Exception:
            _pid = None
        await demand.record(ctx.db, reason, kind="out_of_catalogue",
                            channel=_channel_label(ctx), wa_id=ctx.wa_id, person_id=_pid)
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


async def _raise_complaint(args: dict, ctx: ToolContext) -> dict:
    """File a complaint as a complete case for the team — WITHOUT muting Neema.

    This is deliberately not `handoff_to_human`. That sets intercept_mode=human,
    which stops the agent replying at all AND drops the thread out of the
    missed-reply sweeper (it only picks up intercept_mode=ai) — so a complaint at
    11pm got one apology and then silence until someone opened the dashboard. The
    angriest customer received the least service.

    Here the conversation stays in AI mode: the team is flagged in the Activity
    log with Neema's findings, a colleague takes it over and has the final word,
    and meanwhile the customer still gets factual answers instead of nothing."""
    from sqlalchemy import or_
    from app.models.conversation import Conversation
    from app.models.intercept import Intercept, InterceptAction

    issue = (args.get("issue") or "").strip()
    if not issue:
        return {"error": "issue is required — describe what the customer says went wrong"}
    findings = (args.get("findings") or "").strip()
    wanted = (args.get("wanted") or "").strip()
    severity = (args.get("severity") or "normal").strip().lower()
    if severity not in ("low", "normal", "high"):
        severity = "normal"

    lines = [f"COMPLAINT ({severity.upper()}) — a colleague must follow up and close this.",
             f"• What the customer says: {issue}"]
    if findings:
        lines.append(f"• What Neema checked/found: {findings}")
    if wanted:
        lines.append(f"• What they're asking for: {wanted}")
    lines.append("• Neema has NOT promised any refund, discount or replacement, and is "
                 "still answering factual questions in the thread until you take over.")
    note = "\n".join(lines)

    conv = (await ctx.db.execute(select(Conversation).where(
        Conversation.channel == ctx.channel,
        or_(Conversation.external_id == ctx.wa_id, Conversation.wa_id == ctx.wa_id),
    ))).scalars().first()
    if conv is None:
        _log.warning("raise_complaint: no %s conversation for %s", ctx.channel, ctx.wa_id)
        return {"ok": False, "logged": False,
                "next_step": "Tell the customer plainly that a colleague will follow up, "
                             "and keep helping with anything factual you can answer."}

    ctx.db.add(Intercept(conversation_id=conv.id, action=InterceptAction.flag, note=note[:2000]))
    # Deliberately NOT conv.intercept_mode = human — see the docstring.
    await ctx.db.commit()
    _log.info("complaint raised on %s/%s (severity=%s)", ctx.channel, ctx.wa_id, severity)
    return {
        "ok": True,
        "logged": True,
        "severity": severity,
        "you_may": "explain what happened, give real order status, correct wrong information, "
                   "re-send a payment link, and say a colleague is picking it up (and by when "
                   "if you know).",
        "you_may_not": "promise or initiate a refund, offer a discount, commit to a remake or "
                       "reshipment, guarantee a delivery date you cannot verify, or accept "
                       "blame in a way that binds the business.",
        "next_step": "Tell the customer, warmly and without excuses, what you found and that a "
                     "colleague is now on it. Then STAY with them: keep answering factual "
                     "questions. Do NOT sell anything in this conversation unless they "
                     "themselves move on to buying.",
    }


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
    # An unpriced hub product must not become a 0-shilling cart line — a cart
    # that totals wrong is worse than one that asks. The model gets "not
    # matched", checks availability, and the team confirms the price first.
    if not line.get("unit_price"):
        _log.info("cart: refused unpriced hub product %r", line.get("name"))
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


def _storefront_base() -> str:
    return (settings.storefront_url or "https://bethanyhouse.co.ke").rstrip("/")


def _product_url(slug: str | None) -> str | None:
    """Public product page on the Bethany House storefront (where items are sold):
    https://bethanyhouse.co.ke/product/<slug>. This is the link Neema shares."""
    return f"{_storefront_base()}/product/{slug}" if slug else None


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
    store = _storefront_base()
    product = (args.get("product") or "").strip()
    if not product:
        return {"link": store,
                "note": "Share this so the customer can browse our products with photos and prices."}

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
        return {"link": _product_url(match["slug"]), "product": match.get("name"),
                "note": "Share this so the customer can see this product's photos and price, and order in one tap."}
    return {"link": store,
            "note": "Couldn't find that exact product — sharing the full catalog instead."}


def _match_product(query: str, catalog: list[dict]) -> dict | None:
    """Find the catalogue product for a name/SKU: exact name or SKU first, then the
    longest substring match. Only products with a storefront `slug` are eligible."""
    ql = (query or "").lower().strip()
    if not ql:
        return None
    for p in catalog:                                    # exact name / sku
        if not p.get("slug"):
            continue
        if (p.get("name") or "").lower().strip() == ql or (p.get("sku") or "").lower().strip() == ql:
            return p
    cands = [p for p in catalog if p.get("slug") and                     # substring
             (ql in (p.get("name") or "").lower() or (p.get("name") or "").lower() in ql)]
    cands.sort(key=lambda p: len(p.get("name") or ""), reverse=True)
    return cands[0] if cands else None


async def _record_shared_media(ctx: "ToolContext", *, media_url: str | None, caption: str,
                               waba_msg_id: str | None = None) -> None:
    """Mirror an image Neema sent to the customer into the dashboard thread, so a
    human following the conversation SEES exactly what was shared (and it lands in
    history). `waba_msg_id` is the sent card's wamid — stored so a customer
    reply-quoting the card ("this one, but in steel") resolves back to this row.
    Best-effort — never breaks the send if this fails."""
    if not media_url:
        return
    try:
        from datetime import datetime, timezone
        from sqlalchemy import select, or_
        from app.models.conversation import Conversation
        from app.models.message import Message, MsgDirection, MsgSender

        q = select(Conversation)
        if ctx.channel == "whatsapp":
            q = q.where(Conversation.wa_id == ctx.wa_id)
        else:
            q = q.where(Conversation.channel == ctx.channel,
                        or_(Conversation.external_id == ctx.wa_id,
                            Conversation.wa_id == ctx.wa_id))
        conv = (await ctx.db.execute(q)).scalars().first()
        if conv is None:
            return
        ctx.db.add(Message(
            wa_id=conv.wa_id, external_id=conv.external_id, conversation_id=conv.id,
            person_id=conv.person_id, channel=conv.channel or ctx.channel,
            direction=MsgDirection.outbound, sender=MsgSender.ai,
            text=caption or None, media_type="image", media_url=media_url,
            waba_msg_id=waba_msg_id,
        ))
        conv.last_message_at = datetime.now(timezone.utc)
        conv.last_message_preview = (caption or "📷 Photo")[:100]
        await ctx.db.commit()
        if ctx.redis is not None:
            from app.services.redis import broadcast
            await broadcast(ctx.redis, str(conv.id), {
                "type": "new_message", "conversationId": str(conv.id),
                "waId": conv.wa_id or conv.external_id, "direction": "outbound",
                "sender": "ai", "text": caption or "", "mediaType": "image",
                "mediaUrl": media_url,
            })
    except Exception as exc:
        _log.warning("record shared image failed for %s: %s", ctx.wa_id, exc)


async def _person_id_of(ctx: "ToolContext"):
    """This contact's person_id: WhatsApp → the User row; Meta → the Identity."""
    if ctx.channel == "whatsapp":
        u = (await ctx.db.execute(
            select(User).where(User.wa_id == ctx.wa_id))).scalar_one_or_none()
        return u.person_id if u else None
    from app.models.person import Identity
    ident = (await ctx.db.execute(select(Identity).where(
        Identity.channel == ctx.channel,
        Identity.external_id == ctx.wa_id))).scalar_one_or_none()
    return ident.person_id if ident else None


async def _save_parish(args: dict, ctx: ToolContext) -> dict:
    """Attach this customer to their church — the institutional buyer behind the
    individual contact. Also banked as a memory fact so it survives everywhere."""
    from app.services import parish as parish_svc
    name = str(args.get("name") or "").strip()
    if not name:
        return {"error": "pass the church/parish name"}
    # Bank the fact FIRST, unconditionally — so even a contact with no person yet
    # (a fresh web visitor) keeps the church name in memory. The old order skipped
    # this on the no-person path while telling the model it was "noted in memory".
    try:
        await memorymod.add_fact(ctx.db, ctx.wa_id, f"church: {name}", channel=ctx.channel)
    except Exception:
        pass
    person_id = await _person_id_of(ctx)
    if person_id is None:
        return {"ok": False, "note": "no linked profile yet — the name was noted in memory only"}
    p = await parish_svc.attach_person(ctx.db, person_id, name,
                                       location=(args.get("location") or None))
    if p is None:
        return {"ok": False,
                "note": "not recorded as a parish (unclear name, or they already "
                        "belong to a different one — a colleague can change it)"}
    return {"ok": True, "parish": p.name,
            "note": "Parish on file. Their orders now count toward this church's account."}


async def _church_calendar(args: dict, ctx: ToolContext) -> dict:
    """Where we are in the Church year — the one demand signal this business can
    know in advance. Pure computation, no network."""
    from app.core import liturgical
    s = liturgical.summary()
    return {**s,
            "note": "Colours are what the parish must WEAR that season. A season in "
                    "`order_now` is close enough that made-to-order should be started "
                    "now — mention it naturally if they're already shopping, never as "
                    "a hard sell."}


async def _save_measurements(args: dict, ctx: ToolContext) -> dict:
    """Put the customer's sizes on file, on their PERSON — so the figures they gave
    on Messenger are the figures Neema already knows on WhatsApp next time."""
    from app.agent import measurements as mm
    fields = args.get("measurements")
    if not isinstance(fields, dict) or not fields:
        return {"error": "pass the measurements as label → value, e.g. {\"chest\": \"42in\"}"}
    saved = await mm.save_measurements(ctx.db, ctx.wa_id, fields, ctx.channel, source="chat")
    if not saved:
        return {"ok": False, "note": "couldn't save — no profile for this contact yet"}
    return {"ok": True, "measurements": mm.visible(saved),
            "note": "On file. Don't ask for these again — next time confirm them "
                    "('same measurements as last time?') instead of re-asking."}


async def _send_product_cards(args: dict, ctx: ToolContext) -> dict:
    """Show the customer product cards (photo + name + price + a View link to the
    product page). On WhatsApp these go out as rich interactive cards immediately;
    on other channels (or if no photo/host is available) the card details are
    returned so the model can share them as a short list of links instead."""
    from app.core.phone import is_plausible_phone

    raw = args.get("products")
    if isinstance(raw, str):
        raw = [raw]
    names = [str(n).strip() for n in (raw or []) if str(n).strip()][:6]   # cap to 6 cards
    if not names:
        return {"error": "no products given — pass the exact product names to show"}

    catalog = await svc.catalog_items(ctx.db, ctx.redis)

    cards, seen = [], set()
    for q in names:
        p = _match_product(q, catalog)
        if not p or p.get("slug") in seen:
            continue
        seen.add(p.get("slug"))
        price = _to_display(p.get("price"), ctx, p.get("price_usd"),
                            prices=p.get("prices"))
        cards.append({
            "name": p.get("name"),
            "price_text": _fmt_price(price, ctx.currency),
            "image": p.get("thumbnail_url") or p.get("image_url"),
            "url": _product_url(p.get("slug")),   # Bethany House storefront product page
            "slug": p.get("slug"),
        })

    if not cards:
        return {"error": "none of those products were found in the catalogue",
                "hint": "call search_catalog first, then pass the exact product names it returns"}

    # Rich WhatsApp cards — only for a real WhatsApp phone (never a Meta PSID or a
    # web session key), and only when we have a storefront URL to link to.
    if ctx.channel == "whatsapp" and is_plausible_phone(ctx.wa_id):
        from app.services.media_convert import to_sendable_image
        sent = 0
        for c in cards:
            try:
                # WhatsApp image messages reject .webp — convert the hub photo to jpg.
                img = await to_sendable_image(c["image"])
                if not img and not c["url"]:
                    # Nothing to show and nowhere to send them: let the model
                    # describe it in words rather than send an empty card.
                    _log.info("send_product_cards: %s has no photo and no link",
                              c["slug"])
                    continue
                if not img:
                    _log.info("send_product_cards: %s has no photo in the "
                              "catalogue — card goes out without one", c["slug"])
                card_wamid = await svc._send_waba_product_card(
                    ctx.wa_id, image_url=img, title=c["name"],
                    body=c["price_text"], url=c["url"])
                sent += 1
                _log.info("product card sent to %s: %s (img=%s)", ctx.wa_id, c["slug"],
                          "yes" if img else "no")
                # Mirror the photo into the dashboard thread so a human sees it too —
                # with the card's wamid, so a reply-quote of the card resolves to it.
                await _record_shared_media(
                    ctx, media_url=img,
                    caption=" — ".join(x for x in (c["name"], c["price_text"]) if x),
                    waba_msg_id=card_wamid)
            except Exception as exc:
                _log.warning("send_product_cards: card failed for %s: %s", c["slug"], exc)
        if sent:
            return {"ok": True, "sent_cards": sent,
                    "note": "Cards with photo, price and a View button were delivered to the "
                            "customer. Reply with only a short line (ask which one, or their "
                            "size/quantity) — do NOT repeat the names, prices or links as text."}

    # Rich cards on Messenger / Instagram — a NATIVE generic-template carousel
    # (photo + name + price + View button, swipeable), the web-chat card look.
    if ctx.channel in ("messenger", "instagram"):
        from app.services.media_convert import to_sendable_image
        elements = []
        for c in cards:
            el = {
                "title": (c["name"] or "")[:80],
                "subtitle": (c["price_text"] or "")[:80],
            }
            # The View button needs a link, but a card without one still shows
            # the photo and the price — far better than a text-only reply.
            if c["url"]:
                el["default_action"] = {"type": "web_url", "url": c["url"]}
                el["buttons"] = [{"type": "web_url", "url": c["url"], "title": "View"}]
            img = await to_sendable_image(c["image"])
            if img:
                el["image_url"] = img
            c["_img"] = img
            if not img and not c["url"]:
                _log.info("send_product_cards: %s has no photo and no link", c["slug"])
                continue
            elements.append(el)
        if elements:
            try:
                from app.services.meta_send import send_meta_carousel, page_of_contact
                page_id = await page_of_contact(ctx.channel, ctx.wa_id)
                await send_meta_carousel(ctx.wa_id, elements, page_id=page_id)
                _log.info("product carousel sent to %s (%s cards) on %s",
                          ctx.wa_id, len(elements), ctx.channel)
                # Mirror each photo into the dashboard thread so a human sees them too.
                for c in cards:
                    if c.get("_img"):
                        await _record_shared_media(
                            ctx, media_url=c["_img"],
                            caption=" — ".join(x for x in (c["name"], c["price_text"]) if x))
                return {"ok": True, "sent_cards": len(elements),
                        "note": "A swipeable carousel of product cards (photo, price, View "
                                "button) was sent. Add only a short line — do NOT re-list the "
                                "names, prices or links as text."}
            except Exception as exc:
                _log.warning("send_product_cards: meta carousel failed: %s", exc)
                # Last resort before words: send the photos as plain attachments.
                # A customer asking "how much is the lay reader set?" should SEE
                # the set, even when the rich carousel can't be delivered.
                photos = 0
                try:
                    from app.services.meta_send import send_meta_media, page_of_contact
                    page_id = await page_of_contact(ctx.channel, ctx.wa_id)
                    for c in cards:
                        if not c.get("_img"):
                            continue
                        await send_meta_media(ctx.wa_id, "image", c["_img"],
                                              page_id=page_id)
                        await _record_shared_media(
                            ctx, media_url=c["_img"],
                            caption=" — ".join(x for x in (c["name"], c["price_text"]) if x))
                        photos += 1
                except Exception as exc2:
                    _log.warning("send_product_cards: photo fallback failed: %s", exc2)
                if photos:
                    return {"ok": True, "sent_cards": photos,
                            "note": "The product photo(s) were sent as images (the rich "
                                    "carousel was unavailable). Add one short line with the "
                                    "price and the link so they can tap through."}
                # fall through to the text-link list

    # Non-WhatsApp channel, or nothing could be sent: hand the details back so the
    # model shares them as a short text list with links.
    return {"ok": True, "sent_cards": 0,
            "products": [{"name": c["name"], "price": c["price_text"], "link": c["url"]} for c in cards],
            "note": "Rich cards aren't available here — share these as a short list, each with "
                    "its price and link so the customer can tap through."}


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


async def _schedule_check_in(args: dict, ctx: ToolContext) -> dict:
    """Plan a replenishment check-in on the initiative scheduler. The customer
    named a time; this makes it a kept promise — process_due sends the message
    (utility template when the 24h window has closed by then, as it will have)."""
    from datetime import timedelta
    try:
        days = int(args.get("days_from_now") or 0)
    except (TypeError, ValueError):
        return {"error": "days_from_now must be a number of days"}
    days = max(1, min(days, 90))
    reason = (args.get("reason") or "").strip()
    if not reason:
        return {"error": "reason is required — what should the check-in be about?"}
    if ctx.read_only:
        return {"ok": True, "preview": True}
    from app.models.agent_action import AgentAction
    from app.models.conversation import Conversation
    channel = _channel_label(ctx)
    where = (Conversation.wa_id == ctx.wa_id) if ctx.channel == "whatsapp" else (
        (Conversation.channel == ctx.channel) & (Conversation.external_id == ctx.wa_id))
    conv = (await ctx.db.execute(select(Conversation).where(where))).scalar_one_or_none()
    if conv is None:
        return {"error": "no conversation found to attach the check-in to"}
    due = datetime.now(timezone.utc) + timedelta(days=days)
    due = due.replace(hour=7, minute=0, second=0, microsecond=0)   # 10:00 Nairobi
    ctx.db.add(AgentAction(deal_id=None, conversation_id=conv.id, due_at=due,
                           kind="replenishment",
                           reason=f"Customer-agreed check-in ({channel}): {reason[:400]}"))
    await ctx.db.commit()
    return {"ok": True, "check_in_on": due.strftime("%d %b %Y"),
            "note": "booked — now tell them plainly you'll check in then"}


async def _prepare_quotation(args: dict, ctx: ToolContext) -> dict:
    """A formal written quotation from the cart — what a parish committee needs
    in hand to approve the purchase. Composed in code so the figures can't
    drift; the model sends the text verbatim."""
    import hashlib as _hashlib
    from datetime import timedelta as _td
    cart = await cartmod.get_cart(ctx.db, ctx.wa_id, ctx.channel)
    if not (cart.get("items") or []):
        return {"error": "cart is empty — add the items with update_cart first"}
    items, total = await _cart_display(cart, ctx)
    nairobi = datetime.now(timezone.utc) + _td(hours=3)
    number = (f"QT-{nairobi.strftime('%y%m%d')}-"
              f"{_hashlib.sha1(ctx.wa_id.encode()).hexdigest()[:4].upper()}")
    to = (args.get("addressed_to") or "").strip()
    # Asterisk bold renders ONLY on WhatsApp; Messenger/Instagram/web show the
    # literal `*`, so those channels get plain text (the meta addendum's rule).
    star = "*" if _channel_label(ctx) == "whatsapp" else ""
    lines = [f"{star}QUOTATION {number}{star}",
             "Bethany House — Nairobi, Kenya",
             f"Date: {nairobi.strftime('%d %b %Y')}"]
    if to:
        lines.append(f"Prepared for: {to}")
    lines.append("")
    for i in items:
        qty = i.get("qty") or i.get("quantity") or 1
        name = i.get("name") or "Item"
        try:
            unit = float(i.get("unit_price"))
            lines.append(f"- {name} ×{qty} @ {ctx.currency} {unit:,.0f} "
                         f"= {ctx.currency} {unit * float(qty):,.0f}")
        except (TypeError, ValueError):
            lines.append(f"- {name} ×{qty}")
    try:
        total_s = f"{float(total):,.0f}"
    except (TypeError, ValueError):
        total_s = str(total)
    lines += ["",
              f"{star}TOTAL: {ctx.currency} {total_s}{star}",
              f"Valid until {(nairobi + _td(days=14)).strftime('%d %b %Y')}.",
              "Made to order and tailored to your measurements. Delivery is "
              "quoted separately by destination."]
    return {"ok": True, "quotation": "\n".join(lines),
            "note": "send this text as your message — at most one warm line before it"}


async def _send_measurement_guide(args: dict, ctx: ToolContext) -> dict:
    """Send the how-to-measure diagram. WhatsApp gets the image natively; Meta
    channels get the link to include with the ask (their DM clients preview it)."""
    url = (settings.measurement_guide_url or "").strip()
    if not url:
        return {"error": "no measurement guide is configured"}
    if ctx.channel == "whatsapp":
        try:
            from app.services import n8n_bridge as _svc
            wamid = await _svc._send_waba_image(
                ctx.wa_id, url, caption="How to take your measurements 📏")
            await _svc.save_outbound_message(
                ctx.db, ctx.redis, ctx.wa_id, "[image] How-to-measure guide 📏",
                waba_msg_id=wamid)
            return {"ok": True, "sent": "image",
                    "note": "the diagram is with them — now ask for the figures in one short line"}
        except Exception as exc:
            _log.warning("measurement guide send failed for %s: %s", ctx.wa_id, exc)
            return {"error": "could not send the image — share the figures ask in words instead"}
    return {"ok": True, "guide_url": url,
            "note": "include this link with your ask so they can see how to measure"}


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
    "raise_complaint": _raise_complaint,
    "check_availability": _check_availability,
    "pause_conversation": _pause_conversation,
    "capture_contact": _capture_contact,
    "whatsapp_checkout_link": _whatsapp_checkout_link,
    "share_catalog": _share_catalog,
    "send_product_cards": _send_product_cards,
    "save_measurements": _save_measurements,
    "church_calendar": _church_calendar,
    "save_parish": _save_parish,
    "prepare_quotation": _prepare_quotation,
    "send_measurement_guide": _send_measurement_guide,
    "schedule_check_in": _schedule_check_in,
}
