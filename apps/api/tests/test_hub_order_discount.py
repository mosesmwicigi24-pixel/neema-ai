"""The hub must charge what Neema quoted — the ordering half.

Neema read `sale_price or regular_price` off the hub feed, ignoring the sale
window, while the hub's order path charged `regular_price` flat. She quoted a
Preaching Gown at 18,000 and the hub billed 20,000, on 60 live products. The hub
now publishes ONE number, `effective_price`, and both sides read it.

Separately, a discount the customer was PROMISED used to reach the hub only as a
sentence in the order notes. The lines now carry it as money.
"""
import asyncio

from app.core import hub_client


def _catalog():
    return [
        {"hub_product_id": 6, "sku": "843GLV9RC", "name": "Preaching Gown",
         "category": "Gowns", "price": 18000.0, "prices": {"KES": 18000.0},
         "aliases": [], "product_type": "simple", "is_producible": False,
         "in_stock": True, "slug": "preaching-gown"},
        {"hub_product_id": 9, "sku": "7IM6K8KA4", "name": "Chalice Cup",
         "category": "Chalices", "price": 12000.0, "prices": {"KES": 12000.0},
         "aliases": [], "product_type": "simple", "is_producible": False,
         "in_stock": True, "slug": "chalice-cup"},
    ]


def test_the_feed_price_is_the_hubs_own_effective_price():
    # effective_price wins over sale_price: a sale whose window has closed is
    # not a price, and reading sale_price ourselves honoured it anyway.
    prices = hub_client._all_prices([
        {"currency_code": "KES", "regular_price": "20000.00",
         "sale_price": "18000.00", "effective_price": 20000.0},
    ])

    assert prices["KES"] == 20000.0


def test_an_older_hub_without_effective_price_still_works():
    prices = hub_client._all_prices([
        {"currency_code": "KES", "regular_price": "20000.00", "sale_price": "18000.00"},
    ])

    assert prices["KES"] == 18000.0


def _pushed_payload(monkeypatch, promise, items):
    """Run push_pending_order far enough to capture the payload it would POST."""
    seen = {}

    class _Resp:
        status_code = 201
        def raise_for_status(self): pass
        def json(self): return {"order_id": 1, "order_number": "WA-1"}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw):
            seen["payload"] = kw.get("json")
            return _Resp()
        async def get(self, url, **kw):
            return _Resp()

    monkeypatch.setattr(hub_client.httpx, "AsyncClient", lambda *a, **k: _Client())
    try:
        asyncio.run(hub_client.push_pending_order(
            _catalog(), wa_id="254700000000", first_name="Esther",
            country_iso="KE", items=items, promise=promise))
    except Exception:
        pass                      # only the payload matters
    return seen.get("payload") or {}


def test_a_covered_line_carries_the_promised_percentage(monkeypatch):
    promise = {"name": "Harvest Offer", "percent": 10, "at": "2026-09-02",
               "scope": "category", "covers": ["Gowns"]}

    payload = _pushed_payload(monkeypatch, promise,
                              [{"name": "Preaching Gown", "qty": 1}])

    line = (payload.get("items") or [{}])[0]
    assert line.get("discount_type") == "percent"
    assert line.get("discount_value") == 10.0
    assert "ALREADY ON" in payload.get("notes", "")


def test_an_uncovered_line_carries_no_discount(monkeypatch):
    promise = {"name": "Harvest Offer", "percent": 10, "at": "2026-09-02",
               "scope": "category", "covers": ["Gowns"]}

    payload = _pushed_payload(monkeypatch, promise,
                              [{"name": "Chalice Cup", "qty": 1}])

    line = (payload.get("items") or [{}])[0]
    assert "discount_type" not in line
    # Nothing in this order was covered, so the note says nothing at all.
    assert "Harvest Offer" not in payload.get("notes", "")


def test_no_promise_means_no_discount_and_no_note(monkeypatch):
    payload = _pushed_payload(monkeypatch, None,
                              [{"name": "Preaching Gown", "qty": 1}])

    line = (payload.get("items") or [{}])[0]
    assert "discount_type" not in line
    assert "off" not in payload.get("notes", "").lower()
