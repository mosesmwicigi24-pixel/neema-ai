"""RANDS FROM THE HUB (owner, 2026-11-16: "quote rands from the hub rates").
The hub sets a customer price per currency (KES 6.50 = 1 ZAR) and writes
each product's rand price from it. Neema reads the rate from those prices —
one place to change it — and never converts such a currency at a public rate."""
import inspect

import app.main  # noqa: F401
from app.services import fx

# As the hub sent them on 2026-11-16 (GET /api/v1/products).
CATALOG = [
    {"name": "Trousers", "price": 8000, "prices": {"KES": 8000, "GBP": 53, "USD": 80, "ZAR": 1231, "ZMW": 1120}},
    {"name": "Refiller Silver Kettle", "price": 5500, "prices": {"KES": 5500, "GBP": 37, "USD": 55, "ZAR": 846, "ZMW": 770}},
    {"name": "Refiller Golden Kettle", "price": 6000, "prices": {"KES": 6000, "GBP": 40, "USD": 60, "ZAR": 923, "ZMW": 840}},
    {"name": "Cream Gold Cassock", "price": 15000, "prices": {"KES": 15000, "GBP": 100, "USD": 150, "ZAR": 2308, "ZMW": 2100}},
    {"name": "ROSARY", "price": 500, "prices": {"KES": 500, "GBP": 3, "USD": 5, "ZAR": 77, "ZMW": 70}},
    {"name": "Cassock", "price": 13000, "prices": {"KES": 13000, "USD": 130, "ZMW": 1820}},   # no rand row
]


def test_the_rate_is_read_from_the_hubs_own_prices():
    per = fx.hub_kes_per_unit(CATALOG)
    assert per["ZAR"] == 6.5 and per["GBP"] == 150.0 and per["ZMW"] == 7.14
    assert "KES" not in per and "USD" not in per
    rates = fx.hub_rates(CATALOG, 100)
    # a KES 13,000 cassock ($130) is R 2,000 at the hub's rate
    assert round(fx.convert_usd(130, rates["ZAR"])) == 2000
    assert round(fx.convert_usd(80, rates["ZAR"])) == 1231          # the hub's own row for Trousers
    assert round(fx.convert_usd(150, rates["GBP"])) == 100


def test_one_odd_row_cannot_move_the_rate_and_too_few_rows_give_none():
    odd = CATALOG + [{"name": "Typo", "price": 9000, "prices": {"KES": 9000, "ZAR": 90}}]
    assert fx.hub_kes_per_unit(odd)["ZAR"] == 6.5
    assert "ZAR" not in fx.hub_kes_per_unit(CATALOG[:2])            # two rows: not enough to trust
    assert fx.hub_kes_per_unit([]) == {} and fx.hub_kes_per_unit(None) == {}
    assert fx.hub_kes_per_unit([{"prices": {"KES": "x", "ZAR": None}}, "junk"]) == {}


def test_the_writer_is_told_it_is_our_rate_not_a_market_rate():
    rates = fx.hub_rates(CATALOG, 100)
    line = fx.hub_line("ZAR", rates["ZAR"], 6.5)
    assert "KES 6.5 = 1 ZAR" in line and "$130 = 2,000 ZAR" in line
    assert "OUR RATE" in line and "TODAY'S RATE" not in line and "public source" not in line


def test_the_turn_prefers_the_hubs_rate_over_the_public_one():
    from app.agent import runtime
    src = inspect.getsource(runtime.run_turn)
    assert "_fx.hub_rates(_fx_cat, settings.usd_kes_rate)" in src and "_fx.hub_line(" in src
    # the gate verifies against the same merged rates
    assert "fx=_fx_rates" in src


def test_the_kwacha_fallback_is_the_hubs_rate_once_the_catalogue_was_read(monkeypatch):
    from app.agent import tools
    from app.agent.tools import ToolContext
    monkeypatch.setattr(fx, "_HUB_PER", {"rates": {}, "mark": None})
    ctx = ToolContext(db=None, redis=None, wa_id="260970000001", currency="ZMW")
    assert tools._kes_rate_for(ctx, "ZMW") == 5            # nothing read yet: the setting
    fx.remember(CATALOG)
    assert tools._kes_rate_for(ctx, "ZMW") == 7.14 and fx.hub_per("ZAR") == 6.5
    assert tools._kes_rate_for(ctx, "USD") == 100          # the house dollar is untouched
    fx.remember([])                                        # an empty read keeps the last good rates
    fx.remember(None)
    assert fx.hub_per("ZMW") == 7.14
    assert fx.hub_per("NGN") is None and fx.hub_per("NGN", 1.0) == 1.0
