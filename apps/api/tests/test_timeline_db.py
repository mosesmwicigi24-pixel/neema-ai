"""THE CUSTOMER TIMELINE on a real Postgres (owner's directive, 2026-11-09):
a promised check answered, a hold the customer asked for and a stage move
each write one customer-level row; the ledger returns them with their level
and folds the repeated searches. Skips without Postgres."""
import asyncio
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401
from sqlalchemy import select
from tests import test_calls_db as _calls, test_security_db as _sec

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark

WA = "254733000001"


def test_state_changes_become_customer_level_lines_and_searches_fold(env, world):
    from app.models.agent_activity import AgentActivity
    from app.routers.admin import get_conversation_activity
    from app.services import activity_trail, customer_state
    from app.services.channel import get_or_create_conversation
    from app.services.deals import clear_team_check, open_deal_for, open_team_check
    from app.services.messaging import provision_user

    async def go():
        async with env.maker() as db:
            await provision_user(db, WA, name="Grace")
            conv = await get_or_create_conversation(db, "whatsapp", WA, wa_id=WA)
            await db.commit()
            conv_id = conv.id
            # three searches in a minute: technical, foldable
            for q in ("tray", "cope", "stole"):
                await activity_trail.record(db, channel="whatsapp", contact=WA, tool="search_catalog",
                                            args={"query": q}, out={"count": 2, "results": []})
            # a promised check, opened then answered
            await open_team_check(db, conv, "the cope")
            deal = await open_deal_for(db, conversation_id=conv_id)
            from sqlalchemy.orm.attributes import flag_modified
            nxt = dict(deal.next_action)
            nxt["since"] = (datetime.now(timezone.utc) - timedelta(minutes=42)).isoformat(timespec="seconds")
            deal.next_action = nxt
            flag_modified(deal, "next_action")
            await db.commit()
            assert await clear_team_check(db, conv_id, by="Ann")
            # the customer asks for time (the floor's reading)
            deal = await open_deal_for(db, conversation_id=conv_id)
            reading = customer_state.floor("Let me think about it and get back to you next week")
            assert reading and reading["customer_said"] == "needs_time"
            await customer_state.apply(db, conv, deal, reading, source="floor",
                                       inbound_text="Let me think about it and get back to you next week")
            # the same reading again is not news
            await customer_state.apply(db, conv, deal, reading, source="floor",
                                       inbound_text="still thinking")

        async with env.maker() as db:
            rows = (await db.execute(select(AgentActivity).where(AgentActivity.contact == WA)
                                     .order_by(AgentActivity.created_at))).scalars().all()
            by_tool = {}
            for r in rows:
                by_tool.setdefault(r.tool, []).append(r)
            assert len(by_tool["search_catalog"]) == 3
            assert len(by_tool["commitment"]) == 1
            assert by_tool["commitment"][0].summary == "Promised check answered"
            assert "answered by Ann after 42 min" in by_tool["commitment"][0].detail
            assert len(by_tool["customer_state"]) == 1                   # one hold, not two
            assert by_tool["customer_state"][0].summary == "Asked for time"
            assert by_tool["customer_state"][0].detail.startswith("on hold until ")
            assert all(r.conversation_id == conv_id for r in rows)

            out = await get_conversation_activity(str(conv_id), db=db, agent=None)
            assert out["levels"]["technical"] == 3
            assert out["levels"]["customer"] >= 3               # deal + commitment + hold (+ the team-check flag rows)
            folded = [e for e in out["events"] if e["kind"] == "tool"]
            assert len(folded) == 1 and folded[0]["count"] == 3 and folded[0]["level"] == "technical"
            kinds = {e["kind"] for e in out["events"]}
            assert {"commitment", "customer_state", "deal"} <= kinds
            cust = await get_conversation_activity(str(conv_id), db=db, agent=None, level="customer")
            assert all(e["level"] == "customer" for e in cust["events"])
            assert not any(e["kind"] == "tool" for e in cust["events"])
    asyncio.run(go())
