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


def test_the_size_the_attributes_carry_joins_the_colour_the_name_carries():
    """Live, 2026-09-25: the cassocks, dresses, shirts and sprinklers name
    the colour and keep the size in the attributes — five 'Black Pleats'
    rows read the same. Every attribute the name does not say rides along;
    a bare code rides with its key."""
    assert variant_label("Red Apostolic Cassock",
                         {"name": "Red Apostolic Cassock + Black Pleats, Piping and Buttons",
                          "attributes": {"Pleats": "Black", "Size": "M"}}) == "Red Apostolic Cassock — Black Pleats, Piping and Buttons / Size M"
    assert variant_label("Straight Collar Shirt", {"name": "Navy Straight Collar Shirt",
                                                   "attributes": {"Colour": "Navy", "Size": "L"}}) == "Straight Collar Shirt — Navy / Size L"
    assert variant_label("Sprinkler (Aspergillum)", {"name": "Brass sprinkler",
                                                     "attributes": {"Finish": "Brass", "Size": "Small"}}) == "Sprinkler (Aspergillum) — Brass sprinkler / Small"
    assert variant_label("Ladies Princes Dress", {"name": "Red", "attributes": {"Colour": "Red", "Size": "Size 12"}}) == "Ladies Princes Dress — Red / Size 12"
    assert variant_label("BELL", {"name": "", "attributes": {"Size": "S"}}) == "BELL — Size S"
    assert variant_label("Straight Collar", {"name": "Straight Collar", "attributes": {"size": "8"}}) == "Straight Collar — Size 8"
    # what the name already says is not said twice
    assert variant_label("Thurible", {"name": "S / GOLD", "attributes": {"Size": "S", "Colour": "GOLD"}}) == "Thurible — S / GOLD"
    assert variant_label("Cassock", {"name": "Black", "attributes": {"Colour": "black"}}) == "Cassock — Black"


def test_the_hubs_plus_and_a_copy_of_the_product_name_even_misspelt_are_not_what_tells_it_apart():
    # "+ Black Pleats…": the hub's plus is a join, not a word
    assert variant_label("Red Apostolic Cassock", {"name": "+ Red Pleats, Piping and Buttons",
                                                   "attributes": {"Size": "XL"}}) == "Red Apostolic Cassock — Red Pleats, Piping and Buttons / Size XL"
    # "INCENSE BURNER/THURBLE" is the product's name with a typo: the size tells the two apart
    assert variant_label("Incense Burner / Thurible", {"name": "INCENSE BURNER/THURBLE", "attributes": {"Size": "M"}}) == "Incense Burner / Thurible — Size M"
    assert variant_label("Incense Burner / Thurible", {"name": "INCENSE BURNER/THURBLE", "attributes": {}}) == "Incense Burner / Thurible"
    assert variant_label("Cassock", {"name": "Cassocks", "attributes": {"Colour": "Black"}}) == "Cassock — Black"
    # a leading run of the product's words goes; a variant that merely starts
    # with the product's first word keeps it
    assert variant_label("Holy Communion Bread 1000 Pcs",
                         {"name": "Holy Communion Bread -500PCS + 200, 500 and 1000"}) == "Holy Communion Bread 1000 Pcs — 500PCS + 200, 500 and 1000"
    assert variant_label("Red Apostolic Cassock", {"name": "Red Pleats"}) == "Red Apostolic Cassock — Red Pleats"
    assert variant_label("Chasuble", {"name": "Chasuble Set"}) == "Chasuble — Set"


def test_the_public_card_shows_each_distinct_variant_once():
    from app.routers.public import _card
    p = {"slug": "red-apostolic-cassock", "name": "Red Apostolic Cassock", "category": "Clergy", "description": "",
         "prices": {"KES": 21000, "USD": 170}, "image_url": "", "variants": [
             {"name": "+ Black Pleats, Piping and Buttons", "attributes": {}, "prices": {"USD": 170}},
             {"name": "+ Black Pleats, Piping and Buttons", "attributes": {}, "prices": {"USD": 170}},
             {"name": "+ Black Pleats, Piping and Buttons", "attributes": {}, "prices": {"USD": 170}},
             {"name": "+ White Pleats, Piping and Buttons", "attributes": {}, "prices": {"USD": 170}},
             {"name": "+ White Pleats, Piping and Buttons", "attributes": {}, "prices": {"USD": 180}},
         ]}
    rows = [(v["label"], v["price"]) for v in _card(p, "USD")["variants"]]
    assert rows == [("Red Apostolic Cassock — Black Pleats, Piping and Buttons", 170),
                    ("Red Apostolic Cassock — White Pleats, Piping and Buttons", 170),
                    ("Red Apostolic Cassock — White Pleats, Piping and Buttons", 180)]
    # sized in the attributes, every size is its own line
    for v, size in zip(p["variants"], ("S", "M", "L", "S", "M")):
        v["attributes"] = {"Size": size}
    assert len(_card(p, "USD")["variants"]) == 5


def test_variants_that_read_the_same_at_different_prices_never_hold_a_reply():
    """Until the hub tells them apart, three 'Brass sprinkler' rows at three
    prices are a range to the verifier — soft, never a hard finding."""
    from app.agent import review as rv
    p = {"name": "Sprinkler (Aspergillum)", "price": 10000, "price_usd": 100, "variants": [
        {"name": "Brass sprinkler", "attributes": {}, "price_kes": 7500, "price_usd": 80},
        {"name": "Brass sprinkler", "attributes": {}, "price_kes": 9000, "price_usd": 90},
        {"name": "Brass sprinkler", "attributes": {}, "price_kes": 14000, "price_usd": 140},
        {"name": "Silver sprinkler", "attributes": {}, "price_kes": 7000, "price_usd": 70},
    ]}
    label_variants([p])
    found = rv.variant_issues("brass one", "The brass sprinkler is $90.", p)
    assert all(not f["hard"] for f in found)
    assert rv.variant_issues("brass one", "The brass sprinkler is from $80 to $140 by size — which size?", p) == []
    # told apart by size, the named one is checked at its own price
    for v, size in zip(p["variants"], ("Small", "Medium", "Large", "Small")):
        v["attributes"] = {"Size": size}
    label_variants([p])
    bad = rv.variant_issues("the small brass", "The small brass sprinkler is $90.", p)
    assert bad and bad[0]["hard"] and "USD 80" in bad[0]["text"]
    assert rv.variant_issues("the small brass", "The Sprinkler (Aspergillum) — Brass sprinkler / Small is $80.", p) == []
