"""OUTBOUND COMMUNICATION, STAGE 2 — on a real Postgres with the commitment
index in place: one open row per commitment whatever the path or the worker,
the planners filing rows the dispatcher sends, two independent orders in one
reminder, the contextual rules in shadow and in enforce. Skips without a
reachable Postgres."""
import asyncio
import importlib.util
import pathlib
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests.test_security_db import fresh_db, pytestmark  # noqa: F401
from app.core.config import settings

JUDAS, WILLY = "211985555188", "255754648158"


def run(coro):
    return asyncio.run(coro)


def _index_sql():
    path = next(pathlib.Path(__file__).resolve().parents[1].glob("alembic/versions/e8a1c3d5f7b9_*.py"))
    spec = importlib.util.spec_from_file_location("mig_e8a1_db", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.UNIQUE_INDEX_SQL


@pytest.fixture
def maker(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as database
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE agent_actions, deals, messages, order_events, intercepts, "
                          "conversations, persons, users, recovery_sends CASCADE"))
        c.execute(sa.text(_index_sql()))                 # what the migration creates on the box
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    mk = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                            class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", mk)
    # the planners bound app.database.AsyncSessionLocal at import time
    from app.jobs import cart_recovery, payment_followup
    monkeypatch.setattr(cart_recovery, "AsyncSessionLocal", mk)
    monkeypatch.setattr(payment_followup, "AsyncSessionLocal", mk)
    monkeypatch.setattr(settings, "agent_initiative", True, raising=False)
    monkeypatch.setattr("app.services.hub_events.is_quiet_hours", lambda now=None: False)
    return mk


class _Redis:
    def __init__(self):
        self.kv, self.hashes, self.published = {}, {}, []
    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True
    async def get(self, k): return self.kv.get(k)
    async def delete(self, k): self.kv.pop(k, None)
    async def exists(self, k): return 1 if k in self.kv else 0
    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]
    async def expire(self, k, s): pass
    async def hincrby(self, k, f, n):
        self.hashes.setdefault(k, {})[f] = self.hashes.get(k, {}).get(f, 0) + n
    async def publish(self, ch, msg):
        import json
        self.published.append((ch, json.loads(msg)))


def _seed(maker, wa, *, name):
    from app.models.conversation import Conversation, InterceptMode
    from app.models.person import Person
    from app.models.user import User

    async def go():
        async with maker() as db:
            p = Person(id=uuid.uuid4(), display_name=name)
            db.add(p)
            await db.flush()
            c = Conversation(id=uuid.uuid4(), wa_id=wa, channel="whatsapp", external_id=wa,
                             person_id=p.id, intercept_mode=InterceptMode.ai)
            db.add(c)
            db.add(User(wa_id=wa, name=name, person_id=p.id))
            await db.commit()
            return c.id
    return run(go())


