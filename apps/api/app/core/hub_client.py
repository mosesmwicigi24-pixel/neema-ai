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


def _all_prices(prices_list) -> dict:
    """Every currency the hub prices this item in → {code: amount}, keeping only
    real 3-letter ISO codes and POSITIVE amounts (the hub sends 0.00 duplicates
    and stray codes). Last positive wins per currency. This is the multi-currency
    source of truth the catalog quotes from — KES, USD, ZMW, and whatever's added
    next flow through automatically."""
    by: dict = {}
    for pr in (prices_list or []):
        code = (pr.get("currency_code") or "").upper()
        if not (code.isalpha() and len(code) == 3):
            continue
        val = pr.get("sale_price") or pr.get("regular_price")
        try:
            v = float(val) if val not in (None, "") else 0.0
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            by[code] = v
    return by


def _map_images(p: dict) -> list[dict]:
    """Ordered {url, thumb, alt} list from the hub's product images (primary
    first). Empty list when the product has no images."""
    imgs = p.get("images") or []
    out = [
        {
            "url":   im.get("image_url"),
            "thumb": im.get("thumbnail_url") or im.get("image_url"),
            "alt":   im.get("alt_text") or "",
            "primary": bool(im.get("is_primary")),
            "sort":  im.get("sort_order") or 0,
        }
        for im in imgs if im.get("image_url")
    ]
    out.sort(key=lambda i: (not i["primary"], i["sort"]))   # primary first, then sort_order
    return out


def _map_variant(v: dict) -> dict:
    """One product variant → the compact shape the agent quotes from: its own
    SKU, human name ('S / GOLD'), attributes ({Size, Colour}), and per-currency
    price. Each variant carries its OWN price — a Thurible in S is KES 9,000 but
    L is KES 15,000 — so the agent must quote the variant, not the product."""
    prices = _all_prices(v.get("prices"))
    return {
        "variant_id": v.get("id"),
        "sku":        v.get("sku") or "",
        "name":       v.get("variant_name") or "",
        "attributes": v.get("attributes") or {},
        "price_kes":  prices.get("KES"),
        "price_usd":  prices.get("USD"),
        "prices":     prices,               # full multi-currency map
        "is_default": bool(v.get("is_default")),
        "in_stock":   bool(v.get("is_active", True)),
    }


def _map_product(p: dict) -> dict:
    trans = p.get("translations") or []
    en = next((t for t in trans if t.get("language_code") == "en"),
              trans[0] if trans else {})
    prices = _all_prices(p.get("prices"))
    kes = prices.get("KES")
    usd = prices.get("USD")
    images = _map_images(p)
    return {
        "hub_product_id": p.get("id"),
        "uuid":           p.get("uuid"),
        "sku":            p.get("sku") or "",
        "slug":           p.get("slug") or "",
        "name":           en.get("name") or "",
        "category":       (p.get("category") or {}).get("name_en") or "",
        # `price` stays KES for backward-compat with the current prompt; the full
        # multi-currency map is carried so the catalog quotes each customer's own
        # money (KES / USD / ZMW / whatever the hub adds next).
        "price":          kes if kes is not None else 0.0,
        "price_kes":      kes,
        "price_usd":      usd,
        "prices":         prices,
        "unit":           "",
        "description":    en.get("short_description") or en.get("description") or "",
        "aliases":        p.get("aliases") or [],
        "in_stock":       bool(p.get("in_stock", True)),
        "available_qty":  p.get("available_qty"),
        # Product visuals (primary first) — for the shareable catalog + inline
        # product images the agent can send in chat.
        "images":         images,
        "image_url":      images[0]["url"] if images else None,
        "thumbnail_url":  images[0]["thumb"] if images else None,
        # Order-routing: "variable" products track stock per-variant, so a bare
        # product_id fails the POS stock check. Producible (made-to-order) items
        # are pushed via production_items[] instead — no variant, no stock check.
        "product_type":   p.get("product_type") or "simple",
        "is_producible":  bool(p.get("is_producible")),
        # Filled in by fetch_hub_catalog for variable products (each with its own
        # price); empty for simple products.
        "variants":       [],
    }


async def _fetch_variants(client: "httpx.AsyncClient", base: str, product_id) -> list[dict]:
    """The variants for one variable product, mapped. Best-effort: on any error
    return [] so the product still sells at its base price."""
    try:
        resp = await client.get(f"{base}/api/v1/products/{product_id}/variants")
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data", data) if isinstance(data, dict) else data
        return [_map_variant(v) for v in (rows or []) if v.get("is_active", True)]
    except Exception as exc:
        _log.warning("hub variants fetch failed for product %s: %s", product_id, exc)
        return []


