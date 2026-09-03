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
    (99, 33, 66.33),       # to the cent — the hub bills 66.33, so she says 66.33
    (45, 10, 40.5),        # 10% off USD 45 is 40.50, not a rounded 41
    (0.50, 10, 0.45),      # under a unit keeps its cents
    (1, 50, 0.50),
])
def test_prices_are_exact_not_approximately_right(price, percent, expected):
    assert promo.offer_price(_c(percent=percent), price) == expected


def test_half_up_never_banker_s_rounding():
    # 0.30 * 0.85 = 0.255 → 0.26 at the cent. Python's own round() gives 0.25,
    # which quietly hands the customer a cent that isn't theirs on every such
    # price. And a figure that already sits on a cent is not touched at all:
    # 125 * 0.9 = 112.5 stays 112.5 — neither 113 nor 112.
    assert promo.offer_price(_c(percent=15), 0.30) == 0.26
    assert promo.offer_price(_c(percent=10), 125) == 112.5


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
    # The note is built from THIS customer's promise; no promise, no note.
    assert "granted_promise" in src, "every order would otherwise be discounted"


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


# ── a price already quoted is a promise ──────────────────────────────────────
# The offer was switched off the day after Neema quoted someone the offer
# price. Before this, their order silently reverted to the full price: the
# note was built from the campaign, and the campaign was gone. You do not take
# back a price you have given — and the customer would never learn why.

def _promised(redis, channel="whatsapp", key="254700000000"):
    c = _c(percent=10)
    asyncio.run(promo.mark_granted(redis, channel, key, c))
    return asyncio.run(promo.granted_promise(redis, channel, key))


def test_the_terms_are_recorded_not_just_the_fact():
    p = _promised(_GrantRedis())
    assert p["name"] == "Harvest Offer" and p["percent"] == 10 and p["at"]


def test_the_order_honours_it_after_the_campaign_ends():
    # No campaign running at all — the note comes from the promise regardless.
    note = promo.promise_note(_promised(_GrantRedis()))
    assert "Harvest Offer" in note and "10% off" in note
    assert "was QUOTED" in note and "APPLY before taking payment" in note
    assert "even if the offer has since ended" in note


def test_a_customer_who_was_never_promised_anything_gets_no_note():
    assert promo.promise_note(None) == ""
    assert promo.promise_note({}) == ""
    assert promo.promise_note(asyncio.run(
        promo.granted_promise(_GrantRedis(), "whatsapp", "254799999999"))) == ""


def test_neema_is_told_the_price_stands_so_she_does_not_quote_higher():
    line = promo.promise_line(_promised(_GrantRedis()))
    assert "THAT PRICE STANDS" in line
    assert "even if the offer has since ended" in line
    # …and she must not treat it as a fresh card to play again.
    assert "do not offer it a second time" in line
    assert promo.promise_line(None) == ""


def test_the_promise_reaches_the_per_customer_block_only():
    from app.agent.prompt import build_system_prompt, customer_context
    line = promo.promise_line(_promised(_GrantRedis()))
    assert line in customer_context("Pastor Moses", "Kenya", line)
    # The shared rules block is byte-identical fleet-wide — a per-customer
    # promise in there would break the cached prefix for everyone.
    assert line not in build_system_prompt(offer="Harvest Offer — 10% off")


def test_an_older_bare_name_grant_still_counts_as_a_promise():
    # Grants written before the terms were stored held just the campaign name.
    r = _GrantRedis()
    r.store[promo._grant_key("whatsapp", "254700000000")] = "Harvest Offer"
    p = asyncio.run(promo.granted_promise(r, "whatsapp", "254700000000"))
    assert p["name"] == "Harvest Offer" and p["percent"] is None
    note = promo.promise_note(p)
    assert "the offer price was QUOTED" in note      # no percentage to quote back
    assert "Honour it" in note


def test_the_order_note_no_longer_depends_on_a_running_campaign():
    import inspect
    from app.agent import tools
    src = inspect.getsource(tools._create_order)
    # The promise itself now travels to push_pending_order, which puts the
    # percentage on the covered lines and writes the note describing what it
    # did — so the order carries the discount as MONEY, not as a sentence.
    assert "granted_promise" in src and "promise=" in src
    assert "campaign_now" not in src, "an ended campaign must not revoke a quoted price"


# ── a promise is only made when the offer was actually quoted ────────────────
# The grant used to be written the moment apply_offer ran, BEFORE the tool had
# checked whether the campaign covered what the customer asked about. So asking
# after an excluded product recorded a 45-day promise while Neema said, in the
# same breath, that it was not covered — and the next order they placed, of
# anything at all, carried a note telling the team a discount was owed.

class _OfferCtx:
    """The slice of ToolContext _apply_offer actually reads."""
    def __init__(self, redis):
        self.redis, self.channel, self.wa_id = redis, "whatsapp", "254700000000"
        self.db, self.currency = None, "KES"


def _run_apply_offer(monkeypatch, campaign, catalog, product):
    from app.agent import tools
    from app.services import promotions as _p

    async def _campaign_now(_r):
        return campaign
    async def _catalog_items(_db, _r):
        return catalog

    monkeypatch.setattr(_p, "campaign_now", _campaign_now)
    monkeypatch.setattr(tools.svc, "catalog_items", _catalog_items)

    redis = _GrantRedis()
    ctx = _OfferCtx(redis)
    out = asyncio.run(tools._apply_offer({"product": product} if product else {}, ctx))
    return out, asyncio.run(_p.was_granted(redis, "whatsapp", "254700000000"))