def _msg(maker, conv_id, wa, direction, text, *, minutes_ago=0.0, sender=None, raw_meta=None):
    from app.models.message import Message, MsgDirection, MsgSender

    async def go():
        async with maker() as db:
            db.add(Message(id=uuid.uuid4(), conversation_id=conv_id, wa_id=wa, external_id=wa,
                           channel="whatsapp", direction=MsgDirection(direction),
                           sender=sender or (MsgSender.user if direction == "inbound" else MsgSender.ai),
                           text=text, raw_meta=raw_meta,
                           created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
            await db.commit()
    run(go())


def _rows(maker, conv_id):
    from sqlalchemy import select
    from app.models.agent_action import AgentAction

    async def go():
        async with maker() as db:
            return [(a.kind, a.status, a.dedupe_key, a.source, a.reason or "", a.draft) for a in (
                await db.execute(select(AgentAction).where(AgentAction.conversation_id == conv_id)
                                 .order_by(AgentAction.created_at))).scalars().all()]
    return run(go())


def _outbound(maker, conv_id):
    from sqlalchemy import select
    from app.models.message import Message, MsgDirection

    async def go():
        async with maker() as db:
            return [(m.text, m.raw_meta) for m in (await db.execute(
                select(Message).where(Message.conversation_id == conv_id,
                                      Message.direction == MsgDirection.outbound,
                                      Message.media_type.is_(None)).order_by(Message.created_at))).scalars().all()]
    return run(go())


def _wire(monkeypatch):
    sent = []

    async def _send_waba(to, text, **kw):
        sent.append((to, text))
        return f"wamid.{len(sent)}"
    monkeypatch.setattr("app.services.messaging._send_waba", _send_waba)
    return sent


def _tick(maker, redis):
    from app.services import actions

    async def go():
        async with maker() as db:
            return await actions.process_due(db, redis)
    return run(go())


# ── identity under the index ─────────────────────────────────────────────────

def test_plan_keeps_one_open_row_per_commitment_and_survives_a_race(maker):
    from app.services import actions
    cid = _seed(maker, JUDAS, name="Judas Othow")
    now = datetime.now(timezone.utc)

    async def plan(kind, reason, **kw):
        async with maker() as db:
            row, created = await actions.plan(db, conversation_id=cid, kind=kind, due_at=now,
                                              reason=reason, source="test", **kw)
            return str(row.id), created
    a, c1 = run(plan("check_in", "Customer-agreed check-in (WhatsApp): the quotation"))
    b, c2 = run(plan("check_in", "Customer-agreed check-in (WhatsApp): again, Thursday"))
    assert c1 is True and c2 is False and a == b                      # the same commitment
    s, c3 = run(plan("replenishment", "Supplies check-in (WhatsApp): divai"))
    assert c3 is True and s != a                                        # a different one
    assert [(k, st) for k, st, *_ in _rows(maker, cid)] == [("check_in", "planned"), ("replenishment", "planned")]

    # Another worker inserted the same commitment a moment ago, bypassing plan():
    # the index refuses a second open row and plan() lands on the existing one.
    async def raw_insert():
        from app.models.agent_action import AgentAction
        from sqlalchemy.exc import IntegrityError
        async with maker() as db:
            db.add(AgentAction(conversation_id=cid, kind="check_in", due_at=now, reason="dup",
                               dedupe_key="check_in:purchase_decision", source="other-worker"))
            try:
                await db.commit()
                return "accepted"
            except IntegrityError:
                await db.rollback()
                return "rejected"
    assert run(raw_insert()) == "rejected"
    same, created = run(plan("check_in", "Customer-agreed check-in (WhatsApp): once more"))
    assert created is False and same == a
    # a SENT row no longer blocks the next commitment of the same kind
    async def mark_sent():
        from sqlalchemy import update
        from app.models.agent_action import AgentAction
        async with maker() as db:
            await db.execute(update(AgentAction).where(AgentAction.id == uuid.UUID(a)).values(status="sent"))
            await db.commit()
    run(mark_sent())
    again, created = run(plan("check_in", "Customer-agreed check-in (WhatsApp): next month"))
    assert created is True and again != a


def test_a_quote_and_a_cart_are_one_buying_follow_up(maker, monkeypatch):
    """Judas was quoted $335 AND had the items in a cart: one nudge, not two."""
    from app.services import actions, deals
    from app.jobs import cart_recovery
    cid = _seed(maker, JUDAS, name="Judas Othow")
    _msg(maker, cid, JUDAS, "inbound", "How much for 2 trays and 50 cups?", minutes_ago=90)
    _msg(maker, cid, JUDAS, "outbound", "2 Aluminium Trays and 50 cups come to $335.", minutes_ago=89)

    async def quote_then_cart():
        async with maker() as db:
            from app.models.deal import Deal
            deal = Deal(conversation_id=cid, items_snapshot=[{"name": "Aluminium Tray", "qty": 2, "price": 70}])
            db.add(deal)
            await db.flush()
            await actions.plan(db, conversation_id=cid, kind="quote_follow_up", deal_id=deal.id,
                               due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                               reason="Quote follow-up: Neema quoted $335", source="scribe",
                               draft="Hi Judas 🙏 Just following up on the trays at $335. Shall I reserve them?")
            return deal.id
    deal_id = run(quote_then_cart())
    conv = types.SimpleNamespace(id=cid, channel="whatsapp", wa_id=JUDAS, person_id=None)
    row = {"conv": conv, "to": JUDAS, "items": [{"name": "Aluminium Tray", "qty": 2}], "owner": "o", "total": 335}
    res = run(cart_recovery._handle(_Redis(), row, send=True))
    assert res["sent"] is True and res.get("planned"), res
    rows = _rows(maker, cid)
    assert len(rows) == 1 and rows[0][2] == f"buying:{deal_id}"     # the cart refreshed the quote's row
    assert rows[0][0] == "buying_follow_up" and rows[0][3] == "cart_recovery"
    assert deals is not None


def test_two_independent_orders_get_one_reminder_naming_both(maker, monkeypatch):
    from app.jobs import payment_followup as pf
    from app.models.order_event import OrderEvent
    cid = _seed(maker, WILLY, name="Willy K. Ackyoo")
    _msg(maker, cid, WILLY, "inbound", "Order both please", minutes_ago=200)
    _msg(maker, cid, WILLY, "outbound", "Both orders placed — here are the links.", minutes_ago=199)

    async def orders():
        async with maker() as db:
            o1 = OrderEvent(id=f"{WILLY}_1", wa_id=WILLY, event_type="confirmed", hub_order_id=501,
                            hub_order_number="BH-501", hub_total=22000, hub_currency="KES",
                            hub_payment_url="https://pay.example/501", payment_status="unpaid",
                            created_at=datetime.now(timezone.utc) - timedelta(hours=3))
            o2 = OrderEvent(id=f"{WILLY}_2", wa_id=WILLY, event_type="confirmed", hub_order_id=502,
                            hub_order_number="BH-502", hub_total=2500, hub_currency="KES",
                            hub_payment_url="https://pay.example/502", payment_status="unpaid",
                            created_at=datetime.now(timezone.utc) - timedelta(hours=3))
            db.add_all([o1, o2])
            await db.commit()
            return o1, o2
    o1, o2 = run(orders())
    conv = types.SimpleNamespace(id=cid, channel="whatsapp", wa_id=WILLY, person_id=None)
    group = {"conv": conv, "to": WILLY, "orders": [o1, o2]}
    r = _Redis()
    res = run(pf._handle(r, group, send=True))
    assert res["sent"] is True and res["orders"] == 2, res
    rows = _rows(maker, cid)
    assert len(rows) == 1 and rows[0][0] == "payment_reminder" and rows[0][2] == "payment:501,502"
    assert "BH-501" in rows[0][5] and "BH-502" in rows[0][5] and "pay.example/502" in rows[0][5]
    # the dispatcher re-reads the hub and sends ONE message naming both
    async def unpaid(oid, redis=None): return {"payment_status": "unpaid"}
    monkeypatch.setattr("app.core.hub_client.fetch_order_status", unpaid)
    sent = _wire(monkeypatch)
    assert _tick(maker, r) == 1
    assert len(sent) == 1 and "BH-501" in sent[0][1] and "BH-502" in sent[0][1]
    assert _outbound(maker, cid)[-1][1]["reference"] == "payment:501,502"
    # the same two orders are never reminded again by the planner (its per-order guards)
    assert run(pf._handle(r, group, send=True))["skipped"] == "already reminded"
    # and once BOTH are paid the dispatcher withdraws a reminder instead of sending it
    async def paid(oid, redis=None): return {"payment_status": "paid"}
    monkeypatch.setattr("app.core.hub_client.fetch_order_status", paid)
    async def replan():
        from app.services import actions
        async with maker() as db:
            await actions.plan(db, conversation_id=cid, kind="payment_reminder",
                               due_at=datetime.now(timezone.utc), reason="again", source="payment_followup",
                               draft="reminder", reference="501,502")
    run(replan())
    assert _tick(maker, r) == 0 and len(sent) == 1
    assert _rows(maker, cid)[-1][1] == "vetoed" and "paid — nothing to remind" in _rows(maker, cid)[-1][4]


# ── the contextual rules, shadow and enforce ─────────────────────────────────

def test_a_customer_who_wrote_after_planning_is_not_nudged_in_enforce_and_is_flagged_in_shadow(maker, monkeypatch):
    """Willy: a cart nudge was planned, then he wrote ("I'll compare in
    Arusha"). Enforce withdraws the nudge; shadow sends it but records what
    enforce would have done, so the comparison week can be read. (A QUOTE
    nudge in the same spot is withdrawn in every mode by its own stale rule —
    quote_followup.stale_reason — which Stage 1 already enforced.)"""
    from app.services import actions
    cid = _seed(maker, WILLY, name="Willy K. Ackyoo")
    _msg(maker, cid, WILLY, "inbound", "Bei ya tray?", minutes_ago=120)
    _msg(maker, cid, WILLY, "outbound", "Golden Communion Tray ni $220.", minutes_ago=119)

    async def plan():
        async with maker() as db:
            row, _ = await actions.plan(db, conversation_id=cid, kind="buying_follow_up",
                                        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                                        reason="They built a cart — Golden Communion Tray", source="cart_recovery")
            # planned two hours ago, before his message
            from sqlalchemy import update
            from app.models.agent_action import AgentAction
            await db.execute(update(AgentAction).where(AgentAction.id == row.id)
                             .values(created_at=datetime.now(timezone.utc) - timedelta(minutes=118)))
            await db.commit()
    run(plan())
    _msg(maker, cid, WILLY, "inbound", "Ninataka kufuatilia wanaouza hapa Arusha. Nitakuambia nikishapata majibu", minutes_ago=60)
    _msg(maker, cid, WILLY, "outbound", "Sawa, Rev. Dr. Ackyoo — tutakungoja.", minutes_ago=59)
    sent = _wire(monkeypatch)
    r = _Redis()

    async def compose(db, redis, c, reason): return "Habari Willy, Golden Communion Tray bado ipo — nikuwekee?"
    monkeypatch.setattr(actions, "_compose_follow_up", compose)
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)
    assert _tick(maker, r) == 1
    text, meta = _outbound(maker, cid)[-1]
    assert text.startswith("Habari") and meta["shadow"] == ["suppress: the customer wrote after this was planned — the live reply answered them"]
    assert r.hashes[next(iter(r.hashes))] == {"suppress": 1}

    # enforce: the same situation ends in silence
    async def plan_again():
        async with maker() as db:
            row, _ = await actions.plan(db, conversation_id=cid, kind="buying_follow_up",
                                        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                                        reason="They built a cart — Golden Communion Tray (again)", source="cart_recovery")
            from sqlalchemy import update
            from app.models.agent_action import AgentAction
            await db.execute(update(AgentAction).where(AgentAction.id == row.id)
                             .values(created_at=datetime.now(timezone.utc) - timedelta(minutes=118)))
            await db.commit()
    run(plan_again())
    monkeypatch.setattr(settings, "outreach_mode", "enforce", raising=False)
    assert _tick(maker, r) == 0 and len(sent) == 1
    assert _rows(maker, cid)[-1][1] == "vetoed" and "customer wrote after this was planned" in _rows(maker, cid)[-1][4]


def test_one_unprompted_sales_message_a_day_while_a_promise_still_goes(maker, monkeypatch):
    from app.services import actions
    from app.services import outreach_log as ol
    cid = _seed(maker, JUDAS, name="Judas Othow")
    _msg(maker, cid, JUDAS, "inbound", "Thinking about it", minutes_ago=300)
    # a routine nudge already went out today (stamped)
    _msg(maker, cid, JUDAS, "outbound", "Judas, your trays are still saved — shall we go ahead?", minutes_ago=10,
         raw_meta=ol.stamp("actions", ol.ROUTINE, kind="buying_follow_up"))

    async def plan():
        async with maker() as db:
            await actions.plan(db, conversation_id=cid, kind="quote_follow_up",
                               due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                               reason="Quote follow-up", source="scribe", draft="Shall I reserve them?")
            await actions.plan(db, conversation_id=cid, kind="check_in",
                               due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                               reason="Customer-agreed check-in (WhatsApp): Thursday as agreed", source="tool")
    run(plan())
    sent = _wire(monkeypatch)

    async def compose(db, redis, c, reason): return "Judas, as agreed on Thursday: shall your friend collect, or DHL to Juba?"
    monkeypatch.setattr(actions, "_compose_follow_up", compose)
    async def window(db, c): return True
    monkeypatch.setattr("app.services.hub_events._within_window", window)
    monkeypatch.setattr(settings, "outreach_mode", "enforce", raising=False)
    now = datetime.now(timezone.utc)
    assert _tick(maker, _Redis()) == 1
    assert [t for _, t in sent] == ["Judas, as agreed on Thursday: shall your friend collect, or DHL to Juba?"]
    rows = {k: (st, reason) for k, st, _, _, reason, _ in _rows(maker, cid)}
    assert rows["check_in"][0] == "sent"                          # the kept promise went first
    # the sales nudge is folded into the day's one message, not queued for tomorrow
    assert rows["quote_follow_up"][0] == "vetoed" and "merged" in rows["quote_follow_up"][1]
    assert now is not None
