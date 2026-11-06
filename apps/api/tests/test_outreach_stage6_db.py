"""OUTBOUND COMMUNICATION, STAGE 6 — on a real Postgres: the backlog view
over real rows and the retire command sparing promises and care; the planners
through plan() under the unique index. Skips without a reachable Postgres."""
import uuid
from datetime import datetime, timedelta, timezone

from tests.test_outreach_stage2_db import _rows, _seed, maker, run  # noqa: F401 — the fixture
from tests.test_security_db import fresh_db, pytestmark  # noqa: F401

GRACE = "254722000111"


def _park(maker, cid, kind, reason, *, days_ago):  # noqa: F811
    from app.models.agent_action import AgentAction

    async def go():
        async with maker() as db:
            row = AgentAction(id=uuid.uuid4(), conversation_id=cid, kind=kind, status="needs_approval",
                              due_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
                              reason=reason, dedupe_key=f"{kind}:{uuid.uuid4().hex[:6]}", source="test")
            db.add(row)
            await db.flush()
            from sqlalchemy import update
            await db.execute(update(AgentAction).where(AgentAction.id == row.id)
                             .values(created_at=datetime.now(timezone.utc) - timedelta(days=days_ago)))
            await db.commit()
    run(go())


def test_the_backlog_is_readable_and_the_retire_command_spares_promises_and_care(maker, monkeypatch, capsys):  # noqa: F811
    cid = _seed(maker, GRACE, name="Grace W.")
    _park(maker, cid, "quote_follow_up", "Quoted … [needs approval: outside the 24h messaging window]", days_ago=45)
    _park(maker, cid, "buying_follow_up", "Cart … [needs approval: outside the 24h messaging window]", days_ago=12)
    _park(maker, cid, "check_in", "Customer-agreed check-in (WhatsApp): Thursday [needs approval: outside the 24h messaging window]", days_ago=60)
    _park(maker, cid, "fit_check", "Order BH-9 … [needs approval: team still confirming: x]", days_ago=50)

    from app.services import outreach_log as ol
    async def view():
        async with maker() as db:
            return await ol.backlog_view(db)
    v = run(view())
    assert v["total"] == 4 and v["by_reason"] == {"window": 3, "team_check": 1}
    assert v["by_age"] == {"over_30d": 3, "7_to_30d": 1}

    import app.database as database
    from app.jobs import outreach_backlog
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)
    assert run(outreach_backlog._main(30)) == 0
    out = capsys.readouterr().out
    assert "retired 1 routine row(s)" in out and "2 older row(s) left for a person" in out
    status = {k: st for k, st, *_ in _rows(maker, cid)}
    assert status == {"quote_follow_up": "vetoed", "buying_follow_up": "needs_approval",
                      "check_in": "needs_approval", "fit_check": "needs_approval"}
    retired = next(r for r in _rows(maker, cid) if r[0] == "quote_follow_up")
    assert "[retired: parked 30+ days — the moment has passed]" in retired[4]


def test_the_fit_check_planner_is_one_row_per_order_under_the_index(maker):  # noqa: F811
    from app.services import hub_events
    cid = _seed(maker, GRACE, name="Grace W.")

    async def plan_twice():
        async with maker() as db:
            from app.models.conversation import Conversation
            conv = await db.get(Conversation, cid)
            await hub_events._plan_fit_check(db, None, conv, {"order_number": "BH-77"})
            await hub_events._plan_fit_check(db, None, conv, {"order_number": "BH-77"})
            await hub_events._plan_fit_check(db, None, conv, {"order_number": "BH-78"})
    run(plan_twice())
    keys = sorted(r[2] for r in _rows(maker, cid))
    assert keys == ["care:BH-77", "care:BH-78"]