def _apply_variant_pricing(prod: dict) -> None:
    """Give a variable product a sensible base price + range from its variants,
    so a bare quote is never 0 and the agent can say 'from KES 9,000'. The
    default variant sets the base; min/max frame the range."""
    vs = prod.get("variants") or []
    kes = [v["price_kes"] for v in vs if v.get("price_kes") is not None]
    usd = [v["price_usd"] for v in vs if v.get("price_usd") is not None]
    default = next((v for v in vs if v.get("is_default")), vs[0] if vs else None)
    if default:
        if not prod.get("price_kes"):
            prod["price_kes"] = default.get("price_kes")
            prod["price"] = default.get("price_kes") or prod.get("price") or 0.0
        if not prod.get("price_usd"):
            prod["price_usd"] = default.get("price_usd")
    if kes:
        prod["price_min_kes"], prod["price_max_kes"] = min(kes), max(kes)
    if usd:
        prod["price_min_usd"], prod["price_max_usd"] = min(usd), max(usd)


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

        # Variable products carry per-variant prices on a separate endpoint —
        # pull them (concurrently, bounded) so the agent can quote the right
        # size/colour, then derive each product's base price + range.
        import asyncio
        variable = [p for p in items if p.get("product_type") == "variable" and p.get("hub_product_id")]
        sem = asyncio.Semaphore(8)

        async def _load(p):
            async with sem:
                p["variants"] = await _fetch_variants(client, base, p["hub_product_id"])
            _apply_variant_pricing(p)

        if variable:
            await asyncio.gather(*[_load(p) for p in variable])

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

    def _line(p: dict, matched_by: str, variant: dict | None = None) -> dict:
        # Hub price is authoritative; fall back to the AI's quoted unit only if
        # the catalogue has no price (shouldn't happen for a sellable item). For a
        # matched VARIANT, the variant's own KES price is the source of truth.
        price = (variant or {}).get("price_kes") if variant else p.get("price")
        if price in (None, 0, 0.0):
            price = p.get("price") or item.get("unit") or item.get("price") or item.get("unit_price") or 0
        return {
            "product_id": p.get("hub_product_id"),
            "quantity": qty,
            "unit_price": float(price or 0),
            "name": (f"{p.get('name')} ({variant.get('name')})" if variant else p.get("name")),
            "variant_sku": (variant or {}).get("sku"),
            "variant_id": (variant or {}).get("variant_id"),
            "unit_price_usd": (variant or {}).get("price_usd") if variant else p.get("price_usd"),
            "matched_by": matched_by,
            "product_type": p.get("product_type") or "simple",
            "is_producible": bool(p.get("is_producible")),
        }

    by_sku = {_norm(p.get("sku")): p for p in catalog if p.get("sku")}
    by_name = {_norm(p.get("name")): p for p in catalog if p.get("name")}
    # Variant lookups: a variant SKU ("COM-T-001-S-GOL") or full name ("thurible
    # s / gold") resolves to its parent product at the VARIANT's price.
    by_var_sku = {_norm(v.get("sku")): (p, v)
                  for p in catalog for v in (p.get("variants") or []) if v.get("sku")}
    by_var_name = {_norm(f"{p.get('name')} {v.get('name')}"): (p, v)
                   for p in catalog for v in (p.get("variants") or []) if v.get("name")}

    if sku and sku in by_var_sku:
        p, v = by_var_sku[sku]
        return _line(p, "variant_sku", v)
    if sku and sku in by_sku and by_sku[sku].get("hub_product_id"):
        return _line(by_sku[sku], "sku")
    if name and name in by_var_name:
        p, v = by_var_name[name]
        return _line(p, "variant_name", v)
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


async def _search_customer_match(wa_id: str) -> dict | None:
    """Find the hub customer that is the *same person* as this WhatsApp contact.

    The hub stores numbers in mixed formats (0712…, 254712…, +254712…), so we
    search by the national digits (an ILIKE that hits every format) but confirm on
    the full country-aware E.164 — so a Kenyan contact never matches a Ugandan
    number that merely shares trailing digits. Hub numbers with no country code are
    read as Kenyan (the shop's home country). Returns {id, name, phone} or None.
    """
    from app.core.phone import national_digits, same_number
    q = national_digits(wa_id) or "".join(ch for ch in wa_id if ch.isdigit())
    base = settings.hub_api_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                f"{base}/api/v1/admin/pos/customers/search",
                headers=_api_headers(),
                params={"q": q},
            )
            resp.raise_for_status()
            for c in (resp.json() or {}).get("data", []):
                if same_number(wa_id, c.get("phone")):
                    return {"id": c.get("id"), "name": c.get("name"), "phone": c.get("phone")}
    except Exception:
        pass  # dedupe is a nicety — fall back to new_customer
    return None


async def _find_customer_id(wa_id: str) -> int | None:
    """Reuse an existing hub customer by phone so repeat buyers don't duplicate."""
    match = await _search_customer_match(wa_id)
    return match["id"] if match else None


