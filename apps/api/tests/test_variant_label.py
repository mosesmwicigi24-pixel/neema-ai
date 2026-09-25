"""ONE name for a variant, everywhere (owner, 2026-09-25: "take the variant +
attribute to get the product name and size, and apply it to all variants")."""
import asyncio

from app.core import hub_client as hc
from app.core.variants import label_variants, variant_label


def test_the_label_is_the_product_plus_what_tells_the_variant_apart():
    assert variant_label("Straight Collar", {"name": "Straight Collar", "attributes": {"Size": "8 inch"}}) == "Straight Collar — 8 inch"
    assert variant_label("Straight Collar Shirt", {"name": "Navy Straight Collar Shirt", "attributes": {"Colour": "Navy"}}) == "Straight Collar Shirt — Navy"
    assert variant_label("Thurible", {"name": "S / GOLD", "attributes": {"Size": "S", "Colour": "GOLD"}}) == "Thurible — S / GOLD"
    # no attributes: the hub's variant name, minus the product's name inside it
    assert variant_label("Straight Collar Shirt", {"name": "Navy Straight Collar Shirt", "attributes": {}}) == "Straight Collar Shirt — Navy"
    assert variant_label("Thurible", {"name": "L / GOLD"}) == "Thurible — L / GOLD"
    # nothing tells it apart: the product's name, never a made-up size
    assert variant_label("Straight Collar", {"name": "Straight Collar", "attributes": {}}) == "Straight Collar"
    assert variant_label("Straight Collar", {"name": "", "attributes": {}}) == "Straight Collar"
    # no product name: the attributes alone
    assert variant_label("", {"name": "", "attributes": {"Colour": "Navy"}}) == "Navy"
    assert variant_label(None, None) == ""


def test_every_variant_of_every_product_is_labelled_in_place():
    items = [{"name": "Straight Collar", "variants": [
                  {"name": "Straight Collar", "attributes": {"Size": "8 inch"}},
                  {"name": "Straight Collar", "attributes": {"Size": "10 inch"}}]},
             {"name": "Cassock", "variants": []},
             {"name": "Thurible", "variants": [{"name": "S / GOLD", "attributes": {"Size": "S"}}]}]
    label_variants(items)
    assert [v["label"] for v in items[0]["variants"]] == ["Straight Collar — 8 inch", "Straight Collar — 10 inch"]
    assert items[2]["variants"][0]["label"] == "Thurible — S / GOLD"      # the hub's richer name wins
    src = open(hc.__file__, encoding="utf-8").read()
    assert "label_variants([p])" in src            # stamped as the hub's variants are loaded


def _collar():
    return [{"hub_product_id": 23, "sku": "ACC-COL", "name": "Straight Collar", "price": 400, "price_usd": 10,
             "category": "Clergy Accessories", "product_type": "variable", "is_producible": False,
             "variants": [
                 {"variant_id": 1, "sku": "ACC-COL-8", "name": "Straight Collar", "attributes": {"Size": "8 inch"},
                  "price_kes": 350, "price_usd": 3.5, "prices": {"KES": 350, "USD": 3.5}, "in_stock": True},
                 {"variant_id": 2, "sku": "ACC-COL-10", "name": "Straight Collar", "attributes": {"Size": "10 inch"},
                  "price_kes": 400, "price_usd": 4, "prices": {"KES": 400, "USD": 4}, "in_stock": True},
             ]}]


def test_a_cart_line_resolves_by_the_label_at_the_variants_price():
    cat = _collar()
    line = hc.resolve_hub_line({"name": "Straight Collar — 10 inch", "sku": "", "qty": 3}, cat)
    assert line["variant_id"] == 2 and line["unit_price"] == 400.0 and line["unit_price_usd"] == 4
    assert line["name"] == "Straight Collar — 10 inch" and line["quantity"] == 3
    # said without the dash, or by SKU, the same variant
    assert hc.resolve_hub_line({"name": "straight collar 8 inch", "sku": "", "qty": 1}, cat)["variant_id"] == 1
    assert hc.resolve_hub_line({"name": "", "sku": "ACC-COL-8", "qty": 1}, cat)["unit_price"] == 350.0


def test_the_agent_sees_the_label_on_every_variant_row(monkeypatch):
    from app.agent import tools
    from app.services import promotions as promo

    async def items(db, redis):
        return _collar()

    async def none(redis):
        return None
    monkeypatch.setattr(tools.svc, "catalog_items", items)
    monkeypatch.setattr(promo, "campaign_now", none)
    ctx = tools.ToolContext(db=None, redis=None, wa_id="PSID", channel="messenger", currency="USD", read_only=True)
    r = asyncio.run(tools._search_catalog({"query": "straight collar"}, ctx))["results"][0]
    assert [(v["label"], v["price"]) for v in r["variants"]] == [("Straight Collar — 8 inch", 3.5), ("Straight Collar — 10 inch", 4)]
    assert r["price_range"] == {"from": 3.5, "to": 4}


def test_the_public_card_and_the_verifier_read_the_same_label():
    from app.routers.public import _card
    from app.agent import review as rv
    p = _collar()[0]
    p["prices"] = {"KES": 400, "USD": 10}
    labels = [v["label"] for v in _card(p, "USD")["variants"]]
    assert labels == ["Straight Collar — 8 inch", "Straight Collar — 10 inch"]
    assert [lab for lab, _k, _u in rv.variants_of(p)] == labels
    # the distinctive words are the sizes, so "the 10 inch" names one variant
    assert rv.variant_issues("the 10 inch", "The Straight Collar — 10 inch is $4.", p) == []
    bad = rv.variant_issues("the 10 inch", "The 10 inch collar is $3.50.", p)
    assert bad and bad[0]["hard"] and "10 inch variant is priced KES 400 / USD 4" in bad[0]["text"]
