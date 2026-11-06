"""Owner, 2026-10-29: "build it" — every follow-up a daily sweep sends is
recorded, and the Reports page reads what each customer did next: wrote back
within 72 hours, then ordered within 7 days (payment reminder: the order was
paid). Sends younger than 72 hours are "waiting" and kept out of the rates.

Skips cleanly without a database (the Docker harness / CI migrations job has one).
"""
import asyncio
import types
from datetime import datetime, timezone
import uuid

import pytest

from app.core.config import settings
import sqlalchemy as sa

from tests.test_security_db import _reachable, _sync_url, fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = pytest.mark.skipif(
    not _sync_url() or not _reachable(_sync_url()),
    reason="needs a reachable Postgres (CI migrations job / Docker harness)")

WA = ["254700777001", "254700777002", "254700777003", "254700777004"]


@pytest.fixture
def env(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as database

    async_url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)

    convs = [str(uuid.uuid4()) for _ in WA]
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE recovery_sends, agent_actions, order_events, messages, conversations CASCADE"))
        for cid, wa in zip(convs, WA):
            c.execute(sa.text(
                "INSERT INTO conversations (id, wa_id, channel, external_id, intercept_mode, status, created_at, updated_at) "
                "VALUES (:id, :wa, 'whatsapp', :wa, 'ai', 'open', NOW(), NOW())"), {"id": cid, "wa": wa})
    yield types.SimpleNamespace(url=fresh_db, eng=eng, maker=maker, convs=convs)
    eng.dispose()


def _send(c, job, conv, ago, ref=None):
    c.execute(sa.text(
        "INSERT INTO recovery_sends (id, job, conversation_id, channel, ref, sent_at) "
        "VALUES (:id, :job, :conv, 'whatsapp', :ref, NOW() - CAST(:ago AS interval))"),
        {"id": str(uuid.uuid4()), "job": job, "conv": conv, "ref": ref, "ago": ago})


def _msg(c, conv, wa, ago, direction="inbound", media_type=None):
    c.execute(sa.text(
        "INSERT INTO messages (id, wa_id, channel, external_id, conversation_id, direction, sender, text, media_type, created_at) "
        "VALUES (:id, :wa, 'whatsapp', :wa, :c, :d, :s, 'hi', :mt, NOW() - CAST(:ago AS interval))"),
        {"id": str(uuid.uuid4()), "wa": wa, "c": conv, "d": direction,
         "s": "user" if direction == "inbound" else "agent", "mt": media_type, "ago": ago})


def _order(c, wa, ago, hub_order_id=None, hub_payment_status=None):
    c.execute(sa.text(
        "INSERT INTO order_events (id, wa_id, items, subtotal, currency, status, payment_status, "
        "fulfillment_status, channel, state, created_at, updated_at, hub_order_id, hub_payment_status) "
        "VALUES (:id, :wa, '[]', 0, 'KES', 'open', 'unpaid', 'pending', 'whatsapp', '{}', "
        "NOW() - CAST(:ago AS interval), NOW(), :hid, :hps)"),
        {"id": f"{wa}_{uuid.uuid4().hex[:8]}", "wa": wa, "ago": ago, "hid": hub_order_id,
         "hps": hub_payment_status})


def _results(env, days=30):
    from app.services import recovery_results

    async def go():
        async with env.maker() as db:
            return await recovery_results.results(db, days)
    return {j["job"]: j for j in asyncio.run(go())["jobs"]}


def test_reply_and_order_are_read_per_send(env):
    a, b, c_, d = env.convs
    with env.eng.begin() as c:
        # a: nudged 5 days ago, answered a day later, ordered 2 days later → replied + converted
        _send(c, "cart_recovery", a, "5 days")
        _msg(c, a, WA[0], "4 days")
        _order(c, WA[0], "3 days")
        # b: nudged 5 days ago, answered only after 4 days (outside 72 h), never ordered
        _send(c, "cart_recovery", b, "5 days")
        _msg(c, b, WA[1], "1 day")
        # c: nudged 5 days ago; only a staff NOTE followed, and an order from BEFORE the nudge
        _send(c, "cart_recovery", c_, "5 days")
        _msg(c, c_, WA[2], "4 days", direction="inbound", media_type="note")
        _order(c, WA[2], "6 days")
        # d: nudged an hour ago → waiting, kept out of the rates
        _send(c, "cart_recovery", d, "1 hour")
        _msg(c, d, WA[3], "30 minutes")
        # outside the 30-day period → not counted at all
        _send(c, "cart_recovery", a, "40 days")

    r = _results(env)["cart_recovery"]
    assert (r["sent"], r["waiting"], r["settled"]) == (4, 1, 3)
    assert (r["replied"], r["converted"]) == (1, 1)
    assert r["reply_rate"] == 33.3 and r["convert_rate"] == 33.3


def test_a_payment_reminder_converts_when_its_order_is_paid(env):
    a, b, *_ = env.convs
    with env.eng.begin() as c:
        _order(c, WA[0], "10 days", hub_order_id=501, hub_payment_status="paid")
        _order(c, WA[1], "10 days", hub_order_id=502, hub_payment_status="unpaid")
        _order(c, WA[1], "10 days", hub_order_id=503, hub_payment_status=None)
        _send(c, "payment_followup", a, "4 days", ref="501")
        _send(c, "payment_followup", b, "4 days", ref="502,503")
    r = _results(env)["payment_followup"]
    assert (r["sent"], r["settled"], r["converted"]) == (2, 2, 1)


