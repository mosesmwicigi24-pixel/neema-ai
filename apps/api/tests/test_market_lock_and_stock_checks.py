"""A placed customer's currency cannot be moved by the model, and a plain stock
item is never sent to the team to "confirm" (owner review, 2026-10-29).

Live misses behind each test:
  · a South African number (+27, market USD) was quoted "ZMW 2,600" for a
    gown, then "it's in US dollars — $130" for the same gown: the model passed
    currency="ZMW" and the tool obeyed. 9 South African and 13 Tanzanian
    WhatsApp threads in 30 days — one Tanzanian wrote "Taja kwa pesa ya 🇹🇿…
    am not a Kenyan";
  · "Let me confirm with the team on the Aluminium Tray" — a tray we sell
    every week — and the team's answer never came; the church waited.
"""
import asyncio
import inspect
from types import SimpleNamespace

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import tools
from app.agent.tools import ToolContext, _search_catalog, _stock_rows_named


def _catalog():
    return [
        {"hub_product_id": 1, "name": "Aluminium Tray", "sku": "AT", "price": 7000,
         "price_usd": 70, "prices": {"ZMW": 1400}, "category": "Holy Communion",
         "aliases": ["communion tray with cups"]},
        {"hub_product_id": 2, "name": "Golden Communion Tray", "sku": "GT", "price": 22000,
         "price_usd": 220, "category": "Holy Communion", "aliases": ["tray with cups"]},
        {"hub_product_id": 3, "name": "Chalice Cup -Medium", "sku": "CM", "price": 10000,
         "price_usd": 100, "category": "Holy Communion"},
        {"hub_product_id": 4, "name": "Chalice Cup - Medium Sized Gold Coated Stainless Steel",
         "sku": "CG", "price": 20000, "price_usd": 200, "category": "Holy Communion"},
        {"hub_product_id": 5, "name": "Preaching Gown", "sku": "PG", "price": 13000,
         "price_usd": 130, "prices": {"ZMW": 2600}, "category": "Gowns",
         "product_type": "variable", "is_producible": True},
        {"hub_product_id": 6, "name": "NIV BIBLE", "sku": "NB", "price": 2500,
         "price_usd": 25, "category": "Books"},
    ]


def _fake(monkeypatch):
    async def fake_catalog(db, redis):
        return _catalog()
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)


# ── the market lock ──────────────────────────────────────────────────────────

def test_a_placed_customer_keeps_their_currency_whatever_the_model_asks(monkeypatch):
    _fake(monkeypatch)
    ctx = ToolContext(db=None, redis=None, wa_id="27610000791", channel="whatsapp",
                      currency="USD", market_locked=True)
    out = asyncio.run(_search_catalog({"query": "preaching gown", "currency": "ZMW"}, ctx))
    assert ctx.currency == "USD" and out["currency"] == "USD"
    assert out["results"][0]["price"] == 130            # dollars, never Kwacha 2,600
    assert "never ZMW" in out["currency_note"]


def test_an_unplaced_customer_still_moves_on_a_cue(monkeypatch):
    """Messenger with no evidence: "In Zm Kwacha?" must still reach ZMW."""
    _fake(monkeypatch)
    ctx = ToolContext(db=None, redis=None, wa_id="psid1", channel="messenger", currency="USD")
    out = asyncio.run(_search_catalog({"query": "preaching gown", "currency": "ZMW"}, ctx))
    assert ctx.currency == "ZMW" and out["results"][0]["price"] == 2600
    assert "currency_note" not in out


def test_the_same_currency_asked_again_adds_no_note(monkeypatch):
    _fake(monkeypatch)
    ctx = ToolContext(db=None, redis=None, wa_id="260970000000", currency="ZMW",
                      market_locked=True)
    out = asyncio.run(_search_catalog({"query": "aluminium tray", "currency": "ZMW"}, ctx))
    assert out["currency"] == "ZMW" and "currency_note" not in out


