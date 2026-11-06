"""OUTBOUND COMMUNICATION, STAGE 7 — on a real Postgres: a quotation updated
after its nudge was planned replaces the nudge (one pending row, the newer
draft, the old one says why), and a paid order withdraws every pending sales
nudge while a customer-agreed check-in survives."""
from datetime import datetime, timezone

from tests.test_outreach_stage2_db import _msg, _rows, _seed, maker, run  # noqa: F401 — the fixture
from tests.test_security_db import fresh_db, pytestmark  # noqa: F401
from app.core.config import settings

GRACE = "254722000111"


def _deal(maker, cid):  # noqa: F811
    from app.models.deal import Deal

    async def go():
        async with maker() as db:
            deal = Deal(conversation_id=cid, items_snapshot=[{"name": "Stole", "qty": 1, "price": 45}])
            db.add(deal)
            await db.commit()
            return deal.id
    return run(go())


def test_a_newer_quotation_replaces_the_planned_nudge(maker, monkeypatch):  # noqa: F811
    from app.services import quote_followup
    monkeypatch.setattr(settings, "quote_follow_up_enabled", True, raising=False)
    cid = _seed(maker, GRACE, name="Grace W.")
    _msg(maker, cid, GRACE, "inbound", "How much is the purple stole?", minutes_ago=5)
    did = _deal(maker, cid)

    async def quote(items, text):
        async with maker() as db:
            from app.models.conversation import Conversation
            from app.models.deal import Deal
            conv = await db.get(Conversation, cid)
            deal = await db.get(Deal, did)
            out = await quote_followup.on_turn(db, conv, deal, quote=items, inbound_text="", tools=None, reply=text)
            await db.commit()
            return out
    assert run(quote([{"name": "Purple Stole", "price": 45, "currency": "USD"}], "The Purple Stole is $45.")) == "planned"
    assert run(quote([{"name": "Purple Stole", "price": 40, "currency": "USD"}], "With the discount, $40.")) == "planned"
    rows = _rows(maker, cid)
    kinds = [(k, st) for k, st, *_ in rows]
    assert kinds.count(("quote_follow_up", "planned")) == 1
    old = [r for r in rows if r[1] == "vetoed"]
    assert len(old) == 1 and "superseded by a newer quote" in old[0][4]
    new = next(r for r in rows if r[1] == "planned")
    assert "40" in (new[5] or "") and "45" not in (new[5] or "")      # the draft follows the newer figure


def test_a_paid_order_withdraws_sales_nudges_but_keeps_the_customers_check_in(maker):  # noqa: F811
    from app.services import actions
    cid = _seed(maker, GRACE, name="Grace W.")
    did = _deal(maker, cid)
    now = datetime.now(timezone.utc)

    async def plan_all():
        async with maker() as db:
            await actions.plan(db, conversation_id=cid, kind="buying_follow_up", deal_id=did, due_at=now,
                               reason="They built a cart — Stole", source="cart_recovery")
            await actions.plan(db, conversation_id=cid, kind="follow_up", deal_id=did, due_at=now,
                               reason="Neema promised: confirm the embroidery", source="scribe")
            await actions.plan(db, conversation_id=cid, kind="check_in", due_at=now,
                               reason="Customer-agreed check-in (WhatsApp): Thursday", source="tool",
                               dedupe_key="check_in:purchase_decision")
    run(plan_all())

    async def paid():
        async with maker() as db:
            return await actions.withdraw_routine(db, cid, why="order paid")
    assert run(paid()) == 2
    status = {k: st for k, st, *_ in _rows(maker, cid)}
    assert status == {"buying_follow_up": "vetoed", "follow_up": "vetoed", "check_in": "planned"}
    assert all("[order paid]" in r[4] for r in _rows(maker, cid) if r[1] == "vetoed")