def test_asking_about_an_excluded_product_records_no_promise(monkeypatch):
    campaign = _c(scope="category", categories=["Gowns"])
    catalog = [{"name": "Chalice Cup", "sku": "CH-1", "category": "Chalices",
                "price": 5000, "aliases": []}]

    out, granted = _run_apply_offer(monkeypatch, campaign, catalog, "chalice cup")

    assert "not_covered" in out, "she must still say plainly that it is excluded"
    assert out["granted"] is False
    assert granted is False, "an excluded product must not buy a 45-day discount"


def test_a_covered_product_is_quoted_and_promised(monkeypatch):
    campaign = _c(scope="category", categories=["Gowns"])
    catalog = [{"name": "Canon Gown", "sku": "CG-1", "category": "Gowns",
                "price": 10000, "aliases": []}]

    out, granted = _run_apply_offer(monkeypatch, campaign, catalog, "canon gown")

    assert out["offer_price"] == 9000
    assert out["granted"] is True
    assert granted is True


def test_a_product_we_do_not_stock_records_nothing(monkeypatch):
    # Nothing was quoted, so nothing was promised.
    campaign = _c()
    catalog = [{"name": "Canon Gown", "sku": "CG-1", "category": "Gowns",
                "price": 10000, "aliases": []}]

    out, granted = _run_apply_offer(monkeypatch, campaign, catalog, "hovercraft")

    assert out["granted"] is False
    assert granted is False


def test_asking_what_is_on_offer_still_counts_as_a_quote(monkeypatch):
    # No product named: stating the campaign IS the quote.
    out, granted = _run_apply_offer(monkeypatch, _c(), [], None)

    assert out["granted"] is True
    assert granted is True


def test_no_campaign_promises_nothing(monkeypatch):
    out, granted = _run_apply_offer(monkeypatch, None, [], "canon gown")

    assert out["offer"] is None
    assert granted is False


# ── the note names its own limit ─────────────────────────────────────────────

def test_the_note_says_what_a_scoped_offer_does_not_cover():
    r = _GrantRedis()
    asyncio.run(promo.mark_granted(r, "whatsapp", "254700000000",
                                   _c(scope="category", categories=["Gowns"])))
    note = promo.promise_note(
        asyncio.run(promo.granted_promise(r, "whatsapp", "254700000000")))

    assert "Gowns" in note
    assert "full price for anything else" in note, \
        "a person reading this must not discount the whole order"


def test_an_everything_offer_needs_no_limit_clause():
    r = _GrantRedis()
    asyncio.run(promo.mark_granted(r, "whatsapp", "254700000000", _c()))
    note = promo.promise_note(
        asyncio.run(promo.granted_promise(r, "whatsapp", "254700000000")))

    assert "covers ONLY" not in note


# ── the promise travels as money, not as a sentence ──────────────────────────
# It used to reach the hub only as a note in the order: lines were pushed at
# list price and a person was expected to apply the discount by hand. Meanwhile
# the customer already had the durable order link — so someone quoted 117 could
# open it, see 130, and pay 130 before anybody read the note.

def test_a_promise_covers_everything_when_it_named_no_scope():
    r = _GrantRedis()
    asyncio.run(promo.mark_granted(r, "whatsapp", "254700000000", _c()))
    p = asyncio.run(promo.granted_promise(r, "whatsapp", "254700000000"))

    assert promo.promise_covers(p, {"sku": "ANY-1", "category": "Chalices"})


def test_a_category_promise_covers_only_that_category():
    r = _GrantRedis()
    asyncio.run(promo.mark_granted(r, "whatsapp", "254700000000",
                                   _c(scope="category", categories=["Gowns"])))
    p = asyncio.run(promo.granted_promise(r, "whatsapp", "254700000000"))

    assert promo.promise_covers(p, {"sku": "CG-1", "category": "gowns"})
    assert not promo.promise_covers(p, {"sku": "CH-1", "category": "Chalices"})


def test_a_sku_promise_covers_only_those_skus():
    r = _GrantRedis()
    asyncio.run(promo.mark_granted(r, "whatsapp", "254700000000",
                                   _c(scope="products", skus=["GOWN-01"])))
    p = asyncio.run(promo.granted_promise(r, "whatsapp", "254700000000"))

    assert promo.promise_covers(p, {"sku": "gown-01", "category": "Gowns"})
    assert not promo.promise_covers(p, {"sku": "GOWN-02", "category": "Gowns"})


def test_no_promise_covers_nothing():
    assert not promo.promise_covers(None, {"sku": "X", "category": "Y"})


def test_the_note_says_it_is_already_on_the_order():
    # The old note said "APPLY before taking payment". Said now, over lines that
    # already carry the discount, it would have a person discount it twice.
    note = promo.applied_note({"name": "Harvest Offer", "percent": 10, "at": "2026-09-02"},
                              applied=2, pending=0)

    assert "ALREADY ON" in note
    assert "Do not apply it again" in note


def test_the_note_singles_out_the_made_to_order_lines():
    # The hub's production_items carry no discount field, so those still need a
    # person — and the note must say WHICH, not "apply it" over everything.
    note = promo.applied_note({"name": "Harvest Offer", "percent": 10, "at": None},
                              applied=1, pending=1)

    assert "already on the stocked lines" in note
    assert "made-to-order" in note


def test_a_promise_that_touches_nothing_in_this_order_says_nothing():
    assert promo.applied_note({"name": "Harvest Offer", "percent": 10},
                              applied=0, pending=0) == ""