def test_quote_follow_ups_are_read_from_their_own_rows(env):
    a, *_ = env.convs
    with env.eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO agent_actions (id, conversation_id, due_at, kind, reason, status, created_by, created_at, updated_at) "
            "VALUES (:id, :c, NOW() - interval '5 days', 'quote_follow_up', 'q', 'sent', 'ai', "
            "NOW() - interval '6 days', NOW() - interval '5 days')"), {"id": str(uuid.uuid4()), "c": a})
        c.execute(sa.text(
            "INSERT INTO agent_actions (id, conversation_id, due_at, kind, reason, status, created_by, created_at, updated_at) "
            "VALUES (:id, :c, NOW() - interval '5 days', 'quote_follow_up', 'q', 'vetoed', 'ai', "
            "NOW() - interval '6 days', NOW() - interval '5 days')"), {"id": str(uuid.uuid4()), "c": a})
        _msg(c, a, WA[0], "4 days")
    r = _results(env)
    assert (r["quote_follow_up"]["sent"], r["quote_follow_up"]["replied"]) == (1, 1)
    # every job is always listed, an empty one with no rate rather than 0 %
    assert r["reengage"]["sent"] == 0 and r["reengage"]["reply_rate"] is None


def test_record_send_writes_one_row_and_never_raises(env, monkeypatch):
    from app.services import recovery_results
    conv = types.SimpleNamespace(id=uuid.UUID(env.convs[0]), person_id=None, channel="whatsapp")
    assert asyncio.run(recovery_results.record_send("reengage", conv)) is True
    with env.eng.begin() as c:
        rows = c.execute(sa.text("SELECT job, channel, ref FROM recovery_sends")).all()
    assert [tuple(r) for r in rows] == [("reengage", "whatsapp", None)]

    import app.database as database

    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(database, "AsyncSessionLocal", broken)
    assert asyncio.run(recovery_results.record_send("reengage", conv)) is False


def test_a_job_records_only_a_message_that_was_sent(monkeypatch):
    """Stage 2: the cart PLANNER records nothing (it files a row); the
    dispatcher writes the recovery row after a successful send of that row,
    keyed by the planner and its reference — and none when the send fails."""
    from app.services import actions as act
    from app.services import recovery_results
    from tests._action_fakes import install
    from app.models.conversation import InterceptMode
    install(monkeypatch)
    recorded = []

    async def fake_record(job, conv, *, ref=None):
        recorded.append((job, ref))
        return True
    monkeypatch.setattr(recovery_results, "record_send", fake_record)

    now = datetime.now(timezone.utc)
    action = types.SimpleNamespace(id="a1", status="planned", due_at=now, kind="buying_follow_up",
                                   conversation_id="c1", deal_id=None, source="cart_recovery",
                                   dedupe_key="buying:c1", reason="They built a cart — Alb", draft=None)
    conv = types.SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700777009",
                                 external_id=None, intercept_mode=InterceptMode.ai, person_id=None)

    class _Rows:
        def scalars(self): return types.SimpleNamespace(all=lambda: [action])
        def scalar_one_or_none(self): return None
        def scalar(self): return None
    class _DB:
        async def execute(self, *a, **k): return _Rows()
        async def get(self, model, pk): return conv if model.__name__ == "Conversation" else None
        async def commit(self): pass
        async def rollback(self): pass

    async def fake_window(db, c): return True
    monkeypatch.setattr("app.services.hub_events._within_window", fake_window)
    monkeypatch.setattr("app.services.hub_events.is_quiet_hours", lambda now=None: False)
    async def no_gate(db, d, c, in_window): return None
    monkeypatch.setattr(act, "needs_approval", no_gate)
    monkeypatch.setattr(settings, "agent_initiative", True, raising=False)
    async def compose(db, redis, c, reason): return "Still keen on the alb?"
    monkeypatch.setattr(act, "_compose_follow_up", compose)
    async def not_repeat(db, c, t): return False
    monkeypatch.setattr(act, "_repeats_earlier", not_repeat)
    async def not_opted(db, redis, c, **kw): return False
    monkeypatch.setattr("app.services.intent.opted_out", not_opted)
    async def readable_no(db, redis, c): return "no"
    monkeypatch.setattr("app.services.intent.opt_out_state", readable_no)   # slice 5: the dispatcher reads the three-state form
    async def go(db, c, a, *, now): return "go", ""
    monkeypatch.setattr(act, "decide", go)

    async def ok_send(db, redis, c, text, action=None, **kw): pass
    monkeypatch.setattr(act, "_send", ok_send)
    assert asyncio.run(act.process_due(_DB(), None, now=now)) == 1
    assert recorded == [("cart_recovery", "c1")]

    action.status = "planned"
    async def bad_send(db, redis, c, text, action=None, **kw): raise RuntimeError("meta down")
    monkeypatch.setattr(act, "_send", bad_send)
    assert asyncio.run(act.process_due(_DB(), None, now=now)) == 0
    assert len(recorded) == 1 and action.status == "planned"
