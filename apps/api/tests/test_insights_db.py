"""INSIGHTS on a real Postgres (owner's directive, 2026-11-09): the panel and
the leads list score the same customer the same, from paid orders and the
open unpaid one; a Messenger-linked customer's conversations and orders count
on both sides; the snapshot names the unpaid order. Skips without Postgres."""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401
from tests import test_calls_db as _calls, test_security_db as _sec

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark

WA_PAID, WA_OPEN = "254711000001", "254711000002"


def _req():
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=None)))


def test_panel_and_list_agree_and_keep_paid_apart_from_unpaid(env, world, monkeypatch):
    from app.core import hub_client
    from app.models.order_event import OrderEvent
    from app.routers import crm
    from app.services.channel import get_or_create_conversation
    from app.services.identity import resolve_or_create_person
    from app.services.messaging import provision_user

    async def no_hub(*a, **k):
        return None
    monkeypatch.setattr(hub_client, "fetch_customer_summary", no_hub)
    now = datetime.now(timezone.utc)

    async def go():
        async with env.maker() as db:
            paid = await provision_user(db, WA_PAID, name="Paid Customer")
            open_ = await provision_user(db, WA_OPEN, name="Open Customer")
            c1 = await get_or_create_conversation(db, "whatsapp", WA_PAID, wa_id=WA_PAID)
            c2 = await get_or_create_conversation(db, "whatsapp", WA_OPEN, wa_id=WA_OPEN)
            c1.last_message_at = now - timedelta(days=2)
            c2.last_message_at = now - timedelta(days=1)
            # the open customer also wrote on Messenger: linked by person, no wa_id
            ident = await resolve_or_create_person(db, "messenger", "psid-ins-1", source="test")
            c3 = await get_or_create_conversation(db, "messenger", "psid-ins-1")
            c3.person_id = open_.person_id
            c3.last_message_at = now - timedelta(days=1)
            ident.person_id = open_.person_id
            db.add(OrderEvent(id=f"{WA_PAID}_1", wa_id=WA_PAID, person_id=paid.person_id,
                              event_type="confirmed", items=[{"name": "Cassock"}], subtotal=15000,
                              currency="KES", status="pending", payment_status="unpaid",
                              hub_payment_status="paid", hub_order_id=901, hub_order_number="BH-901",
                              created_at=now - timedelta(days=20)))
            db.add(OrderEvent(id=f"{WA_OPEN}_1", wa_id=WA_OPEN, person_id=open_.person_id,
                              event_type="confirmed", items=[{"name": "Collar"}], subtotal=6000,
                              currency="KES", status="pending", payment_status="unpaid",
                              hub_order_id=902, hub_order_number="BH-902",
                              created_at=now - timedelta(days=1)))
            await db.commit()

        async with env.maker() as db:
            leads = {row["wa_id"]: row for row in await crm.list_leads(stage=None, db=db, agent=None)}
            p_paid = await crm.get_customer(WA_PAID, _req(), db=db, agent=None)
            p_open = await crm.get_customer(WA_OPEN, _req(), db=db, agent=None)

        # the same number in the list and the panel, for both customers
        assert leads[WA_PAID]["lead_score"] == p_paid["lead_score"]
        assert leads[WA_OPEN]["lead_score"] == p_open["lead_score"]
        # paid and unpaid kept apart, on both sides
        assert (p_paid["paid_orders"], p_paid["paid_spent"], p_paid["unpaid_orders"]) == (1, 15000.0, 0)
        assert (leads[WA_PAID]["paid_orders"], leads[WA_PAID]["paid_spent"]) == (1, 15000.0)
        assert (p_open["paid_orders"], p_open["unpaid_orders"], p_open["unpaid_spent"]) == (0, 1, 6000.0)
        assert leads[WA_OPEN]["open_order"] is True and p_open["open_order"]["number"] == "BH-902"
        rows_open = {r["label"]: r["pts"] for r in p_open["lead_score_breakdown"]}
        rows_paid = {r["label"]: r["pts"] for r in p_paid["lead_score_breakdown"]}
        assert rows_open["Paid orders"] == 0 and rows_open["Open order (unpaid)"] == 10
        assert rows_paid["Paid orders"] == 10 and rows_paid["Open order (unpaid)"] == 0
        # the Messenger thread counts on both sides (multi-channel)
        assert rows_open["Multi-channel"] == 10 and set(leads[WA_OPEN]["channels"]) == {"whatsapp", "messenger"}
        # the snapshot names the unpaid order as the next best action
        assert p_open["snapshot"]["next_best_action"]["kind"] == "collect_payment"
        assert "BH-902" in p_open["snapshot"]["next_best_action"]["action"]
        assert p_paid["snapshot"]["next_best_action"]["kind"] == "none"
        # the stage: an order placed → negotiation suggested; nobody is "qualified" by a prefix
        assert p_paid["suggested_lead_stage"] == "negotiation"
    asyncio.run(go())
