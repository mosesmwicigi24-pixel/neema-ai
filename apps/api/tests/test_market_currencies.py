"""Kenya trades in KES, Zambia in Kwacha, the world in USD (owner, 2026-08-09).

The hub now carries ZMW price rows for every product (filled from KES at the
owner's 5-KES-per-Kwacha rate). The market gate follows: a customer is priced
in their own country's currency ONLY when the hub actually prices it —
KE → KES, ZM → ZMW — and every other international customer stays on USD.
A Ugandan is NOT quoted UGX (the hub has no UGX rows); they get USD like
before. Display prefers the hub's OWN figure in the customer's currency and
falls back to KES ÷ rate (USD ÷100, ZMW ÷5) so a missing row never shows 0.
"""
import inspect
import types

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.core.countries import market_currency, money_name, resolve_country
from app.agent.prompt import build_system_prompt


# ── the gate ─────────────────────────────────────────────────────────────────

def test_market_currency_gate():
    assert market_currency("KE") == "KES"
    assert market_currency("ZM") == "ZMW"
    assert market_currency("zm") == "ZMW"
    # A mapped country whose currency the hub does NOT price stays USD.
    assert market_currency("UG") == "USD"
    assert market_currency("TZ") == "USD"
    assert market_currency("IN") == "USD"
    assert market_currency(None) == "USD"


def test_zambian_phone_resolves_to_zm():
    assert resolve_country("260977123456")["country_iso"] == "ZM"


def test_money_names():
    assert money_name("ZMW") == "Zambian Kwacha (ZMW)"
    assert money_name("KES") == "Kenyan Shillings (KES)"
    assert money_name(None) == "US Dollars (USD)"


def test_both_conversation_entrances_use_the_gate():
    import app.agent.runtime as rt
    assert "market_currency(" in inspect.getsource(rt.run_turn)
    assert "market_currency(" in inspect.getsource(rt._meta_market)


# ── the prompt speaks Kwacha ─────────────────────────────────────────────────

def test_zmw_prompt_names_the_kwacha_and_ships_international():
    p = build_system_prompt(country_iso="ZM", currency="ZMW")
    flat = " ".join(p.split())
    assert "Zambian Kwacha (ZMW)" in flat
    assert "FULFILMENT (international)" in p           # no M-Pesa flow for Zambia
    # The convert-on-request paragraph belongs to USD customers only — a
    # Zambian already has their own money.
    assert "convert from the USD amount" not in flat


def test_prompt_teaches_the_zambia_research():
    flat = " ".join(build_system_prompt(currency="USD").split())
    assert 'Zambia the same with currency="ZMW"' in flat


def test_meta_addendum_speaks_the_market_currency():
    from app.agent.runtime import _meta_addendum, _public_comment_addendum
    assert "Zambian Kwacha (ZMW)" in _meta_addendum("ZMW")
    a = _public_comment_addendum("ZMW")
    assert "Zambian Kwacha (ZMW)" in a and "ZMW 1,300" in a


# ── display prefers the hub's own figure, then the owner's rate ──────────────

def _ctx(ccy):
    from app.agent.tools import ToolContext
    return ToolContext(db=None, redis=None, wa_id="260977123456",
                       currency=ccy, usd_rate=100)


def test_display_uses_hub_zmw_price_first():
    from app.agent.tools import _to_display
    assert _to_display(7000, _ctx("ZMW"), prices={"ZMW": 1400, "USD": 70}) == 1400
    assert _to_display(7000, _ctx("USD"), prices={"ZMW": 1400, "USD": 70}) == 70
    # No ZMW row → KES ÷ 5 (the owner's rate), never 0.
    assert _to_display(4500, _ctx("ZMW"), prices={}) == 900
    # Legacy price_usd argument still honoured for USD.
    assert _to_display(7000, _ctx("USD"), price_usd=70) == 70
    # Kenya stays raw KES whatever maps ride along.
    assert _to_display(7000, _ctx("KES"), prices={"ZMW": 1400}) == 7000


def test_search_override_accepts_zmw():
    import app.agent.tools as tools
    src = inspect.getsource(tools._search_catalog)
    assert '("KES", "USD", "ZMW")' in src
    schema = next(t for t in tools.TOOLS if t["name"] == "search_catalog")
    assert "ZMW" in schema["input_schema"]["properties"]["currency"]["enum"]


def test_cart_lines_carry_the_price_map():
    from app.core.hub_client import resolve_hub_line
    catalog = [{"name": "Aluminium Tray", "sku": "COM-AT-001", "hub_product_id": 71,
                "price": 7000, "price_usd": 70,
                "prices": {"KES": 7000, "USD": 70, "ZMW": 1400}}]
    line = resolve_hub_line({"name": "Aluminium Tray", "qty": 2}, catalog)
    assert line["prices"]["ZMW"] == 1400
    # …and the cart display consults it for non-KES customers.
    import app.agent.tools as tools
    src = inspect.getsource(tools._cart_display)
    assert "prices_by_id" in src and 'r.get("prices")' in src
