"""Stock is never a customer topic (owner rule): the model is never shown
"out of stock" or remaining counts — everything is sold as available, and a hub
shortfall becomes a SOURCING flag for the team at order time instead."""
import asyncio
from types import SimpleNamespace

from app.agent import tools
from app.agent.tools import _search_catalog, _sourcing_gaps, _cart_display, ToolContext
from app.agent.prompt import build_system_prompt


def _catalog():
    return [
        {"hub_product_id": 1, "name": "Communion Wafers", "sku": "W1", "price": 800,
         "price_usd": 8, "category": "Communion", "in_stock": False, "available_qty": 0},
        {"hub_product_id": 2, "name": "Communion Cups", "sku": "CU1", "price": 1500,
         "price_usd": 15, "category": "Communion", "in_stock": True, "available_qty": 2},
        {"hub_product_id": 3, "name": "Cassock", "sku": "C1", "price": 12000,
         "price_usd": 120, "category": "Vestments", "product_type": "variable",
         "is_producible": True},
    ]


def test_search_never_exposes_stock_state_or_counts(monkeypatch):
    async def fake_catalog(db, redis):
        return _catalog()
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    ctx = ToolContext(db=None, redis=None, wa_id="254700", currency="KES")

    out = asyncio.run(_search_catalog({"query": "communion"}, ctx))
    for r in out["results"]:
        assert r["availability"] == "available"     # even the out-of-stock wafers
        assert "available_qty" not in r
        assert "in_stock" not in r


def test_cart_display_strips_internal_stock_flag():
    cart = {"items": [{"name": "Communion Wafers", "qty": 500, "unit_price": 800,
                       "hub_product_id": 1, "in_stock": False}]}
    ctx = SimpleNamespace(currency="KES", usd_rate=100, db=None, redis=None)
    items, total = asyncio.run(_cart_display(cart, ctx))
    assert "in_stock" not in items[0]                    # model never sees it
    assert cart["items"][0]["in_stock"] is False         # stored line keeps it


def test_sourcing_gaps_flags_shortfalls_only():
    items = [
        {"hub_product_id": 1, "name": "Communion Wafers", "qty": 500},   # out of stock
        {"hub_product_id": 2, "name": "Communion Cups", "qty": 5},       # only 2 on hand
        {"hub_product_id": 3, "name": "Cassock", "qty": 10},             # made-to-order → never a gap
    ]
    gaps = _sourcing_gaps(items, _catalog())
    assert gaps == ["Communion Wafers ×500 (hub: out of stock)",
                    "Communion Cups ×5 (hub: only 2 on hand)"]
    # covered lines produce no flag
    assert _sourcing_gaps([{"hub_product_id": 2, "name": "Communion Cups", "qty": 2}],
                          _catalog()) == []
    assert _sourcing_gaps([], _catalog()) == []


def test_prompt_forbids_stock_talk():
    for currency in ("KES", "USD"):
        p = build_system_prompt(currency=currency)
        assert "STOCK IS NEVER A CUSTOMER TOPIC" in p
        assert "quote how many remain" in p              # no counts, ever
        assert "sourced before delivery" in p            # team flag, not customer news
