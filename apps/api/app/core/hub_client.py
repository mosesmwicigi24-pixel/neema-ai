"""Bethany House hub client — the hub is the single source of truth for
products, prices and stock (shared by POS, website and this WhatsApp agent).

This module reads the hub's public catalogue and maps it into the shape Neema's
AI pipeline already expects, so the agent quotes live hub prices and never sells
an out-of-stock item. It carries `hub_product_id` on every line — that's what a
confirmed order will reference when it's pushed back into the hub.

Cached in Redis; callers fall back to Neema's local catalogue table if the hub
is unreachable, so a conversation never loses its price list mid-sale.
"""
from __future__ import annotations

import json
import logging

import httpx

from app.core.config import settings

_log = logging.getLogger("neema.hub")
_CACHE_KEY = "hub:catalog"


def _price(prices_by_ccy: dict, ccy: str):
    pr = prices_by_ccy.get(ccy) or {}
    val = pr.get("sale_price") or pr.get("regular_price")
    try:
        return float(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _map_product(p: dict) -> dict:
    trans = p.get("translations") or []
    en = next((t for t in trans if t.get("language_code") == "en"),
              trans[0] if trans else {})
    prices = {pr.get("currency_code"): pr for pr in (p.get("prices") or [])}
    kes = _price(prices, "KES")
    usd = _price(prices, "USD")
    return {
        "hub_product_id": p.get("id"),
        "uuid":           p.get("uuid"),
        "sku":            p.get("sku") or "",
        "name":           en.get("name") or "",
        "category":       (p.get("category") or {}).get("name_en") or "",
        # `price` stays KES for backward-compat with the current prompt; both
        # currencies are carried so quoting can be made currency-correct next.
        "price":          kes if kes is not None else 0.0,
        "price_kes":      kes,
        "price_usd":      usd,
        "unit":           "",
        "description":    en.get("short_description") or en.get("description") or "",
        "aliases":        p.get("aliases") or [],
        "in_stock":       bool(p.get("in_stock", True)),
        "available_qty":  p.get("available_qty"),
        # Order-routing: "variable" products track stock per-variant, so a bare
        # product_id fails the POS stock check. Producible (made-to-order) items
        # are pushed via production_items[] instead — no variant, no stock check.
        "product_type":   p.get("product_type") or "simple",
        "is_producible":  bool(p.get("is_producible")),
    }


async def fetch_hub_catalog(redis) -> list[dict]:
    """All published hub products, mapped to Neema's catalogue shape (cached).

    Raises on network/HTTP failure so the caller can fall back to the local
    table — never returns a partial/empty list silently.
    """
    if redis is not None:
        try:
            cached = await redis.get(_CACHE_KEY)
            if cached:
                return json.loads(cached)
        except Exception:  # cache miss is non-fatal
            pass

    items: list[dict] = []
    page = 1
    base = settings.hub_api_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            resp = await client.get(
                f"{base}/api/v1/products",
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            data = resp.json()
            for p in data.get("data", []):
                items.append(_map_product(p))
            last = data.get("last_page") or 1
            if page >= last:
                break
            page += 1

    if not items:
        raise RuntimeError("hub returned zero products")

    if redis is not None:
        try:
            await redis.setex(_CACHE_KEY, settings.hub_catalog_ttl, json.dumps(items))
        except Exception:
            pass
    _log.info("hub catalogue loaded: %d products", len(items))
    return items


# ── Order push (Part B) + fulfilment relay (Loop C) ──────────────────────────
#
# A confirmed WhatsApp cart carries item lines like {name, qty, unit, sku?} but
# NOT the hub product id — the AI matches by name. We resolve each line back to a
# hub product HERE (server-authoritative) against the same cached catalogue the
# agent sold from, then create a "pending, awaiting payment" order in the hub
# under the WhatsApp outlet. No money moves: the customer pays via the hub's own
# payment link (relayed on WhatsApp by Loop C).

def _api_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.hub_api_token}",
        "Accept": "application/json",          # else the hub 302-redirects HTML
        "Content-Type": "application/json",
    }


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def resolve_hub_line(item: dict, catalog: list[dict]) -> dict | None:
    """Match one confirmed cart line to a hub product.

    Precedence: exact SKU → exact name → alias → substring. Returns a hub order
    line {product_id, quantity, unit_price, name, matched_by} using the hub's own
    price (source of truth), or None if nothing matched.
    """
    name = _norm(item.get("name") or item.get("product") or item.get("title"))
    sku = _norm(item.get("sku"))
    qty = item.get("qty") or item.get("quantity") or 1
    try:
        qty = max(int(qty), 1)
    except (TypeError, ValueError):
        qty = 1

    def _line(p: dict, matched_by: str) -> dict:
        # Hub price is authoritative; fall back to the AI's quoted unit only if
        # the catalogue has no price (shouldn't happen for a sellable item).
        price = p.get("price")
        if price in (None, 0, 0.0):
            price = item.get("unit") or item.get("price") or item.get("unit_price") or 0
        return {
            "product_id": p.get("hub_product_id"),
            "quantity": qty,
            "unit_price": float(price or 0),
            "name": p.get("name"),
            "matched_by": matched_by,
            "product_type": p.get("product_type") or "simple",
            "is_producible": bool(p.get("is_producible")),
        }

    by_sku = {_norm(p.get("sku")): p for p in catalog if p.get("sku")}
    by_name = {_norm(p.get("name")): p for p in catalog if p.get("name")}

    if sku and sku in by_sku and by_sku[sku].get("hub_product_id"):
        return _line(by_sku[sku], "sku")
    if name and name in by_name and by_name[name].get("hub_product_id"):
        return _line(by_name[name], "name")
    for p in catalog:                       # alias exact
        if p.get("hub_product_id") and any(_norm(a) == name for a in (p.get("aliases") or [])):
            return _line(p, "alias")
    if name:                                # substring (longest name wins)
        cands = [
            p for p in catalog
            if p.get("hub_product_id") and (name in _norm(p.get("name")) or _norm(p.get("name")) in name)
        ]
        if cands:
            cands.sort(key=lambda p: len(_norm(p.get("name"))), reverse=True)
            return _line(cands[0], "contains")
    return None


