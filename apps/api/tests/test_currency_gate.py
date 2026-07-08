"""Currency display gate (pure, no DB).

Rule: Kenya (+254) customers are quoted KES; everyone else — and all
Messenger/IG, which carry no phone — is quoted USD = round(KES / usd_kes_rate).
Conversion happens in the tools; the LLM only quotes what it's handed.
"""
from types import SimpleNamespace

from app.agent.tools import _display, _display_items
from app.agent.prompt import build_system_prompt


def _ctx(currency="KES", rate=100):
    # _display only reads .currency and .usd_rate, so a light stub is enough.
    return SimpleNamespace(currency=currency, usd_rate=rate)


def test_display_converts_only_for_usd():
    usd = _ctx("USD")
    kes = _ctx("KES")
    assert _display(10000, usd) == 100      # 10000 / 100
    assert _display(12345, usd) == 123      # rounds to whole USD
    assert _display(10000, kes) == 10000    # Kenya sees raw KES
    assert _display(None, usd) is None      # missing price stays missing


def test_display_respects_rate_and_bad_input():
    assert _display(10000, _ctx("USD", rate=125)) == 80
    assert _display(10000, _ctx("USD", rate=0)) == 100   # rate 0 → fall back to 100
    assert _display("not-a-number", _ctx("USD")) == "not-a-number"


def test_display_items_converts_unit_price():
    items = [{"name": "Cassock", "qty": 2, "unit_price": 12000}]
    out = _display_items(items, _ctx("USD"))
    assert out[0]["unit_price"] == 120 and out[0]["qty"] == 2
    assert items[0]["unit_price"] == 12000   # original untouched (copied)


def test_prompt_is_currency_aware():
    assert "US Dollars (USD)" in build_system_prompt(currency="USD")
    assert "Kenyan Shillings (KES)" in build_system_prompt(currency="KES")
