"""The shared customer catalog speaks each customer's own money: Kenya → KES,
Zambia → ZMW, everyone else → USD — from the hub's multi-currency price map,
falling back to USD (real or approximated) when the hub doesn't price their
currency, so an international viewer never sees shillings or a $0."""
from app.routers.public import _card, _resolve_price
from app.core.countries import currency_for_country
from app.core.hub_client import _all_prices


def test_currency_for_country():
    assert currency_for_country("KE") == "KES"
    assert currency_for_country("ZM") == "ZMW"
    assert currency_for_country("ug") == "UGX"
    assert currency_for_country("US") == "USD"
    assert currency_for_country("XX") == "USD"          # unknown → USD
    assert currency_for_country(None) == "USD"


def test_all_prices_drops_zero_and_bogus_codes():
    raw = [{"currency_code": "KES", "regular_price": "3500.00"},
           {"currency_code": "USD", "regular_price": "0.00"},      # zero → dropped
           {"currency_code": "ZMW", "regular_price": "1260.00"},
           {"currency_code": "260", "regular_price": "5.00"},      # not a 3-letter code
           {"currency_code": "KES", "regular_price": "2500.03"}]   # last positive wins
    assert _all_prices(raw) == {"KES": 2500.03, "ZMW": 1260.0}


def test_resolve_price_speaks_each_customers_currency(monkeypatch):
    from app.core.config import settings
    from app.core.pricing import usd_rate_for
    monkeypatch.setattr(settings, "usd_kes_rate", 100, raising=False)
    monkeypatch.setattr(settings, "fx_usd_rates", "", raising=False)
    prices = {"KES": 12000, "USD": 120, "ZMW": 1680}
    assert _resolve_price(prices, "KES") == (12000, "KES")
    assert _resolve_price(prices, "USD") == (120, "USD")
    assert _resolve_price(prices, "ZMW") == (1680, "ZMW")        # hub-priced local wins
    # Not priced in UGX but we know a rate → convert USD → UGX (the fallback rule).
    assert _resolve_price(prices, "UGX") == (round(120 * usd_rate_for("UGX")), "UGX")
    # A currency with no rate → USD (never a wrong local number).
    assert _resolve_price(prices, "XYZ") == (120, "USD")
    # only KES priced: Kenyan sees KES; a Zambian sees converted ZMW; unknown → USD
    assert _resolve_price({"KES": 5000}, "KES") == (5000, "KES")
    assert _resolve_price({"KES": 5000}, "ZMW") == (round(50 * usd_rate_for("ZMW")), "ZMW")
    assert _resolve_price({"KES": 5000}, "XYZ") == (50, "USD")   # 5000/100, no rate
    assert _resolve_price({"KES": 30}, "USD") == (0.3, "USD")   # small item keeps cents
    # Kenyan but only USD priced → converted to KES
    assert _resolve_price({"USD": 10}, "KES") == (1000, "KES")


def test_card_prices_product_and_variants_in_customer_currency():
    p = {"slug": "thurible", "name": "Thurible", "category": "Communion",
         "description": "x", "prices": {"KES": 12000, "USD": 120, "ZMW": 1680},
         "image_url": "http://x", "is_producible": False, "in_stock": True,
         "variants": [
             {"name": "S / GOLD", "attributes": {"Size": "S"},
              "prices": {"KES": 9000, "USD": 90, "ZMW": 1260}},
             {"name": "L / GOLD", "attributes": {"Size": "L"},
              "prices": {"KES": 15000, "USD": 150, "ZMW": 2100}},
         ]}
    z = _card(p, "ZMW")
    assert z["currency"] == "ZMW" and z["price"] == 1680
    labels = {v["label"]: v for v in z["variants"]}
    assert labels["S / GOLD"]["price"] == 1260 and labels["S / GOLD"]["currency"] == "ZMW"
    assert z["price_from"] == 1260 and z["price_to"] == 2100

    u = _card(p, "USD")
    assert u["currency"] == "USD" and u["price"] == 120 and u["price_from"] == 90