def _is_made_to_order(line: dict) -> bool:
    """A line the hub should MAKE, not sell from stock.

    Variable products track inventory per-variant, so a bare product_id fails
    the POS stock check; when such a product is also producible it's a genuine
    made-to-order item (custom vestments — sized per order). These go through
    production_items[], which skips the stock check and needs no variant_id.
    Simple products (and non-producible ones) sell from stock via items[].
    """
    return line.get("product_type") == "variable" and bool(line.get("is_producible"))


async def _find_customer_id(wa_id: str) -> int | None:
    """Reuse an existing hub customer by phone so repeat buyers don't duplicate."""
    base = settings.hub_api_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                f"{base}/api/v1/admin/pos/customers/search",
                headers=_api_headers(),
                params={"q": wa_id},
            )
            resp.raise_for_status()
            digits = "".join(ch for ch in wa_id if ch.isdigit())
            for c in (resp.json() or {}).get("data", []):
                cphone = "".join(ch for ch in str(c.get("phone") or "") if ch.isdigit())
                if cphone and (cphone == digits or cphone.endswith(digits) or digits.endswith(cphone)):
                    return c.get("id")
    except Exception:
        pass  # dedupe is a nicety — fall back to new_customer
    return None


async def push_pending_order(
    catalog: list[dict],
    *,
    wa_id: str,
    first_name: str,
    country_iso: str | None,
    items: list[dict],
) -> dict:
    """Create a pending order in the hub from a confirmed WhatsApp cart.

    Stock lines go via items[]; made-to-order lines (custom vestments) via
    production_items[]. Reuses an existing customer (by phone) when present.
    Returns {order_id, order_number, total_amount, currency_code, lines,
    production_lines, unmatched}. Raises on HTTP failure (caller records the
    error and retries). Raises ValueError with .unmatched attached when NO line
    could be matched to a hub product.
    """
    stock_lines, mto_lines, unmatched = [], [], []
    for it in items or []:
        line = resolve_hub_line(it, catalog)
        if not line:
            unmatched.append(it.get("name") or it.get("product") or "item")
        elif _is_made_to_order(line):
            mto_lines.append(line)
        else:
            stock_lines.append(line)

    if not stock_lines and not mto_lines:
        err = ValueError("no cart line matched a hub product")
        err.unmatched = unmatched            # type: ignore[attr-defined]
        raise err

    # channel='whatsapp' groups the order under the hub's "WhatsApp Orders" (and
    # tags order_type/number as WA-), while the outlet stays the fulfilling store.
    payload = {
        "outlet_id": settings.hub_outlet_id,
        "channel": "whatsapp",
        "notes": "WhatsApp order via Neema",
    }
    if stock_lines:
        payload["items"] = [
            {"product_id": l["product_id"], "quantity": l["quantity"], "unit_price": l["unit_price"]}
            for l in stock_lines
        ]
    if mto_lines:
        payload["production_items"] = [
            {
                "product_id": l["product_id"],
                "quantity": l["quantity"],
                "unit_price": l["unit_price"],
                # Size/measurements aren't captured on WhatsApp yet — prompt staff.
                "production_notes": "WhatsApp order via Neema — confirm size/measurements with the customer.",
            }
            for l in mto_lines
        ]
    if country_iso:
        payload["customer_country_code"] = country_iso.upper()

    customer_id = await _find_customer_id(wa_id)
    if customer_id:
        payload["customer_id"] = customer_id
    else:
        payload["new_customer"] = {"first_name": first_name or "WhatsApp Customer", "phone": wa_id}

    base = settings.hub_api_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{base}/api/v1/admin/pos/pending-order",
            headers=_api_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "order_id": data.get("order_id"),
        "order_number": data.get("order_number"),
        "total_amount": data.get("total_amount"),
        "currency_code": data.get("currency_code"),
        "lines": stock_lines,
        "production_lines": mto_lines,
        "unmatched": unmatched,
    }


async def fetch_payment_link(order_id: int) -> str | None:
    """The hub's customer payment page URL for an order (mints the 72h token)."""
    base = settings.hub_api_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{base}/api/v1/admin/orders/{order_id}/payment-link",
            headers=_api_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
    return data.get("payment_url") or data.get("url")


async def fetch_order_status(order_id: int, redis=None) -> dict | None:
    """Live status of a hub order (for "where's my order?"). Cached briefly."""
    key = f"hub:order:{order_id}"
    if redis is not None:
        try:
            cached = await redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    base = settings.hub_api_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{base}/api/v1/admin/orders/{order_id}",
            headers=_api_headers(),
        )
        resp.raise_for_status()
        body = resp.json() or {}
        # The hub returns the order under {"order": {...}} (admin order detail);
        # tolerate a {"data": {...}} or bare-object shape too.
        o = body.get("order") or body.get("data") or body

    status = {
        "order_id": order_id,
        "order_number": o.get("order_number"),
        "status": o.get("status"),
        "payment_status": o.get("payment_status"),
        "fulfillment_status": o.get("fulfillment_status") or o.get("fulfilment_status"),
        "total_amount": o.get("total_amount") or o.get("total"),
        "currency_code": o.get("currency_code") or o.get("currency"),
    }
    if redis is not None:
        try:
            await redis.setex(key, settings.hub_order_status_ttl, json.dumps(status))
        except Exception:
            pass
    return status
