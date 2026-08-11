"""Stock is never a customer topic (owner rule): the model is never shown
"out of stock" or remaining counts — everything is sold as available, and a hub
shortfall becomes a SOURCING flag for the team at order time instead."""
import asyncio
from types import SimpleNamespace

from app.agent import tools
from app.agent.tools import _search_catalog, _sourcing_gaps, _cart_display, ToolContext
from app.agent.prompt import build_system_prompt


def _catalog():
    return [
        {"hub_product_id": 1, "name": "Communion Wafers", "sku": "W1", "price": 800,
         "price_usd": 8, "category": "Communion", "in_stock": False, "available_qty": 0},
        {"hub_product_id": 2, "name": "Communion Cups", "sku": "CU1", "price": 1500,
         "price_usd": 15, "category": "Communion", "in_stock": True, "available_qty": 2},
        {"hub_product_id": 3, "name": "Cassock", "sku": "C1", "price": 12000,
         "price_usd": 120, "category": "Vestments", "product_type": "variable",
         "is_producible": True},
    ]


def test_search_never_exposes_stock_state_or_counts(monkeypatch):
    async def fake_catalog(db, redis):
        return _catalog()
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    ctx = ToolContext(db=None, redis=None, wa_id="254700", currency="KES")

    out = asyncio.run(_search_catalog({"query": "communion"}, ctx))
    for r in out["results"]:
        assert r["availability"] == "available"     # even the out-of-stock wafers
        assert "available_qty" not in r
        assert "in_stock" not in r


def test_cart_display_strips_internal_stock_flag():
    cart = {"items": [{"name": "Communion Wafers", "qty": 500, "unit_price": 800,
                       "hub_product_id": 1, "in_stock": False}]}
    ctx = SimpleNamespace(currency="KES", usd_rate=100, db=None, redis=None)
    items, total = asyncio.run(_cart_display(cart, ctx))
    assert "in_stock" not in items[0]                    # model never sees it
    assert cart["items"][0]["in_stock"] is False         # stored line keeps it


def test_sourcing_gaps_flags_shortfalls_only():
    items = [
        {"hub_product_id": 1, "name": "Communion Wafers", "qty": 500},   # out of stock
        {"hub_product_id": 2, "name": "Communion Cups", "qty": 5},       # only 2 on hand
        {"hub_product_id": 3, "name": "Cassock", "qty": 10},             # made-to-order → never a gap
    ]
    gaps = _sourcing_gaps(items, _catalog())
    assert gaps == ["Communion Wafers ×500 (hub: out of stock)",
                    "Communion Cups ×5 (hub: only 2 on hand)"]
    # covered lines produce no flag
    assert _sourcing_gaps([{"hub_product_id": 2, "name": "Communion Cups", "qty": 2}],
                          _catalog()) == []
    assert _sourcing_gaps([], _catalog()) == []


def test_prompt_forbids_stock_talk():
    for currency in ("KES", "USD"):
        p = build_system_prompt(currency=currency)
        assert "STOCK IS NEVER A CUSTOMER TOPIC" in p
        assert "quote how many remain" in p              # no counts, ever
        assert "sourced before delivery" in p            # team flag, not customer news


# ── Never speak the absence (owner rule, 2026-07-31) ─────────────────────────
# Live miss: "We don't have a metal jug/flagon in stock right now, but we can
# source or make one" — the "but" doesn't rescue it; the customer hears no.


def test_prompt_forbids_the_hidden_but():
    p = " ".join(build_system_prompt(currency="KES").split())
    assert "NEVER SPEAK THE ABSENCE" in p
    assert "is the SAME mistake" in p               # the "but" loophole, named
    assert "check_availability" in p
    # And the upsell that must ride along in the same reply.
    assert "closest companions" in p and "communion table" in p
    # handoff is explicitly NOT the tool for a stock question.
    assert "never for a stock question" in p


