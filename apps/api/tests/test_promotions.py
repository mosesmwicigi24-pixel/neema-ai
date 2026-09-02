"""A discount the owner gave, said outright.

The owner's instruction: "make it outright the discount given … harvest
discount of 10% from gown 130 usd to 117 … for 1 month". Three things have to
be true for that to be safe to ship:

  · the arithmetic is CODE's, because a model doing 10% off 130 in its head is
    how a customer gets quoted 118;
  · it expires on its own, because a forgotten promotion gives away margin
    forever;
  · the order carries it, because quoting 117 while the hub says 130 turns a
    discount into a complaint.
"""
import asyncio
import json
from datetime import date, timedelta

import pytest

from app.services import promotions as promo


def _c(**kw):
    base = {"name": "Harvest Offer", "percent": 10, "scope": "all",
            "ends_on": (date.today() + timedelta(days=30)).isoformat()}
    base.update(kw)
    return promo.parse(base)


# ── the arithmetic ───────────────────────────────────────────────────────────

def test_the_owners_own_example():
    # "10% from gown 130 usd to 117"
    assert promo.offer_price(_c(), 130) == 117.0


@pytest.mark.parametrize("price,percent,expected", [
    (130, 10, 117.0),      # the example
    (100, 10, 90.0),
    (4000, 15, 3400.0),    # KES prices are whole units too
    (99, 33, 66.0),
    (0.50, 10, 0.45),      # under a unit keeps its cents
    (1, 50, 0.50),
])
def test_prices_are_exact_not_approximately_right(price, percent, expected):
    assert promo.offer_price(_c(percent=percent), price) == expected


def test_half_up_never_banker_s_rounding():
    # 125 * 0.9 = 112.5 → 113. Python's own round() gives 112, which quietly
    # hands the customer a shilling that isn't theirs on every such price.
    assert promo.offer_price(_c(percent=10), 125) == 113.0


@pytest.mark.parametrize("price", [0, -5, None, "", "abc"])
def test_an_unpriced_item_gets_no_offer(price):
    # The catalogue has rows with no price set; "10% off nothing" must never
    # become a number a customer is quoted.
    assert promo.offer_price(_c(), price) is None


def test_an_offer_that_saves_nothing_is_not_an_offer():
    # 1% off a one-cent item rounds straight back to a cent. There is no
    # saving to announce, so there is no offer — better silence than "was
    # $0.01, now $0.01".
    assert promo.offer_price(_c(percent=1), 0.01) is None


def test_a_small_but_real_saving_still_counts():
    # 1% off a 1-unit item IS a cent. Tiny, but the owner chose the number and
    # the customer is genuinely paying less.
    assert promo.offer_price(_c(percent=1), 1) == 0.99


# ── it expires by itself ─────────────────────────────────────────────────────

def test_it_runs_through_its_last_day_inclusive():
    today = date.today()
    assert promo.is_running(_c(ends_on=today.isoformat()), on=today)


def test_it_is_over_the_day_after():
    today = date.today()
    c = _c(ends_on=today.isoformat())
    assert not promo.is_running(c, on=today + timedelta(days=1))


def test_a_future_campaign_does_not_leak_early():
    today = date.today()
    c = _c(starts_on=(today + timedelta(days=3)).isoformat(),
           ends_on=(today + timedelta(days=10)).isoformat())
    assert not promo.is_running(c, on=today)
    assert promo.is_running(c, on=today + timedelta(days=4))


# ── scope ────────────────────────────────────────────────────────────────────

def test_everything_means_everything():
    assert promo.applies_to(_c(scope="all"), {"sku": "X", "category": "anything"})


def test_a_category_offer_leaves_the_rest_alone():
    c = _c(scope="category", categories=["Gowns"])
    assert promo.applies_to(c, {"category": "gowns"})        # the hub's casing
    assert promo.applies_to(c, {"category": " Gowns "})
    assert not promo.applies_to(c, {"category": "Chalices"})
    assert not promo.applies_to(c, {"category": ""})


