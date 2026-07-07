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