def test_check_availability_records_demand_without_muting_neema(monkeypatch):
    """handoff_to_human flips the thread to human and silences her — an
    availability question must not."""
    from types import SimpleNamespace
    from app.models.conversation import InterceptMode

    conv = SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700", person_id=None,
                           external_id="254700", intercept_mode=InterceptMode.ai)
    added, recorded = [], {}

    class _Res:
        def scalars(self): return self
        def first(self): return conv

    class _DB:
        async def execute(self, *a, **k): return _Res()
        def add(self, row): added.append(row)
        async def commit(self): ...

    async def fake_record(db, q, **kw):
        recorded.update(query=q, kind=kw.get("kind"))
        return True
    monkeypatch.setattr("app.services.demand.record", fake_record)

    ctx = ToolContext(db=_DB(), redis=None, wa_id="254700", currency="KES")
    out = asyncio.run(tools._check_availability({"item": "metal jug"}, ctx))

    assert out["ok"] is True
    assert recorded["kind"] == "availability_check"
    assert conv.intercept_mode == InterceptMode.ai      # still hers to answer
    assert any(getattr(r, "media_type", "") == "note" for r in added)
    assert "never that we don't have it" in out["note"]


def test_check_availability_needs_an_item():
    ctx = ToolContext(db=None, redis=None, wa_id="254700", currency="KES")
    assert "error" in asyncio.run(tools._check_availability({"item": "  "}, ctx))


def test_check_availability_is_offered_on_messenger():
    from app.agent.runtime import MESSENGER_TOOLS
    assert any(t["name"] == "check_availability" for t in MESSENGER_TOOLS)


def test_every_note_writer_uses_a_real_sender():
    """MsgSender has no `agent` member — three services used it and, being
    best-effort, failed silently: the copilot briefing, the cross-channel
    handoff note and the hub-event escalation note never wrote a row."""
    import inspect
    from app.models.message import MsgSender
    from app.services import copilot, identity, hub_events
    from app.agent import tools as _t

    assert not hasattr(MsgSender, "agent")
    assert MsgSender.human_agent.value == "human_agent"
    for mod in (copilot, identity, hub_events, _t):
        assert "MsgSender.agent," not in inspect.getsource(mod), mod.__name__


# ── No price is not free (owner rule, 2026-08-11) ────────────────────────────
# The hub carries unpriced rows ("Bread container", KES 0) and same-name
# families (Gold/Silver Bread Tray vs the wafer-bread packs). A wrong or
# zero quote is worse than a confirming question.


def test_unpriced_product_is_never_quoted_as_zero(monkeypatch):
    async def fake_catalog(db, redis):
        return [
            {"hub_product_id": 9, "name": "Bread container", "sku": "BC1",
             "price": 0.0, "price_kes": None, "price_usd": None,
             "category": "Communion", "in_stock": True},
            {"hub_product_id": 10, "name": "Silver Bread Tray", "sku": "SBT",
             "price": 13000, "price_usd": 130, "category": "Communion",
             "in_stock": True},
        ]
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    ctx = ToolContext(db=None, redis=None, wa_id="254700", currency="KES")
    out = asyncio.run(_search_catalog({"query": "bread"}, ctx))
    by = {r["name"]: r for r in out["results"]}

    assert by["Bread container"]["price"] == ""            # never 0, never free
    assert "NEVER quote 0" in by["Bread container"]["price_status"]
    assert by["Silver Bread Tray"]["price"] == 13000       # the priced sibling intact
    assert "price_status" not in by["Silver Bread Tray"]


def test_unpriced_product_cannot_enter_the_cart(monkeypatch):
    from app.core import hub_client as hc

    async def fake_catalog(db, redis):
        return [{"name": "Bread container", "sku": "BC1"}]
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    monkeypatch.setattr(hc, "resolve_hub_line", lambda item, cat: {
        "product_id": 9, "name": "Bread container", "quantity": 1,
        "unit_price": 0, "is_producible": False})
    ctx = ToolContext(db=None, redis=None, wa_id="254700", currency="KES")
    assert asyncio.run(tools._resolve_cart_items("bread container", ctx)) == []


def test_prompt_teaches_the_same_name_families():
    p = " ".join(build_system_prompt(currency="KES").split())
    assert "SAME-NAME FAMILIES" in p
    assert "Gold Bread" in p and "wafer BREAD packs" in p
    assert "Round Collar Clergy" in p                      # the two-shirts trap
    assert "NO PRICE IS NOT FREE" in p
    assert "never from memory" in p
