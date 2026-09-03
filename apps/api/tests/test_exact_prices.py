"""The price is what the hub holds — never rounded to a unit, a tidy figure
or a ten (owner rule, 2026-09-03: "give the price as it is in the hub").

The hub's USD column had a $10 floor rounded to tens; while the owner fixes
those rows, Neema must not add a second layer of rounding of her own. Every
seam a price crosses on its way to a customer is pinned here: the one money
helper, the agent's display conversion, the card formatter, the quotation,
the public-comment price, the public catalogue, the offer arithmetic, the
order-total wording in follow-ups, and the two prompts.
"""
import asyncio
from types import SimpleNamespace

from app.core import money


# ── the one helper ───────────────────────────────────────────────────────────

def test_exact_keeps_the_hubs_figure():
    assert money.exact(130) == 130
    assert money.exact(130.0) == 130          # whole reads whole, not "130.0"
    assert isinstance(money.exact(130.0), int)
    assert money.exact(4.5) == 4.5             # not 5
    assert money.exact(12.75) == 12.75         # not 13
    assert money.exact(117.5) == 117.5         # not 118
    assert money.exact(36000) == 36000
    assert money.exact("4.50") == 4.5          # the hub sends decimals as strings
    assert money.exact(None) is None
    assert money.exact("bad") is None
    assert money.exact(float("nan")) is None


def test_exact_never_rounds_to_tens():
    # The whole complaint: 82 must stay 82, 360 must stay 360.
    for v in (82, 360, 117, 1250, 4, 7, 9.99, 10.01):
        assert money.exact(v) == v


def test_exact_only_touches_sub_cent_noise():
    # Money has no sub-cent — float drift is tidied, nothing else.
    assert money.exact(0.1 * 3) == 0.3
    assert money.exact(0.004, floor_cent=True) == 0.01   # a real item is never free
    assert money.exact(0.004) == 0
    assert money.exact(0) == 0


def test_num_and_fmt_show_decimals_only_when_present():
    assert money.num(1250) == "1,250"
    assert money.num(12.5) == "12.50"
    assert money.num(0.3) == "0.30"
    assert money.num(None) == ""
    assert money.fmt(130, "USD") == "$130"
    assert money.fmt(4.5, "USD") == "$4.50"
    assert money.fmt(1250, "KES") == "KES 1,250"
    assert money.fmt(12.5, "KES") == "KES 12.50"
    assert money.fmt(1260, "zmw") == "ZMW 1,260"
    assert money.fmt(None, "USD") == ""


# ── the agent's seams ────────────────────────────────────────────────────────

def _ctx(currency="USD", rate=100):
    return SimpleNamespace(currency=currency, usd_rate=rate, db=None, redis=None,
                           wa_id="x", channel="whatsapp")


def test_agent_display_passes_the_hub_figure_through():
    from app.agent.tools import _to_display, _display
    usd = _ctx("USD")
    # The hub's own USD row wins and is untouched
    assert _to_display(450, usd, price_usd=4.5) == 4.5
    assert _to_display(1300, usd, prices={"USD": 12.75}) == 12.75
    assert _to_display(36000, usd, prices={"USD": 360}) == 360
    # ZMW the same
    assert _to_display(7000, _ctx("ZMW"), prices={"ZMW": 1262.5}) == 1262.5
    # The derived fallback is the arithmetic, to the cent
    assert _display(1250, usd) == 12.5
    assert _display(12345, usd) == 123.45
    assert _display(36000, usd) == 360
    # Kenya: raw KES, whatever it is
    assert _to_display(12.5, _ctx("KES"), price_usd=99) == 12.5


def test_cart_total_is_the_sum_of_the_shown_unit_prices():
    from app.agent import tools
    async def _catalog(db, redis):
        return [{"hub_product_id": 1, "price_usd": 4.5, "prices": {"USD": 4.5}}]
    orig = tools.svc.catalog_items
    tools.svc.catalog_items = _catalog
    try:
        cart = {"items": [{"hub_product_id": 1, "name": "Cup", "unit_price": 450, "qty": 3}]}
        items, total = asyncio.run(tools._cart_display(cart, _ctx("USD")))
    finally:
        tools.svc.catalog_items = orig
    assert items[0]["unit_price"] == 4.5
    assert total == 13.5                      # 3 × 4.50, not 3 × 5


def test_quotation_lines_keep_cents():
    from app.core import money
    unit, qty = 4.5, 3
    line = f"@ USD {money.num(unit)} = USD {money.num(unit * qty)}"
    assert line == "@ USD 4.50 = USD 13.50"


def test_public_comment_price_text_is_exact():
    # runtime formats the matched product's price for a public reply
    assert money.fmt(4.5, "USD") == "$4.50"
    assert money.fmt(1250, "USD") == "$1,250"     # and never '1.25e+03'
    assert money.fmt(12.5, "KES") == "KES 12.50"


# ── the public catalogue ─────────────────────────────────────────────────────

def test_public_catalog_shows_the_hub_figure(monkeypatch):
    from app.routers import public
    monkeypatch.setattr(public.settings, "usd_kes_rate", 100)
    assert public._money(4.5) == 4.5
    assert public._money(12.75) == 12.75
    assert public._money(130.0) == 130
    assert public._resolve_price({"USD": 4.5, "KES": 450}, "USD") == (4.5, "USD")
    assert public._resolve_price({"KES": 1250}, "USD") == (12.5, "USD")


# ── the offer arithmetic ─────────────────────────────────────────────────────

def test_offer_price_is_exact_like_the_hub():
    from datetime import date, timedelta
    from app.services import promotions as promo
    c = promo.parse({"name": "Harvest Offer", "percent": 10, "scope": "all",
                     "ends_on": (date.today() + timedelta(days=30)).isoformat()})
    assert promo.offer_price(c, 130) == 117
    assert promo.offer_price(c, 45) == 40.5      # the hub charges 40.50; she says 40.50
    assert promo.offer_price(c, 27) == 24.3
    assert promo.offer_price(c, 4.5) == 4.05


# ── order totals in what the customer reads ──────────────────────────────────

def test_payment_followup_total_keeps_its_cents():
    from app.jobs.payment_followup import compose
    order = SimpleNamespace(hub_order_number="BH-1", hub_currency="USD",
                            currency="USD", hub_total=40.5, subtotal=45,
                            hub_payment_url="https://pay.example/BH-1")
    text = compose(order, "Grace")
    assert "USD 40.50" in text
    order.hub_total = 117.0
    assert "USD 117" in compose(order, "Grace")


# ── the prompts ──────────────────────────────────────────────────────────────

def test_prompts_carry_no_rounding_rule():
    from app.agent.prompt import build_system_prompt
    from app.agent.runtime import _meta_addendum
    for p in (build_system_prompt(country_iso="", currency="USD"),
              build_system_prompt(country_iso="KE", currency="KES"),
              _meta_addendum("USD")):
        assert "nearest 10" not in p
        assert "82 → 90" not in p
    p = build_system_prompt(country_iso="", currency="USD")
    assert "NEVER round a price to a whole number" in p
    assert "4.5 is $4.50" in p
    assert "never rounded up, down or to a tidy number" in p
    assert "never rounded to a whole number" in _meta_addendum("USD")