def test_the_turn_locks_exactly_when_the_server_placed_them():
    import app.agent.runtime as rt
    src = inspect.getsource(rt.run_turn)
    assert 'market_locked=bool(loc.get("country_iso"))' in src
    # Swahili-means-Kenya is for a customer we could not place — a Tanzanian
    # on record writes Swahili too.
    assert src.index('if not loc.get("country_iso"):') \
        < src.index("currency = await _kes_for_swahili(")


def test_their_own_words_naming_zambia_move_a_placed_customer(monkeypatch):
    """Lock or no lock, a town they NAME outranks a number's prefix — the
    capture path that already did this for Kenya now does it for Zambia."""
    src = inspect.getsource(tools._capture_contact)
    assert 'market_currency(iso_from_text(location))' in src
    assert '_said in ("KES", "ZMW")' in src


# ── stock items are not a team question ──────────────────────────────────────

def test_a_plain_stock_item_is_named():
    cat = _catalog()
    for item in ("Aluminium Tray", "Aluminium Communion Tray", "Aluminium Tray x2",
                 "Chalice Cup - Medium", "Chalice Cup -Medium ($100)"):
        rows = _stock_rows_named(item, cat)
        assert rows, item
    assert [p["name"] for p in _stock_rows_named("Chalice Cup - Medium", cat)] \
        == ["Chalice Cup -Medium"]                        # not the $200 steel one


def test_a_real_question_still_goes_to_the_team():
    cat = _catalog()
    for item in ("golden communion cups",                  # names no row (alias ignored)
                 "bibles",                                 # half of "NIV BIBLE" is not it
                 "Aluminium Tray in black",                # a colour we may not make
                 "Aluminium Tray needed urgently",         # a date is a question
                 "Chalice Cup -Medium (as in customer photo)",
                 "Об'єм рідини (мл) для Chalice Cup -Medium",   # the real question unread
                 "Preaching Gown",                         # made to order: a READY piece?
                 "metal jug"):
        assert _stock_rows_named(item, cat) == [], item


def test_check_availability_answers_a_stock_item_without_asking_the_team(monkeypatch):
    _fake(monkeypatch)
    recorded = []

    async def fake_record(db, q, **kw):
        recorded.append(q)
        return True
    monkeypatch.setattr("app.services.demand.record", fake_record)

    class _NoDB:                       # any write would hit this and fail the test
        async def execute(self, *a, **k): raise AssertionError("team was asked")
        def add(self, row): raise AssertionError("note written")
        async def commit(self): raise AssertionError("committed")

    ctx = ToolContext(db=_NoDB(), redis=None, wa_id="260970000000", currency="ZMW")
    out = asyncio.run(tools._check_availability({"item": "Aluminium Tray"}, ctx))
    assert out["team_asked"] is False and out["availability"] == "available"
    assert out["rows"] == [{"name": "Aluminium Tray", "currency": "ZMW", "price": 1400}]
    assert "never say you are confirming" in out["note"]
    assert recorded == []


def test_check_availability_still_asks_the_team_for_a_variant(monkeypatch):
    _fake(monkeypatch)
    conv = SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700", person_id=None,
                           external_id="254700")
    added = []

    class _Res:
        def scalars(self): return self
        def first(self): return conv

    class _DB:
        async def execute(self, *a, **k): return _Res()
        def add(self, row): added.append(row)
        async def commit(self): ...

    async def fake_record(db, q, **kw):
        return True
    monkeypatch.setattr("app.services.demand.record", fake_record)

    ctx = ToolContext(db=_DB(), redis=None, wa_id="254700", currency="KES")
    out = asyncio.run(tools._check_availability({"item": "Aluminium Tray in black"}, ctx))
    assert "team_asked" not in out
    assert any(getattr(r, "media_type", "") == "note" for r in added)


def test_an_unreadable_catalogue_asks_the_team(monkeypatch):
    async def broken(db, redis):
        raise RuntimeError("hub down")
    monkeypatch.setattr(tools.svc, "catalog_items", broken)
    ctx = ToolContext(db=None, redis=None, wa_id="254700", currency="KES", read_only=True)
    out = asyncio.run(tools._check_availability({"item": "Aluminium Tray"}, ctx))
    assert out == {"ok": True, "item": "Aluminium Tray"}   # the normal path, no claim
