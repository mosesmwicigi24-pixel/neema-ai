"""Variant pricing: the agent must SEE each size/colour's own price, quote the
one the customer picks (or a range), and orders must resolve to the exact
variant (right price + variant_id). A Thurible in S is KES 9,000 but L is 15,000."""
import asyncio

from app.core import hub_client as hc
from app.agent import tools
from app.agent.tools import _search_catalog, ToolContext


def _raw_variant(vid, sku, name, attrs, kes, usd, default=False):
    return {"id": vid, "sku": sku, "variant_name": name, "attributes": attrs,
            "is_default": default, "is_active": True,
            "prices": [{"currency_code": "KES", "regular_price": str(kes)},
                       {"currency_code": "USD", "regular_price": str(usd)}]}


def test_map_variant_extracts_price_and_attrs():
    v = hc._map_variant(_raw_variant(100, "COM-T-001-S-GOL", "S / GOLD",
                                     {"Size": "S", "Colour": "GOLD"}, 9000, 90, True))
    assert v["variant_id"] == 100 and v["sku"] == "COM-T-001-S-GOL"
    assert v["attributes"] == {"Size": "S", "Colour": "GOLD"}
    assert v["price_kes"] == 9000.0 and v["price_usd"] == 90.0 and v["is_default"]


def test_apply_variant_pricing_sets_base_and_range():
    prod = {"price": 0.0, "price_kes": None, "price_usd": None, "variants": [
        hc._map_variant(_raw_variant(100, "S", "S / GOLD", {}, 9000, 90, True)),
        hc._map_variant(_raw_variant(101, "L", "L / GOLD", {}, 15000, 150)),
    ]}
    hc._apply_variant_pricing(prod)
    assert prod["price_kes"] == 9000.0 and prod["price"] == 9000.0   # default variant sets base
    assert prod["price_usd"] == 90.0
    assert prod["price_min_kes"] == 9000.0 and prod["price_max_kes"] == 15000.0


def _thurible_catalog():
    return [{
        "hub_product_id": 85, "sku": "COM-T-001", "name": "Thurible", "price": 9000,
        "price_usd": 90, "category": "Communion",
        "product_type": "variable", "is_producible": False,
        "variants": [
            hc._map_variant(_raw_variant(100, "COM-T-001-S-GOL", "S / GOLD", {"Size": "S"}, 9000, 90, True)),
            hc._map_variant(_raw_variant(102, "COM-T-001-L-GOL", "L / GOLD", {"Size": "L"}, 15000, 150)),
        ],
    }]


def test_resolve_hub_line_matches_variant_sku_at_variant_price():
    cat = _thurible_catalog()
    line = hc.resolve_hub_line({"sku": "COM-T-001-L-GOL", "name": "COM-T-001-L-GOL", "qty": 2}, cat)
    assert line["product_id"] == 85 and line["unit_price"] == 15000.0    # the L variant, not the base
    assert line["variant_id"] == 102 and line["variant_sku"] == "COM-T-001-L-GOL"
    assert line["unit_price_usd"] == 150.0 and "L / GOLD" in line["name"]
    # the full variant name resolves too
    line2 = hc.resolve_hub_line({"name": "Thurible L / GOLD", "sku": "", "qty": 1}, cat)
    assert line2["variant_id"] == 102 and line2["unit_price"] == 15000.0
    # a bare product sku (no variant) still resolves to the product at its base price
    line3 = hc.resolve_hub_line({"sku": "COM-T-001", "name": "", "qty": 1}, cat)
    assert line3["product_id"] == 85 and line3.get("variant_id") is None


