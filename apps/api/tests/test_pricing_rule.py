"""The one pricing rule (app/core/pricing.py), applied on every channel:
  Kenya → KES · hub-priced local currency → that price · else convert USD→local
  when we know a rate · else USD.

Plus the chat surfaces (search_catalog rows, product cards) quoting local currency.
Pure/fake-db style, no DB fixture.
"""
import asyncio
from types import SimpleNamespace

import app.main  # noqa: F401 — registers models
import app.agent.tools as tools
import app.services.n8n_bridge as svc
from app.agent.tools import ToolContext
from app.core import pricing
from app.core.config import settings


# ── the canonical pricer ──────────────────────────────────────────────────────

def test_kenya_is_kes():
    assert pricing.resolve_price({"KES": 12000, "USD": 95}, "KES", kes_rate=100) == (12000, "KES")
    # KES derived from USD when the hub has no KES
    assert pricing.resolve_price({"USD": 100}, "KES", kes_rate=100) == (10000, "KES")


def test_explicit_hub_local_price_wins():
    # Hub prices this item in ZMW → the Zambian sees that exact price, not a conversion.
    assert pricing.resolve_price({"KES": 12000, "USD": 95, "ZMW": 2500}, "ZMW", kes_rate=100) == (2500, "ZMW")


def test_fallback_converts_usd_to_local_when_rate_known(monkeypatch):
    monkeypatch.setattr(settings, "fx_usd_rates", "", raising=False)
    # No ZMW hub price → USD = 12000/100 = 120, then × ZMW rate (27) = 3240.
    amount, cur = pricing.resolve_price({"KES": 12000}, "ZMW", kes_rate=100)
    assert cur == "ZMW"
    assert amount == round(120 * pricing.usd_rate_for("ZMW"))
    # UGX from a real hub USD price: 95 USD × 3800 = 361000.
    amount2, cur2 = pricing.resolve_price({"USD": 95}, "UGX", kes_rate=100)
    assert cur2 == "UGX" and amount2 == round(95 * pricing.usd_rate_for("UGX"))


def test_unknown_currency_falls_back_to_usd():
    # A currency with no rate configured → USD (never a wrong local number).
    amount, cur = pricing.resolve_price({"KES": 12000}, "XYZ", kes_rate=100)
    assert cur == "USD" and amount == 120


def test_non_kenya_default_usd():
    assert pricing.resolve_price({"KES": 10000}, "USD", kes_rate=100) == (100, "USD")
    assert pricing.resolve_price({"USD": 95, "KES": 12000}, "USD", kes_rate=100) == (95, "USD")


def test_fx_env_override(monkeypatch):
    monkeypatch.setattr(settings, "fx_usd_rates", '{"ZMW": 30}', raising=False)
    assert pricing.usd_rate_for("ZMW") == 30
    amount, cur = pricing.resolve_price({"KES": 12000}, "ZMW", kes_rate=100)
    assert cur == "ZMW" and amount == round(120 * 30)


def test_small_item_keeps_cents_never_zero():
    # A KES 20 cup for a USD viewer → $0.20, never $0.
    assert pricing.resolve_price({"KES": 20}, "USD", kes_rate=100) == (0.2, "USD")


def test_fmt_price_keeps_cents_for_all_currencies():
    # A sub-unit near-parity currency must never read as free ("EUR 0").
    assert tools._fmt_price(0.4, "GBP") == "GBP 0.40"
    assert tools._fmt_price(0.37, "EUR") == "EUR 0.37"
    assert tools._fmt_price(0.4, "USD") == "$0.40"
    assert tools._fmt_price(57000, "UGX") == "UGX 57,000"
    assert tools._fmt_price(12000, "KES") == "KES 12,000"


# ── chat surfaces quote local currency ────────────────────────────────────────

def _ctx(currency, rate=100):
    return ToolContext(db=object(), redis=None, wa_id="254712345678",
                       channel="whatsapp", currency=currency, usd_rate=rate)


def test_search_catalog_quotes_local_currency(monkeypatch):
    async def fake_catalog(db, redis):
        return [{"name": "Cassock", "sku": "C1", "slug": "cassock",
                 "prices": {"KES": 12000, "USD": 95}, "price": 12000, "price_usd": 95}]
    monkeypatch.setattr(svc, "catalog_items", fake_catalog)
    monkeypatch.setattr(settings, "fx_usd_rates", "", raising=False)

    out = asyncio.run(tools._search_catalog({"query": "cassock"}, _ctx("UGX")))
    assert out["currency"] == "UGX"
    row = out["results"][0]
    assert row["currency"] == "UGX"
    assert row["price"] == round(95 * pricing.usd_rate_for("UGX"))   # hub USD × rate

    # Kenyan still sees raw KES.
    out_ke = asyncio.run(tools._search_catalog({"query": "cassock"}, _ctx("KES")))
    assert out_ke["results"][0]["price"] == 12000 and out_ke["results"][0]["currency"] == "KES"


def test_product_card_price_text_local_currency(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "https://shop.example", raising=False)
    monkeypatch.setattr(tools, "_customer_currency", _acoro("UGX"))
    async def fake_catalog(db, redis):
        return [{"name": "Ring", "sku": "R1", "slug": "ring",
                 "prices": {"KES": 1500, "USD": 15}, "price": 1500, "price_usd": 15,
                 "thumbnail_url": "https://i/r.jpg"}]
    monkeypatch.setattr(svc, "catalog_items", fake_catalog)
    monkeypatch.setattr(settings, "fx_usd_rates", "", raising=False)
    sent = []
    async def fake_card(wa_id, *, image_url, title, body, url, button="View"):
        sent.append(body)
    monkeypatch.setattr(svc, "_send_waba_product_card", fake_card)

    out = asyncio.run(tools._send_product_cards({"products": ["Ring"]}, _ctx("UGX")))
    assert out["sent_cards"] == 1
    assert sent[0] == f"UGX {round(15 * pricing.usd_rate_for('UGX')):,}"   # e.g. "UGX 57,000"


def _acoro(value):
    async def f(*a, **k):
        return value
    return f