def test_a_named_product_offer_covers_only_those_skus():
    c = _c(scope="products", skus=["GOWN-01", "GOWN-02"])
    assert promo.applies_to(c, {"sku": "gown-01"})
    assert not promo.applies_to(c, {"sku": "GOWN-03"})
    assert not promo.applies_to(c, {"sku": ""})


# ── what gets stored, and what gets refused ──────────────────────────────────

@pytest.mark.parametrize("bad", [
    {},
    {"name": "", "percent": 10, "scope": "all", "ends_on": "2099-01-01"},
    {"name": "X", "percent": 0, "scope": "all", "ends_on": "2099-01-01"},
    {"name": "X", "percent": 71, "scope": "all", "ends_on": "2099-01-01"},
    {"name": "X", "percent": "ten", "scope": "all", "ends_on": "2099-01-01"},
    {"name": "X", "percent": 10, "scope": "everything", "ends_on": "2099-01-01"},
    {"name": "X", "percent": 10, "scope": "category", "ends_on": "2099-01-01"},
    {"name": "X", "percent": 10, "scope": "products", "ends_on": "2099-01-01"},
    {"name": "X", "percent": 10, "scope": "all"},
    {"name": "X", "percent": 10, "scope": "all", "ends_on": "next month"},
])
def test_a_malformed_campaign_reads_as_no_offer(bad):
    # Strict and quiet on purpose: a bad row must never make Neema announce a
    # discount nobody authorised.
    assert promo.parse(bad) is None


def test_a_percentage_above_the_ceiling_is_a_mistake_not_a_promotion():
    assert promo.parse({"name": "X", "percent": 90, "scope": "all",
                        "ends_on": "2099-01-01"}) is None


# ── the words ────────────────────────────────────────────────────────────────

def test_the_sentence_names_the_offer_the_size_the_scope_and_the_end():
    c = _c(scope="category", categories=["gowns"], ends_on="2026-09-30")
    said = promo.describe(c)
    assert "Harvest Offer" in said and "10%" in said
    assert "gowns" in said and "30 September 2026" in said


def test_an_expired_offer_says_nothing_at_all():
    c = _c(ends_on=(date.today() - timedelta(days=1)).isoformat())
    assert promo.describe(c) == ""
    assert promo.order_note(c) == ""


def test_the_order_note_tells_a_person_to_apply_it_before_payment():
    note = promo.order_note(_c())
    assert "Harvest Offer" in note and "10%" in note
    assert "APPLY before taking payment" in note


# ── storage ──────────────────────────────────────────────────────────────────

class _Redis:
    def __init__(self, store=None):
        self.store = dict(store or {})
    async def get(self, k):
        return self.store.get(k)
    async def set(self, k, v, **kw):
        self.store[k] = v
        return True


class _DB:
    def __init__(self, row=None):
        self.row, self.added, self.committed = row, [], False
    async def execute(self, *a, **k):
        class _R:
            def __init__(s, one): s._one = one
            def scalar_one_or_none(s): return s._one
        return _R(self.row)
    def add(self, o):
        self.added.append(o)
    async def commit(self):
        self.committed = True


def test_ending_a_campaign_stops_it_now_not_in_five_minutes():
    r = _Redis({promo.CAMPAIGN_CACHE: json.dumps(_c())})
    db = _DB(type("Row", (), {"value": "x", "updated_by": None})())
    assert asyncio.run(promo.set_campaign(db, r, None)) is None
    assert r.store[promo.CAMPAIGN_CACHE] == "-"
    assert asyncio.run(promo.active_campaign(db, r)) is None


def test_an_expired_row_is_never_served_as_live():
    stale = _c(ends_on=(date.today() - timedelta(days=1)).isoformat())
    r = _Redis({promo.CAMPAIGN_CACHE: json.dumps(stale)})
    assert asyncio.run(promo.active_campaign(_DB(), r)) is None


def test_a_declared_campaign_comes_back():
    r = _Redis()
    db = _DB()
    saved = asyncio.run(promo.set_campaign(db, r, {
        "name": "Harvest Offer", "percent": 10, "scope": "category",
        "categories": ["gowns"], "ends_on": (date.today() + timedelta(days=30)).isoformat()}))
    assert saved["name"] == "Harvest Offer" and db.committed
    assert asyncio.run(promo.active_campaign(db, r))["percent"] == 10


