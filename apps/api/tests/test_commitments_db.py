"""ACCOUNTABLE COMMITMENTS on a real Postgres (owner's decision on safe-032,
2026-11-07): the sweep escalates an open team check by its age, the
customer's follow-up escalates it now, a colleague's reply closes it with
its age kept, out of hours it is queued, and health counts it. Skips without
a reachable Postgres."""
import asyncio
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401
from tests import test_calls_db as _calls, test_security_db as _sec

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark


def _settings(monkeypatch, *, hours="00-24", ack=5, sup=15):
    from app.services import commitments as cm
    monkeypatch.setattr(cm.settings, "commitment_staffed_hours", hours, raising=False)
    monkeypatch.setattr(cm.settings, "commitment_ack_minutes", ack, raising=False)
    monkeypatch.setattr(cm.settings, "commitment_supervisor_minutes", sup, raising=False)


def _open_check(env, wa, item="the cope", *, age_min, assigned=None):
    from app.services.channel import get_or_create_conversation
    from app.services.deals import open_team_check, open_deal_for
    from sqlalchemy.orm.attributes import flag_modified

    async def go():
        async with env.maker() as db:
            conv = await get_or_create_conversation(db, "whatsapp", wa, wa_id=wa)
            conv.assigned_agent_id = assigned
            await db.commit()
            await open_team_check(db, conv, item)
            deal = await open_deal_for(db, conversation_id=conv.id)
            nxt = dict(deal.next_action)
            nxt["since"] = (datetime.now(timezone.utc) - timedelta(minutes=age_min)).isoformat(timespec="seconds")
            deal.next_action = nxt
            flag_modified(deal, "next_action")
            await db.commit()
            return str(conv.id)
    return asyncio.run(go())


def _deal(env, conv_id):
    from app.services.deals import open_deal_for

    async def go():
        async with env.maker() as db:
            d = await open_deal_for(db, conversation_id=conv_id)
            return dict(d.next_action or {}) if d else None
    return asyncio.run(go())


def _bells(env, kind=None):
    return [m for c, m in env.redis.published
            if c == "ws:channel:agents:all" and str(m.get("type", "")).startswith("commitment_")
            and (kind is None or m["type"] == kind)]


def _flags(env, conv_id):
    import sqlalchemy as sa
    eng = sa.create_engine(env.sync_url) if hasattr(env, "sync_url") else None
    from app.models.intercept import Intercept
    from sqlalchemy import select

    async def go():
        async with env.maker() as db:
            rows = (await db.execute(select(Intercept.note).where(Intercept.conversation_id == conv_id))).scalars().all()
            return [r for r in rows if r and "UNANSWERED CHECK" in r]
    if eng:
        eng.dispose()
    return asyncio.run(go())


def test_the_sweep_escalates_by_age_once_per_stage_and_health_counts_it(env, world, monkeypatch):
    from app.services import commitments as cm
    _settings(monkeypatch)
    cid = _open_check(env, "254700000701", age_min=10)
    out = asyncio.run(cm.sweep(env.redis))
    assert out["open"] == 1 and out["overdue"] == 1 and out["team"] == 1 and out["supervisor"] == 0
    esc = _deal(env, cid)["escalation"]
    assert esc["stage"] == "team" and esc["owner"] == "needs an owner"
    assert len(_bells(env, "commitment_team")) == 1 and len(_flags(env, cid)) == 1
    # the same tick again: nothing new
    out = asyncio.run(cm.sweep(env.redis))
    assert out["team"] == 0 and len(_bells(env)) == 1 and len(_flags(env, cid)) == 1
    # time passes: the supervisor stage, once
    _settings(monkeypatch, sup=8)
    out = asyncio.run(cm.sweep(env.redis))
    assert out["supervisor"] == 1
    assert _deal(env, cid)["escalation"]["stage"] == "supervisor"
    assert [b["type"] for b in _bells(env)] == ["commitment_team", "commitment_supervisor"]
    view = asyncio.run(cm.health_view())
    assert view["open"] == 1 and view["overdue"] == 1 and view["unowned"] == 1
    assert view["escalated"] == {"team": 0, "supervisor": 1} and view["oldest_min"] >= 10


def test_a_customer_following_up_escalates_now_and_the_writer_is_told(env, world, monkeypatch):
    from app.services import commitments as cm
    from app.services.customer_state import live_note
    _settings(monkeypatch)
    cid = _open_check(env, "254700000702", age_min=1500)          # promised yesterday

    async def go():
        async with env.maker() as db:
            note = await cm.customer_followed_up(db, env.redis, "254700000702", "whatsapp")
            live = await live_note(db, "254700000702", "whatsapp")
            return note, live
    note, live = asyncio.run(go())
    assert "referred to the team for a manual check" in note and "promised a day ago" in note
    assert "referred to the team for a manual check" in (live or "")
    esc = _deal(env, cid)["escalation"]
    assert esc["stage"] == "supervisor" and esc["follow_ups"] == 1 and esc["last_follow_up"]
    assert len(_bells(env)) == 1 and "followed up 1×" in _bells(env)[0]["body"]
    # a fresh check is NOT escalated by a follow-up — the ordinary note stands
    cid2 = _open_check(env, "254700000703", age_min=1)

    async def go2():
        async with env.maker() as db:
            return await cm.customer_followed_up(db, env.redis, "254700000703", "whatsapp")
    assert asyncio.run(go2()) is None and "escalation" not in _deal(env, cid2)


def test_a_colleagues_reply_closes_it_and_keeps_the_age(env, world, monkeypatch):
    from app.services import commitments as cm
    from app.services.deals import clear_team_check
    _settings(monkeypatch)
    cid = _open_check(env, "254700000704", age_min=30, assigned=world["ann"])
    asyncio.run(cm.sweep(env.redis))
    assert _deal(env, cid)["escalation"]["owner"] == "Ann Wanjiru"

    async def go():
        async with env.maker() as db:
            return await clear_team_check(db, cid, by=f"agent:{world['ann']}")
    assert asyncio.run(go()) is True
    closed = _deal(env, cid)
    assert closed["kind"] == "team_check_closed" and closed["item"] == "the cope"
    assert 29 <= closed["age_min"] <= 31 and closed["escalation"]["stage"] == "supervisor"
    view = asyncio.run(cm.health_view())
    assert view["open"] == 0 and view["overdue"] == 0


def test_out_of_hours_is_queued_for_the_next_staffed_start_without_a_bell(env, world, monkeypatch):
    from app.services import commitments as cm
    _settings(monkeypatch, hours="07-21")
    cid = _open_check(env, "254700000705", age_min=60)
    night = datetime.now(timezone.utc).replace(hour=20, minute=30)          # 23:30 Nairobi
    out = asyncio.run(cm.sweep(env.redis, now=night))
    assert out["queued"] == 1 and out["team"] == 0 and out["supervisor"] == 0
    esc = _deal(env, cid)["escalation"]
    assert esc.get("queued_for") and "stage" not in esc and not _bells(env)
    # the next staffed morning: it rings
    morning = night + timedelta(hours=8)                                       # 07:30 Nairobi
    out = asyncio.run(cm.sweep(env.redis, now=morning))
    assert out["supervisor"] == 1 and len(_bells(env)) == 1
