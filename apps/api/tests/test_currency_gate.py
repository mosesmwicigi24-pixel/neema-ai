"""Currency display gate (pure + light async, no DB).

Rule: Kenya (+254) customers are quoted KES; everyone else — and all
Messenger/IG, which carry no phone — is quoted USD. USD prefers the hub's own
`price_usd`, falling back to round(KES / usd_kes_rate) when the hub has none.
Conversion happens in the tools; the LLM only quotes what it's handed.
"""
import asyncio
from types import SimpleNamespace

from app.agent import tools
from app.agent.tools import _display, _to_display, _cart_display
from app.agent.prompt import build_system_prompt


def _ctx(currency="KES", rate=100):
    # The converters only read .currency/.usd_rate (+ .db/.redis for the USD cart
    # path), so a light stub is enough.
    return SimpleNamespace(currency=currency, usd_rate=rate, db=None, redis=None)


def test_display_converts_only_for_usd():
    usd, kes = _ctx("USD"), _ctx("KES")
    assert _display(10000, usd) == 100      # 10000 / 100
    assert _display(12345, usd) == 123      # rounds to whole USD
    assert _display(10000, kes) == 10000    # Kenya sees raw KES
    assert _display(None, usd) is None      # missing price stays missing


def test_display_respects_rate_and_bad_input():
    assert _display(10000, _ctx("USD", rate=125)) == 80
    assert _display(10000, _ctx("USD", rate=0)) == 100   # rate 0 → fall back to 100
    assert _display("not-a-number", _ctx("USD")) == "not-a-number"


def test_to_display_prefers_hub_usd_else_divides():
    usd, kes = _ctx("USD"), _ctx("KES")
    assert _to_display(10000, usd, price_usd=95) == 95     # hub USD wins
    assert _to_display(10000, usd, price_usd=None) == 100  # no hub USD → /rate
    assert _to_display(10000, usd, price_usd=0) == 100     # 0/invalid → /rate
    assert _to_display(10000, usd, price_usd="bad") == 100
    assert _to_display(10000, kes, price_usd=95) == 10000  # Kenya ignores USD


def test_cart_display_kes_is_untouched():
    cart = {"items": [{"name": "Cassock", "qty": 2, "unit_price": 12000,
                       "hub_product_id": 7}]}
    items, total = asyncio.run(_cart_display(cart, _ctx("KES")))
    assert items[0]["unit_price"] == 12000 and total == 24000


def test_cart_display_usd_uses_hub_price_and_sums_lines(monkeypatch):
    async def fake_catalog(db, redis):
        return [{"hub_product_id": 7, "price": 12000, "price_usd": 95}]
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    cart = {"items": [{"name": "Cassock", "qty": 2, "unit_price": 12000,
                       "hub_product_id": 7}]}
    items, total = asyncio.run(_cart_display(cart, _ctx("USD")))
    assert items[0]["unit_price"] == 95      # hub USD, not 12000/100=120
    assert total == 190                      # 95 * 2, summed from the line
    assert cart["items"][0]["unit_price"] == 12000   # original untouched


def test_search_catalog_public_comment_price_is_usd(monkeypatch):
    """Public comments (all Meta) are quoted in USD — only +254 WhatsApp gets KES."""
    from app.agent import tools
    from app.agent.tools import _search_catalog, ToolContext

    async def fake_catalog(db, redis):
        return [{"name": "Doctoral Gown", "sku": "DG1", "price": 13000, "price_usd": 130,
                 "category": "gowns", "product_type": "variable", "is_producible": True}]

    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    ctx = ToolContext(db=None, redis=None, wa_id="PSID", currency="USD")   # Meta → USD
    r = asyncio.run(_search_catalog({"query": "gown"}, ctx))["results"][0]
    assert r["price"] == 130 and r["currency"] == "USD"


def test_prompt_is_currency_aware():
    assert "US Dollars (USD)" in build_system_prompt(currency="USD")
    assert "Kenyan Shillings (KES)" in build_system_prompt(currency="KES")


def test_business_info_injected_only_when_set(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "business_info", "We're on Biashara St, Nairobi CBD; open Mon–Sat.",
                        raising=False)
    p = build_system_prompt(currency="KES")
    assert "Biashara St" in p and "ABOUT BETHANY HOUSE" in p   # facts Neema can quote
    monkeypatch.setattr(settings, "business_info", "", raising=False)
    assert "ABOUT BETHANY HOUSE" not in build_system_prompt(currency="KES")   # nothing injected


def test_prompt_payment_and_fulfilment_are_country_specific():
    """Paybill/M-Pesa-link payment is a KENYAN thing; international customers get
    route discovery (WU/Mukuru + handoff) and courier shipping — never
    'delivery or pickup?'. Vestment expertise appears for both."""
    ke = build_system_prompt(currency="KES")
    intl = build_system_prompt(currency="USD")

    assert "M-Pesa payment link" in ke and "ask: delivery or pickup?" in ke
    assert "KES 350" in ke and "3kg" in ke              # fee baseline + parcel advisory
    assert "Western Union" not in ke                     # no intl routes for Kenyans

    assert "Western Union" in intl and "Mukuru" in intl  # discover the route
    assert "Do NOT present the KES payment link" in intl
    assert 'never ask "delivery or pickup?"' in intl     # courier talk instead
    assert "DHL" in intl and "KES 350" not in intl       # no Kenyan fee language abroad

    for p in (ke, intl):                                 # clergy-wear expertise everywhere
        assert "CLERGY WEAR EXPERTISE" in p and "full set" in p.lower()
        assert "chasuble" in p.lower() and "OVERLAY" in p
        assert "never open with" in p                    # customer-led quantities


def test_prompt_greets_by_nairobi_time():
    from app.agent.prompt import _nairobi_daypart
    assert _nairobi_daypart() in ("morning", "afternoon", "evening", "late night")
    p = build_system_prompt(currency="KES")
    assert "in Nairobi right now" in p and "Greet ONCE" in p
