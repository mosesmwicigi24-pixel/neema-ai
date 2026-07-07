"""Unit tests for hub order-line resolution (Part B) — pure, no network.

A confirmed WhatsApp cart carries {name, qty, unit, sku?} but no hub product id;
`resolve_hub_line` must map each line back to a hub product against the cached
catalogue, using the hub's own price. These tests pin the matching precedence
(sku → name → alias → substring) that the order push depends on.
"""
from app.core.hub_client import resolve_hub_line

CATALOG = [
    {"hub_product_id": 11, "sku": "WAFER-500", "name": "Holy Communion Wafers (500 pcs)",
     "price": 850.0, "aliases": ["wafers", "hosts", "eucharist wafers"], "in_stock": True},
    {"hub_product_id": 22, "sku": "OIL-100", "name": "Anointing Oil 100ml",
     "price": 400.0, "aliases": ["holy oil"], "in_stock": True},
    {"hub_product_id": 33, "sku": "CASSOCK-BLK", "name": "Black Cassock",
     "price": 6500.0, "aliases": [], "in_stock": True},
]


def test_matches_by_exact_sku():
    line = resolve_hub_line({"name": "whatever", "sku": "oil-100", "qty": 2}, CATALOG)
    assert line["product_id"] == 22
    assert line["quantity"] == 2
    assert line["unit_price"] == 400.0        # hub price, not the AI's quote
    assert line["matched_by"] == "sku"


def test_matches_by_exact_name_case_insensitive():
    line = resolve_hub_line({"name": "black cassock", "qty": 1}, CATALOG)
    assert line["product_id"] == 33
    assert line["matched_by"] == "name"


def test_matches_by_alias():
    line = resolve_hub_line({"name": "hosts", "qty": 3}, CATALOG)
    assert line["product_id"] == 11
    assert line["matched_by"] == "alias"


def test_matches_by_substring():
    line = resolve_hub_line({"name": "anointing oil", "qty": 1}, CATALOG)
    assert line["product_id"] == 22
    assert line["matched_by"] == "contains"


def test_uses_hub_price_over_ai_quote():
    # Even if the AI quoted a wrong unit, the hub price wins (server-authoritative).
    line = resolve_hub_line({"name": "Black Cassock", "qty": 1, "unit": 1.0}, CATALOG)
    assert line["unit_price"] == 6500.0


def test_falls_back_to_quoted_unit_when_catalogue_price_missing():
    cat = [{"hub_product_id": 44, "sku": "X", "name": "Mystery Item", "price": 0, "aliases": []}]
    line = resolve_hub_line({"name": "Mystery Item", "qty": 1, "unit": 123.0}, cat)
    assert line["unit_price"] == 123.0


def test_quantity_defaults_to_one_and_floors_at_one():
    assert resolve_hub_line({"name": "Black Cassock"}, CATALOG)["quantity"] == 1
    assert resolve_hub_line({"name": "Black Cassock", "qty": 0}, CATALOG)["quantity"] == 1
    assert resolve_hub_line({"name": "Black Cassock", "quantity": "4"}, CATALOG)["quantity"] == 4


def test_no_match_returns_none():
    assert resolve_hub_line({"name": "incense burner", "qty": 1}, CATALOG) is None
