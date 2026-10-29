"""Owner, 2026-10-29: "build it" — every follow-up a daily sweep sends is
recorded, and the Reports page reads what each customer did next: wrote back
within 72 hours, then ordered within 7 days (payment reminder: the order was
paid). Sends younger than 72 hours are "waiting" and kept out of the rates.

Skips cleanly without a database (the Docker harness / CI migrations job has one).
"""
import asyncio
import types
import uuid

import pytest
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
    """The cart sweep writes its row after a successful send, keyed by the
    cart's fingerprint — and none when the send fails."""
    from app.jobs import cart_recovery as cr
    from app.services import n8n_bridge as svc
    from app.services import recovery_results
    recorded = []

    async def fake_record(job, conv, *, ref=None):
        recorded.append((job, ref))
        return True

    async def fake_draft(redis, conv, to, items):
        return "Still keen on the alb?"

    async def ok_send(to, text):
        return "wamid.1"

    async def bad_send(to, text):
        raise RuntimeError("meta down")

    async def noop(*a, **k):
        return None

    class _Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(recovery_results, "record_send", fake_record)
    monkeypatch.setattr(cr, "_draft", fake_draft)
    monkeypatch.setattr(cr, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(svc, "save_outbound_message", noop)
    items = [{"name": "Alb", "qty": 1}]
    row = {"conv": types.SimpleNamespace(id=uuid.uuid4(), channel="whatsapp", person_id=None),
           "to": "254700777009", "items": items, "total": 100.0, "owner": "Person:x"}

    monkeypatch.setattr(svc, "_send_waba", ok_send)
    res = asyncio.run(cr._handle(None, row, send=True))
    assert res["sent"] is True
    assert recorded == [("cart_recovery", cr.cart_fingerprint(items))]

    monkeypatch.setattr(svc, "_send_waba", bad_send)
    res = asyncio.run(cr._handle(None, row, send=True))
    assert res["sent"] is False and res["error"]
    assert len(recorded) == 1