def test_declaring_nonsense_is_refused_loudly():
    with pytest.raises(ValueError):
        asyncio.run(promo.set_campaign(_DB(), _Redis(), {"name": "X", "percent": 999}))


# ── the discount is a closing tool, not an announcement ──────────────────────
# The owner's steer: "think as a business man … not to always throw the
# discount in the beginning. Sales is closing more sales, but if a discount
# helps close the sale, throw it in." The shape he drew:
#
#   Customer: Do you have anointing oil?
#   Neema:    Yes we do — Eliad Oil at USD 50.        ← full price, no offer
#   Customer: Can you give a discount?
#   Neema:    Let me see — Harvest Offer, 10% off …   ← now it is played
#
# Most customers never reach line three. Leading with the offer hands 10% to
# every one of them.

def test_the_catalogue_quotes_the_full_price_even_when_an_offer_covers_it():
    import inspect
    from app.agent import tools
    src = inspect.getsource(tools._search_catalog)
    # The held card is attached, but the quoted price is untouched.
    assert "offer_available" in src
    assert 'row["price"] = _off' not in src and 'row["price"] = _now' not in src


def test_the_held_card_tells_her_not_to_lead_with_it():
    import inspect
    from app.agent import tools
    src = inspect.getsource(tools._search_catalog)
    assert "DO NOT mention this yet" in src
    assert "apply_offer" in src


def test_playing_it_is_a_deliberate_act_with_its_own_tool():
    from app.agent.tools import TOOLS, _HANDLERS
    assert "apply_offer" in _HANDLERS
    schema = next(t for t in TOOLS if t["name"] == "apply_offer")
    d = schema["description"]
    assert "close the sale" in d
    assert "NEVER call it on a first quote" in d


def test_the_prompt_teaches_hold_then_close():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(offer="Harvest Offer — 10% off our oils, until 30 September 2026")
    assert "QUOTE THE FULL PRICE FIRST" in p
    assert "closing tool, not an announcement" in p
    assert "ASK FOR THE ORDER in the same message" in p
    # …and it must not be preached when no campaign is running.
    assert "THE OFFER YOU ARE HOLDING" not in build_system_prompt(offer="")


def test_an_order_carries_the_offer_only_when_it_was_actually_given():
    import inspect
    from app.agent import tools
    src = inspect.getsource(tools._create_order)
    assert "was_granted" in src, "every order would otherwise be discounted"


class _GrantRedis:
    def __init__(self):
        self.store = {}
    async def get(self, k):
        return self.store.get(k)
    async def set(self, k, v, **kw):
        self.store[k] = v
        return True


def test_a_customer_who_never_asked_is_not_recorded_as_discounted():
    r = _GrantRedis()
    assert asyncio.run(promo.was_granted(r, "whatsapp", "254700000000")) is False


def test_granting_is_per_conversation_not_global():
    r = _GrantRedis()
    asyncio.run(promo.mark_granted(r, "whatsapp", "254700000000", "Harvest Offer"))
    assert asyncio.run(promo.was_granted(r, "whatsapp", "254700000000")) is True
    # The customer next door still pays the full price.
    assert asyncio.run(promo.was_granted(r, "whatsapp", "254711111111")) is False
    # And the same person on another channel is a different thread.
    assert asyncio.run(promo.was_granted(r, "instagram", "254700000000")) is False


def test_granting_survives_a_dead_redis_without_raising():
    class _Boom:
        async def get(self, k): raise RuntimeError("down")
        async def set(self, k, v, **kw): raise RuntimeError("down")
    assert asyncio.run(promo.mark_granted(_Boom(), "whatsapp", "x", "H")) is False
    assert asyncio.run(promo.was_granted(_Boom(), "whatsapp", "x")) is False
    assert asyncio.run(promo.was_granted(None, "whatsapp", "x")) is False
