"""WHERE EACH FACT COMES FROM, AND HOW OLD THE COPY IS (owner, 2026-11-16:
"every aspect of this app should get its first-hand information, the truth
from the hub").

For /api/health: one row per business fact Neema uses — its source (hub, or
Neema's own copy) and, for a hub fact, how fresh the copy in hand is. So
drift is seen on a page, not found in a wrong reply. Names and ages only: no
price, no customer, no secret.
"""
from __future__ import annotations

import time

from app.core.config import settings

# The facts Neema still holds itself. Each leaves this list when the hub
# provides it (docs/intelligence/HUB_INTEGRATION_PLAN.md, stage B).
OWN_COPY = (
    ("business_profile", "address, hours, phone lines, payment lines"),
    ("delivery", "fees, courier, transit times, pickup"),
    ("lead_times", "production lead times"),
    ("offers", "campaigns set in the dashboard"),
    ("customer_profile", "name, parish, measurements"),
    ("product_knowledge", "set contents, companions, other names"),
    ("carts_and_quotations", "carts in progress, quotations"),
    ("staff", "accounts and roles"),
)


async def read(redis) -> dict:
    from app.services import fx
    hub_on = (settings.catalog_source or "").lower() == "hub"
    out: dict = {"hub": [], "own_copy": [{"fact": k, "what": v} for k, v in OWN_COPY]}

    async def has(key: str) -> bool:
        if redis is None:
            return False
        try:
            return bool(await redis.exists(key))
        except Exception:
            return False

    fresh = await has("hub:catalog")
    stale = await has("hub:catalog:last_good")
    out["hub"].append({
        "fact": "catalogue_and_prices",
        "source": "hub" if hub_on else "neema_table",
        "copy": "fresh" if fresh else ("last_good" if stale else "none"),
        "refresh_seconds": int(settings.hub_catalog_ttl or 0)})
    rates = dict(fx._HUB_PER.get("rates") or {})
    out["hub"].append({"fact": "currency_rates", "source": "hub_product_prices" if rates else "settings",
                       "kes_per_unit": rates})
    out["hub"].append({"fact": "orders_and_payments", "source": "hub",
                       "configured": bool(settings.hub_api_token)})
    last = None
    if redis is not None:
        try:
            raw = await redis.get("hubevents:last_at")
            if raw:
                from datetime import datetime
                txt = raw if isinstance(raw, str) else raw.decode()
                last = datetime.fromisoformat(txt).timestamp()
        except Exception:
            last = None
    out["hub"].append({"fact": "order_events", "source": "hub",
                       "last_event_seconds_ago": int(time.time() - last) if last else None})
    out["hub"].append({"fact": "customer_order_history", "source": "hub" if settings.hub_api_token else "neema_mirror"})
    return out
