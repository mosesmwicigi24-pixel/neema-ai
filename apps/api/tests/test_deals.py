"""Phase B1 — the deal scribe: Neema owns outcomes, the scribe files them."""
import asyncio
import types

import pytest

from app.services import deals as ds


def test_promise_detection_is_conservative():
    assert ds.detect_own_promise("Let me check with the workshop and get back to you shortly.")
    assert ds.detect_own_promise("I'll confirm the shipping cost for Johannesburg today.")
    assert ds.detect_own_promise("I will find out about the gold thread option.")
    # No promise → no commitment (never nag over nothing)
    assert ds.detect_own_promise("The cassock is KES 12,000. Which colour would you like?") is None
    assert ds.detect_own_promise("Asante! Your order is confirmed.") is None
    assert ds.detect_own_promise("") is None


def test_stage_derivation_is_forward_only():
    assert ds.derive_stage(3, "new") == "qualified"
    assert ds.derive_stage(0, "new") == "new"
    assert ds.derive_stage(0, "qualified") == "qualified"     # cart cleared ≠ demoted
    for terminal in ("won", "lost", "proposal"):
        assert ds.derive_stage(5, terminal) == terminal        # operator/hook wins


def test_scribe_creates_deal_on_buying_signal(monkeypatch):
    from app.agent import cart as cartmod

    conv = types.SimpleNamespace(id="conv1", person_id="p1")
    added, commits = [], []

    class _DB:
        def add(self, o): added.append(o)
        async def commit(self): commits.append(1)
        async def rollback(self): pass

    async def fake_conv(db, key, channel): return conv
    async def fake_open(db, conversation_id=None, person_id=None): return None
    async def fake_cart(db, key, channel="whatsapp"):
        return {"items": [{"name": "Cassock", "qty": 3, "price": 12000}]}
    monkeypatch.setattr(ds, "_conversation_of", fake_conv)
    monkeypatch.setattr(ds, "open_deal_for", fake_open)
    monkeypatch.setattr(cartmod, "get_cart", fake_cart)

    asyncio.run(ds.scribe_update(_DB(), "254700000001", "whatsapp",
                                 "Added 3 cassocks. Let me confirm the delivery cost and get back to you."))
    assert len(added) == 1 and commits
    deal = added[0]
    assert deal.items_snapshot[0]["name"] == "Cassock"
    assert deal.title == "Cassock"
    assert deal.stage == "qualified"
    assert deal.blocking.startswith("Neema owes the customer")
    assert deal.next_action["owner"] == "ai"
    assert deal.next_action["kind"] == "follow_up"


def test_scribe_stays_silent_on_smalltalk(monkeypatch):
    from app.agent import cart as cartmod
    conv = types.SimpleNamespace(id="conv1", person_id="p1")
    added = []

    class _DB:
        def add(self, o): added.append(o)
        async def commit(self): raise AssertionError("nothing should commit")
        async def rollback(self): pass

    async def fake_conv(db, key, channel): return conv
    async def fake_open(db, conversation_id=None, person_id=None): return None
    async def fake_cart(db, key, channel="whatsapp"): return {"items": []}
    monkeypatch.setattr(ds, "_conversation_of", fake_conv)
    monkeypatch.setattr(ds, "open_deal_for", fake_open)
    monkeypatch.setattr(cartmod, "get_cart", fake_cart)

    asyncio.run(ds.scribe_update(_DB(), "254700000001", "whatsapp",
                                 "Good morning! How can I help you today?"))
    assert added == []                       # greetings don't deserve deal rows


def test_mark_won_clears_the_deal(monkeypatch):
    deal = types.SimpleNamespace(stage="qualified", status="open",
                                 blocking="x", next_action={"kind": "follow_up"})
    commits = []

    class _DB:
        async def commit(self): commits.append(1)
        async def rollback(self): pass

    async def fake_open(db, conversation_id=None, person_id=None): return deal
    monkeypatch.setattr(ds, "open_deal_for", fake_open)
    asyncio.run(ds.mark_won_for_conversation(_DB(), "conv1"))
    assert deal.stage == "won" and deal.status == "won"
    assert deal.blocking is None and deal.next_action is None
    assert commits


def test_deal_routes_registered():
    from app.routers.crm import router
    paths = {(r.path, tuple(sorted(r.methods or []))) for r in router.routes}
    assert ("/deals", ("GET",)) in paths
    assert ("/deals/{deal_id}", ("PATCH",)) in paths