def test_search_catalog_surfaces_variants_and_range(monkeypatch):
    async def fake_catalog(db, redis):
        return _thurible_catalog()
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)

    # KES customer sees each variant's KES price + the range
    ctx = ToolContext(db=None, redis=None, wa_id="254700", currency="KES")
    r = asyncio.run(_search_catalog({"query": "thurible"}, ctx))["results"][0]
    prices = {v["sku"]: v["price"] for v in r["variants"]}
    assert prices == {"COM-T-001-S-GOL": 9000, "COM-T-001-L-GOL": 15000}
    assert r["price_range"] == {"from": 9000, "to": 15000}

    # USD customer sees the variant USD prices
    ctxu = ToolContext(db=None, redis=None, wa_id="PSID", currency="USD")
    ru = asyncio.run(_search_catalog({"query": "thurible"}, ctxu))["results"][0]
    pu = {v["sku"]: v["price"] for v in ru["variants"]}
    assert pu == {"COM-T-001-S-GOL": 90, "COM-T-001-L-GOL": 150}


def test_push_order_sends_variant_id_and_price(monkeypatch):
    """A variant order carries variant_id (hub needs it for per-variant stock)
    and the variant's unit_price, not the product base."""
    import types
    cat = _thurible_catalog()
    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"order_id": 1, "order_number": "WA-1",
                                "total_amount": 30000, "currency_code": "KES"}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            captured.update(json or {})
            return _Resp()

    async def _no_customer(wa_id): return None
    monkeypatch.setattr(hc.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(hc, "_find_customer_id", _no_customer)

    items = [{"name": "Thurible (L / GOLD)", "sku": "COM-T-001-L-GOL", "qty": 2}]
    out = asyncio.run(hc.push_pending_order(cat, wa_id="254700000001", first_name="Joy",
                                            country_iso="KE", items=items))
    assert out["order_number"] == "WA-1"
    line = captured["items"][0]
    assert line["variant_id"] == 102 and line["unit_price"] == 15000.0 and line["quantity"] == 2


# ── The Simon thread (live, 2026-08-26): "1 straight collar 19 inches" priced
# the DEFAULT 8-inch variant (KES 400) instead of the 19-inch (KES 1,200) —
# opaque variant SKUs (9C0393V3R-19) and a variant name that just repeats the
# product meant nothing matched, and a colleague had to correct it by hand.

_COLLAR = {
    "hub_product_id": 23, "name": "Straight Collar", "sku": "CAC-001-01",
    "price": 400, "product_type": "variable", "is_producible": False,
    "variants": [
        {"variant_id": 81, "sku": "9C0393V3R-8", "name": "Straight Collar",
         "attributes": {"Size": "8 Inches"}, "price_kes": 400.0,
         "prices": {"KES": 400.0}, "is_default": True},
        {"variant_id": 87, "sku": "9C0393V3R-19", "name": "Straight Collar",
         "attributes": {"Size": "19 inches"}, "price_kes": 1200.0,
         "prices": {"KES": 1200.0}},
    ],
}


def test_attribute_words_resolve_the_exact_variant():
    import app.core.hub_client as hc
    line = hc.resolve_hub_line({"name": "1 straight collar 19 inches", "sku": "", "qty": 1},
                               [_COLLAR])
    assert line["unit_price"] == 1200.0            # the 19-inch price, not the default
    assert line["variant_id"] == 87
    assert line["matched_by"] == "variant_attrs"
    # measurement spellings all land on the same variant
    for phrasing in ('straight collar 19"', "straight collar 19 inch", "straight collar, 19-inches"):
        got = hc.resolve_hub_line({"name": phrasing, "sku": "", "qty": 1}, [_COLLAR])
        assert got["variant_id"] == 87, phrasing


def test_no_attribute_words_still_gets_the_base_product():
    import app.core.hub_client as hc
    line = hc.resolve_hub_line({"name": "straight collar", "sku": "", "qty": 1}, [_COLLAR])
    assert line["product_id"] == 23 and line.get("variant_id") is None
    assert line["unit_price"] == 400               # base/default price, honestly


def test_prompt_makes_the_colleagues_answer_supreme():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(currency="KES")
    assert "A COLLEAGUE'S ANSWER OVERRIDES YOURS" in p
    assert "THEY are right and YOUR earlier line was the error" in p
    assert "fix the cart with update_cart" in p
    assert "my colleague was pricing a different item" in p     # the live failure, banned by name