async def _find_customer(wa_id: str) -> dict | None:
    """Like `_find_customer_id` but returns {id, name, phone} of the hub match."""
    return await _search_customer_match(wa_id)


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
            {
                "product_id": l["product_id"], "quantity": l["quantity"],
                "unit_price": l["unit_price"],
                # Variable stock products track inventory per-variant, so the hub
                # needs the variant_id (a bare product_id fails its stock check).
                **({"variant_id": l["variant_id"]} if l.get("variant_id") else {}),
            }
            for l in stock_lines
        ]
    if mto_lines:
        payload["production_items"] = [
            {
                "product_id": l["product_id"],
                "quantity": l["quantity"],
                "unit_price": l["unit_price"],
                **({"variant_id": l["variant_id"]} if l.get("variant_id") else {}),
                # Name carries the chosen variant (e.g. "… (L / GOLD)"); staff
                # still confirm exact measurements with the customer.
                "production_notes": f"WhatsApp order via Neema — {l['name']}. "
                                    "Confirm size/measurements with the customer.",
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


async def create_production_order(
    *,
    wa_id: str,
    first_name: str,
    country_iso: str | None,
    hub_product_id: int,
    product_name: str,
    quantity: int = 1,
    unit_price: float | None = None,
    production_notes: str = "",
) -> dict:
    """Create a made-to-order production order in the hub from a reviewed
    enquiry — a single production line, with the customer's measurements carried
    in `production_notes`. Reuses an existing hub customer by phone. Raises on
    HTTP failure. Returns {order_id, order_number, total_amount, currency_code}."""
    if not hub_product_id:
        raise ValueError("hub_product_id is required to create a production order")

    payload = {
        "outlet_id": settings.hub_outlet_id,
        "channel": "whatsapp",
        "notes": f"Made-to-order via Neema — {product_name}",
        "production_items": [{
            "product_id": hub_product_id,
            "quantity": max(int(quantity or 1), 1),
            "unit_price": float(unit_price or 0),
            "production_notes": production_notes or "Confirm measurements with the customer.",
        }],
    }
    if country_iso:
        payload["customer_country_code"] = country_iso.upper()

    customer_id = await _find_customer_id(wa_id)
    if customer_id:
        payload["customer_id"] = customer_id
    else:
        payload["new_customer"] = {"first_name": first_name or "Customer", "phone": wa_id}

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


def _f(v):
    """Best-effort float; None for blanks/garbage."""
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _map_hub_order(o: dict) -> dict:
    """One hub order → the shape Neema's CRM panel renders."""
    items = []
    for it in (o.get("items") or []):
        qty = it.get("quantity") or 0
        up = _f(it.get("unit_price")) or 0
        tp = _f(it.get("total_price"))
        items.append({
            "name":       (it.get("product_name") or it.get("name") or "").strip(),
            "qty":        qty,
            "quantity":   qty,
            "unit_price": up,
            "total":      tp if tp is not None else up * (qty or 0),
        })
    return {
        "id":             str(o.get("id")),
        "order_number":   o.get("order_number"),
        "status":         o.get("status"),
        "payment_status": o.get("payment_status"),
        "order_type":     o.get("order_type"),
        "total":          _f(o.get("total_amount")),
        "subtotal":       _f(o.get("subtotal")),
        "currency_code":  o.get("currency_code"),
        "created_at":     o.get("created_at"),
        "items":          items,
        "source":         "hub",
    }


async def fetch_customer_summary(wa_id: str, redis=None) -> dict | None:
    """The customer's hub record — lifetime stats + recent orders (POS, web AND
    WhatsApp), resolved by phone.

    This is the source of truth for the CRM panel's orders and the buying-rhythm
    / tier stats: Neema's local order_events only hold WhatsApp-originated sales
    and undercount a repeat buyer who also walks into the shop. Returns
    {customer_id, total_orders, total_spent, avg_order_value, last_order_date,
    orders[]}, or None when the customer can't be resolved in the hub or the hub
    is unreachable — the caller then falls back to the local order_events mirror.
    """
    key = f"hub:customer_summary:{wa_id}"
    if redis is not None:
        try:
            cached = await redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    match = await _find_customer(wa_id)
    if not match:
        return None
    customer_id = match["id"]

    base = settings.hub_api_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base}/api/v1/admin/customers/{customer_id}",
                headers=_api_headers(),
            )
            resp.raise_for_status()
            body = resp.json() or {}
    except Exception:
        _log.warning("hub customer summary fetch failed for %s", wa_id)
        return None

    stats = body.get("stats") or {}
    cust = body.get("customer") or {}
    orders = [_map_hub_order(o) for o in (cust.get("orders") or [])]

    summary = {
        "customer_id":     customer_id,
        "customer_name":   match.get("name"),
        "total_orders":    int(stats.get("total_orders") or 0),
        "total_spent":     _f(stats.get("total_spent")) or 0.0,
        "avg_order_value": _f(stats.get("average_order_value")) or 0.0,
        "last_order_date": stats.get("last_order_date"),
        "orders":          orders,
    }
    if redis is not None:
        try:
            await redis.setex(key, settings.hub_order_status_ttl, json.dumps(summary))
        except Exception:
            pass
    return summary


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
