"""ONE PRODUCT, ONE CART LINE (2026-10-05).

The cart found its lines by the WORDS used to name them, so one product could
be two lines: the tray reached by its SKU and then by its storefront slug, or
a variant saved under a label the catalogue has since renamed. A cart like
that totals double, and an order placed from it bills twice. Pinned here: a
product is one line whatever names it (SKU, slug, name, alias) — `set` sets
that line, `add` accumulates on it; different variants stay apart; an add on
top of an item already in the cart says so; and the order payload never
carries the same product + variant twice.
"""
import asyncio

import app.main  # noqa: F401
from app.agent import cart as cartmod
from app.agent import tools
from app.agent.tools import ToolContext
from app.core import hub_client

TRAY = {"hub_product_id": 50, "sku": "XYULGK29K-5D98", "slug": "golden-communion-tray",
        "name": "Golden Communion Tray", "price": 22000, "price_usd": 198,
        "prices": {"KES": 22000, "USD": 198}, "aliases": ["gold communion tray"],
        "category": "Communion Items", "product_type": "simple", "is_producible": False,
        "in_stock": True, "variants": []}
COLLAR = {"hub_product_id": 2, "sku": "COL", "slug": "straight-collar", "name": "Straight Collar",
          "price": 400, "price_usd": 4, "prices": {"KES": 400, "USD": 4}, "aliases": [],
          "category": "Clergy Accessories", "product_type": "variable", "is_producible": False,
          "in_stock": True,
          "variants": [
              {"variant_id": 22, "sku": "COL-10", "name": "10 inch", "attributes": {"Size": "10 inch"},
               "price_kes": 400, "price_usd": 4, "prices": {"KES": 400, "USD": 4},
               "label": "Straight Collar — 10 inch"},
              {"variant_id": 23, "sku": "COL-12", "name": "12 inch", "attributes": {"Size": "12 inch"},
               "price_kes": 500, "price_usd": 5, "prices": {"KES": 500, "USD": 5},
               "label": "Straight Collar — 12 inch"}]}
CATALOG = [TRAY, COLLAR]


class _DB:
    async def commit(self):
        pass


def _rig(monkeypatch, start=None):
    store = {"items": list(start or [])}

    async def fake_cart(db_, wa_id, channel="whatsapp"):
        return {"items": [dict(i) for i in store["items"]]}

    async def fake_save(db_, wa_id, cart, channel="whatsapp"):
        store["items"] = [dict(i) for i in cart["items"]]
        return cart

    async def fake_catalog(db_, redis_):
        return CATALOG
    monkeypatch.setattr(cartmod, "get_cart", fake_cart)
    monkeypatch.setattr(cartmod, "save_cart", fake_save)
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    ctx = ToolContext(db=_DB(), redis=None, wa_id="254700000009", currency="KES", channel="whatsapp")

    def call(action, product, quantity=None):
        args = {"action": action, "product": product}
        if quantity is not None:
            args["quantity"] = quantity
        return asyncio.run(tools._update_cart(args, ctx))
    return store, call


def test_sku_then_slug_is_one_line_with_set_semantics(monkeypatch):
    store, call = _rig(monkeypatch)
    assert call("set", "XYULGK29K-5D98", 1)["ok"]
    out = call("set", "golden-communion-tray", 1)
    assert out["ok"], out
    assert [(i["hub_product_id"], i["qty"]) for i in store["items"]] == [(50, 1)]
    assert out["total"] == 22000


def test_name_alias_and_sku_all_land_on_the_same_line(monkeypatch):
    store, call = _rig(monkeypatch)
    call("set", "Golden Communion Tray", 1)
    call("set", "gold communion tray", 2)
    out = call("set", "XYULGK29K-5D98", 3)
    assert len(store["items"]) == 1 and store["items"][0]["qty"] == 3
    assert out["total"] == 3 * 22000


def test_add_twice_accumulates_on_one_line_and_says_so(monkeypatch):
    store, call = _rig(monkeypatch)
    first = call("add", "XYULGK29K-5D98")
    assert "note" not in first
    out = call("add", "golden-communion-tray")
    assert len(store["items"]) == 1 and store["items"][0]["qty"] == 2
    assert out["total"] == 44000
    # the doubling is never silent: the model reads what add did
    assert "already in the cart ×1" in out["note"] and "set" in out["note"]


def test_two_variants_are_two_lines_and_the_total_is_right(monkeypatch):
    store, call = _rig(monkeypatch)
    call("add", "COL-10")
    call("add", "Straight Collar — 12 inch")
    out = call("set", "COL-10", 2)
    assert sorted((i["sku"], i["qty"]) for i in store["items"]) == [("COL-10", 2), ("COL-12", 1)]
    assert out["total"] == 2 * 400 + 500


def test_a_line_saved_under_an_old_label_is_still_that_line(monkeypatch):
    # saved before the variant label rule changed ("…(10 inch)" → "… — 10 inch")
    old = {"hub_product_id": 2, "name": "Straight Collar (10 inch)", "sku": "COL-10",
           "qty": 1, "unit_price": 400}
    store, call = _rig(monkeypatch, start=[old, dict(old)])   # an old cart even holds it twice
    out = call("set", "COL-10", 1)
    assert [(i["sku"], i["qty"]) for i in store["items"]] == [("COL-10", 1)]
    assert out["total"] == 400


def test_removing_by_slug_takes_the_line_and_unknown_items_are_still_refused(monkeypatch):
    store, call = _rig(monkeypatch)
    call("set", "Golden Communion Tray", 1)
    call("add", "COL-10")
    assert call("remove", "golden-communion-tray")["ok"]
    assert [i["hub_product_id"] for i in store["items"]] == [2]
    out = call("add", "Brass Thurible")
    assert "not found in the catalogue" in out["error"]
    assert [i["hub_product_id"] for i in store["items"]] == [2]


def test_the_order_payload_never_carries_one_product_twice(monkeypatch):
    sent = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"order_id": 1, "order_number": "WA-1", "total_amount": 800, "currency_code": "KES"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent["payload"] = json
            return _Resp()

    async def no_customer(wa_id, proven=False):
        return None
    monkeypatch.setattr(hub_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(hub_client, "_find_customer_id", no_customer)
    items = [
        {"hub_product_id": 50, "name": "Golden Communion Tray", "sku": "XYULGK29K-5D98", "qty": 1},
        {"hub_product_id": 50, "name": "Golden Communion Tray", "sku": "golden-communion-tray", "qty": 1},
        {"hub_product_id": 2, "name": "Straight Collar — 10 inch", "sku": "COL-10", "qty": 1},
        {"hub_product_id": 2, "name": "Straight Collar — 12 inch", "sku": "COL-12", "qty": 1},
    ]
    asyncio.run(hub_client.push_pending_order(CATALOG, wa_id="254700000009", first_name="Joy",
                                              country_iso="KE", items=items))
    lines = sent["payload"]["items"]
    keys = [(i["product_id"], i.get("variant_id")) for i in lines]
    assert len(keys) == len(set(keys)) == 3
    assert next(i for i in lines if i["product_id"] == 50)["quantity"] == 2
