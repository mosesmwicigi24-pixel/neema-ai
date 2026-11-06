"""The executive performance view on a real Postgres (intelligence programme
§7): measured figures carry their denominators and intervals; partial ones
say why; unmeasured ones name the instrumentation; nothing is estimated."""
import uuid
from datetime import datetime, timedelta, timezone

from tests.test_outreach_stage2_db import _msg, _seed, maker, run  # noqa: F401 — the fixture
from tests.test_security_db import fresh_db, pytestmark  # noqa: F401

WA = "254722000777"


def _order(maker, wa_id, *, paid: bool, hours_ago: int = 2, subtotal=4500):  # noqa: F811
    async def go():
        from app.models.order_event import OrderEvent
        async with maker() as s:
            s.add(OrderEvent(id=f"{wa_id}_{uuid.uuid4().hex[:8]}", wa_id=wa_id, items=[], subtotal=subtotal,
                             status="open", payment_status="paid" if paid else "unpaid",
                             hub_payment_status="paid" if paid else "unpaid",
                             created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago)))
            await s.commit()
    run(go())


def test_the_view_measures_what_it_can_and_says_what_it_cannot(maker):  # noqa: F811
    from app.services.performance import collect
    cid = _seed(maker, WA, name="Perf Customer")
    _msg(maker, cid, WA, "inbound", "How much is the stole?", minutes_ago=120)
    _msg(maker, cid, WA, "outbound", "The stole is KES 2,500.", minutes_ago=119)
    _msg(maker, cid, WA, "inbound", "Ok I'll take two", minutes_ago=60)
    _msg(maker, cid, WA, "outbound", "Order placed.", minutes_ago=58)
    _order(maker, WA, paid=True, hours_ago=1)
    _order(maker, WA, paid=False, hours_ago=1)

    async def go():
        from app.models.intercept import Intercept, InterceptAction
        from app.models.person import Person
        from sqlalchemy import select
        from app.models.conversation import Conversation
        async with maker() as s:
            conv = (await s.execute(select(Conversation).where(Conversation.wa_id == WA))).scalars().first()
            s.add(Intercept(conversation_id=conv.id, action=InterceptAction.intercept))
            p = Person(state={"contact_preferences": {"opt_out": {
                "at": datetime.now(timezone.utc).isoformat(), "channel": "whatsapp", "said": "stop"}}})
            s.add(p)
            await s.commit()
        async with maker() as s:
            return await collect(s, None, days=7)
    out = run(go())

    m = out["metrics"]
    assert out["counts"]["measured"] >= 5 and out["counts"]["not_measured"] >= 8
    fr = m["first_response_neema"]
    assert fr["status"] == "measured" and fr["n"] == 2 and 50 < fr["value"] < 130
    conv = m["verified_paid_conversion"]
    assert conv["status"] == "partial" and conv["n"] == 2 and conv["value"] == 0.5 and conv["ci95"]
    assert "Neema-placed" in conv["caveat"]
    assert m["revenue_paid"]["value"] == 4500.0 and m["revenue_placed_unpaid"]["value"] == 4500.0
    assert m["sales_autonomous"]["value"] == 2 and m["sales_assisted"]["value"] == 0
    assert m["human_intervention"]["status"] == "measured" and m["human_intervention"]["value"] == 1.0
    assert m["opt_outs"]["value"] == 1 and m["opt_outs"]["n"] >= 1
    for key in ("emotional_appropriateness", "customer_rating", "turn_latency", "sales_human_only",
                "intent_next_action", "resolution"):
        assert m[key]["status"] == "not_measured" and m[key]["instrumentation"], key
        assert m[key]["value"] is None
    assert m["model_cost"]["status"] == "measured" and m["model_cost"]["unit"] == "USD"


def test_an_eval_history_row_turns_the_eval_metrics_measured(maker):  # noqa: F811
    import json
    from app.services.app_settings import set_value
    from app.services.performance import collect
    row = {"at": "2026-11-06T12:00:00+00:00", "git": "abc1234", "case_set": "deadbeef", "selection": "file:blind_heldout.jsonl",
           "cases": 227, "repeat": 1, "producer": "claude-sonnet-5-5", "prompt": "p1",
           "turns": {"k": 500, "n": 618, "p": 0.809, "ci95": [0.776, 0.838]},
           "critical": {"k": 200, "n": 240, "p": 0.833, "ci95": [0.78, 0.875]},
           "language": {"k": 140, "n": 150, "p": 0.933, "ci95": [0.88, 0.96]},
           "figures": {"k": 90, "n": 100, "p": 0.9, "ci95": [0.83, 0.94]},
           "length": {"k": 1, "n": 2, "p": 0.5, "ci95": [0.1, 0.9]}, "first_draft": {"k": 1, "n": 2, "p": 0.5, "ci95": [0.1, 0.9]},
           "next_action": {}}

    async def go():
        async with maker() as s:
            await set_value(s, "eval_history", json.dumps([row]))
            await s.commit()
        async with maker() as s:
            return await collect(s, None, days=7)
    out = run(go())
    m = out["metrics"]["intent_next_action"]
    assert m["status"] == "measured" and m["value"] == 0.809 and m["n"] == 618 and m["ci95"] == [0.776, 0.838]
    assert "claude-sonnet-5-5" in m["basis"]
    assert out["eval_history"][-1]["git"] == "abc1234"
