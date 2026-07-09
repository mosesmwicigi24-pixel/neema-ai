"""Public, unauthenticated storefront — the customer-facing shareable catalog.

Reads the hub's PUBLIC product data (via the same cached client the agent sells
from) and returns ONLY customer-relevant fields. A shared catalog link therefore
never exposes Neema's internal database, order data, customer records, or the
admin surface — the whole point of a customer-faced view.

Mounted at /api/public with NO auth dependency.
"""
from fastapi import APIRouter, Request, HTTPException

from app.core import hub_client

router = APIRouter()


def _card(p: dict) -> dict:
    """The customer-safe projection of a catalogue product."""
    return {
        "slug":          p.get("slug"),
        "name":          p.get("name"),
        "category":      p.get("category"),
        "description":   p.get("description"),
        "price_kes":     p.get("price_kes"),
        "price_usd":     p.get("price_usd"),
        "image_url":     p.get("image_url"),
        "thumbnail_url": p.get("thumbnail_url"),
        # Producible items are made-to-order — the catalog shows "Made to order"
        # rather than a stock count, so they're never wrongly "out of stock".
        "made_to_order": bool(p.get("is_producible")),
        "in_stock":      bool(p.get("in_stock", True)),
    }


async def _catalog(request: Request) -> list[dict]:
    redis = getattr(request.app.state, "redis", None)
    try:
        return await hub_client.fetch_hub_catalog(redis)
    except Exception:
        raise HTTPException(status_code=503, detail="Catalog temporarily unavailable")


@router.get("/catalog")
async def public_catalog(request: Request):
    """Every sellable product as a customer card (name + price + image)."""
    items = await _catalog(request)
    return [_card(p) for p in items if p.get("name") and p.get("slug")]


@router.get("/catalog/{slug}")
async def public_product(slug: str, request: Request):
    """One product's detail — includes the full image gallery."""
    items = await _catalog(request)
    p = next((x for x in items if x.get("slug") == slug), None)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    card = _card(p)
    card["images"] = p.get("images") or []
    return card
