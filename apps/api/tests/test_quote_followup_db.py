"""Quote → follow-up (services/quote_followup.py), on a real Postgres.

30 days of evidence: 1,582 conversations went quiet right after Neema quoted
a price and 8% ever heard from her again — the scribe planned nothing for an
unanswered quote. Now: a reply that priced a stock item (from the turn's own
catalogue results) plans ONE follow-up inside the 24 h window, cancelled when
the customer speaks, never for a human-held thread, never after an order,
its text composed from the quote's own figures with one question. And every
needs_approval row now says WHY it waits.
"""
import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests.test_security_db import fresh_db, pytestmark  # noqa: F401

WA = "254711000001"
NBO = timedelta(hours=3)

TOOLS = [{"tool": "search_catalog", "input": {"query": "aluminium tray"}, "out": {
    "count": 3, "currency": "KES", "results": [
        {"name": "Aluminium Tray", "made_to_order": False, "price": 7000,
         "currency": "KES", "availability": "available"},
        {"name": "Brass Chalice", "made_to_order": False, "price": 4500, "currency": "KES"},
        {"name": "Red Cassock", "made_to_order": True, "price": 9000, "currency": "KES"},
    ]}}]
REPLY = "The Aluminium Tray is KES 7,000 — it holds 40 cups. Would you like one?"
ASK = "How much is the aluminium tray?"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def maker(fresh_db):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE agent_actions, deals, messages, order_events, "
                          "intercepts, conversations, persons CASCADE"))
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    return async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                              class_=AsyncSession, expire_on_commit=False)


def _seed(maker, *, mode="ai", name="Grace Wanjiru"):
    from app.models.conversation import Conversation, InterceptMode
    from app.models.person import Person

    async def go():
        async with maker() as db:
            p = Person(id=uuid.uuid4(), display_name=name)
            db.add(p)
            await db.flush()
            c = Conversation(id=uuid.uuid4(), wa_id=WA, channel="whatsapp", external_id=WA,
                             person_id=p.id, intercept_mode=InterceptMode(mode))
            db.add(c)
            await db.commit()
            return c.id
    conv_id = run(go())
    _msg(maker, conv_id, "inbound", ASK, minutes_ago=2)
    _msg(maker, conv_id, "outbound", REPLY, minutes_ago=1)
    return conv_id


def _msg(maker, conv_id, direction, text, minutes_ago=0.0):
    from app.models.message import Message, MsgDirection, MsgSender

    async def go():
        async with maker() as db:
            db.add(Message(id=uuid.uuid4(), conversation_id=conv_id, wa_id=WA, external_id=WA,
                           channel="whatsapp", direction=MsgDirection(direction),
                           sender=MsgSender.user if direction == "inbound" else MsgSender.ai,
                           text=text,
                           created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
            await db.commit()
    run(go())


def _scribe(maker, reply=REPLY, inbound=ASK, tools=TOOLS):
    from app.services.deals import scribe_update

    async def go():
        async with maker() as db:
            await scribe_update(db, WA, "whatsapp", reply, inbound_text=inbound, tools=tools)
    run(go())


def _actions(maker, statuses=("planned", "needs_approval")):
    from sqlalchemy import select
    from app.models.agent_action import AgentAction

    async def go():
        async with maker() as db:
            return (await db.execute(select(AgentAction).where(
                AgentAction.status.in_(statuses)).order_by(AgentAction.created_at))).scalars().all()
    return run(go())


def _pending(maker):
    return _actions(maker)


# ── Planning ──────────────────────────────────────────────────────────────────

def test_quote_then_silence_plans_one_follow_up_inside_the_window(maker):
    from app.services.hub_events import is_quiet_hours
    _seed(maker)
    now = datetime.now(timezone.utc)
    _scribe(maker)
    rows = _pending(maker)
    assert len(rows) == 1
    a = rows[0]
    assert a.kind == "quote_follow_up" and a.status == "planned" and a.deal_id
    assert now + timedelta(hours=3, minutes=59) <= a.due_at <= now + timedelta(hours=23)
    assert not is_quiet_hours(a.due_at)
    assert "Aluminium Tray KES 7,000" in a.reason
    assert a.draft == ("Hi Grace 🙏 Just following up on the Aluminium Tray at KES 7,000 "
                       "I shared earlier. Shall I reserve it for you?")


def test_customer_reply_cancels_it_at_scribe_time(maker):
    conv = _seed(maker)
    _scribe(maker)
    assert len(_pending(maker)) == 1
    _msg(maker, conv, "inbound", "Thanks, let me think")
    _scribe(maker, reply="Of course — take your time.", inbound="Thanks, let me think", tools=[])
    assert _pending(maker) == []
    vetoed = _actions(maker, ("vetoed",))
    assert len(vetoed) == 1 and "[customer replied]" in vetoed[0].reason


def test_second_quote_on_the_same_deal_is_still_one_pending(maker):
    conv = _seed(maker)
    _scribe(maker)
    _msg(maker, conv, "inbound", "and the brass chalice?")
    _scribe(maker, reply="The Brass Chalice is KES 4,500.", inbound="and the brass chalice?")
    rows = _pending(maker)
    assert len(rows) == 1
    assert "Brass Chalice at KES 4,500" in rows[0].draft
    # a third quote with no new customer message (a deferred turn) — still one
    _scribe(maker, reply="The Brass Chalice is KES 4,500.", inbound="")
    assert len(_pending(maker)) == 1


def test_human_mode_thread_plans_nothing(maker):
    _seed(maker, mode="human")
    _scribe(maker)
    assert _pending(maker) == []


def test_an_order_placed_plans_nothing(maker):
    from app.models.order_event import OrderEvent
    _seed(maker)

    # an order placed in this very turn
    ordered = TOOLS + [{"tool": "create_order", "input": {}, "out": {"order_number": "BH-1"}}]
    _scribe(maker, tools=ordered)
    assert _pending(maker) == []

    # an order already placed today
    async def order():
        async with maker() as db:
            db.add(OrderEvent(id=f"{WA}_1", wa_id=WA, event_type="confirmed",
                              created_at=datetime.now(timezone.utc) - timedelta(hours=1)))
            await db.commit()
    run(order())
    _scribe(maker)
    assert _pending(maker) == []


def test_a_promise_follow_up_is_never_overridden_by_a_quote(maker):
    _seed(maker)
    _scribe(maker, reply="The Aluminium Tray is KES 7,000. Let me confirm the colour for you.")
    rows = _pending(maker)
    assert len(rows) == 1 and rows[0].kind == "follow_up"
    _scribe(maker, inbound="")                        # a later bare quote
    rows = _pending(maker)
    assert len(rows) == 1 and rows[0].kind == "follow_up"


# ── Sending ───────────────────────────────────────────────────────────────────

def _due_now(maker):
    from sqlalchemy import update
    from app.models.agent_action import AgentAction

    async def go():
        async with maker() as db:
            await db.execute(update(AgentAction).values(
                due_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await db.commit()
    run(go())


def _process(maker, monkeypatch, initiative=True):
    from app.core.config import settings
    from app.services import actions as act
    from app.services import hub_events
    monkeypatch.setattr(hub_events, "is_quiet_hours", lambda *a, **k: False)
    monkeypatch.setattr(settings, "agent_initiative", initiative)
    sent = []

    async def fake_send(db, redis, conv, text):
        sent.append(text)

    async def no_llm(*a, **k):
        raise AssertionError("a quote follow-up must not be re-composed by the model")
    monkeypatch.setattr(act, "_send", fake_send)
    monkeypatch.setattr(act, "_compose_follow_up", no_llm)

    async def go():
        async with maker() as db:
            return await act.process_due(db, None)
    return run(go()), sent


def test_silence_until_due_sends_exactly_the_composed_text(maker, monkeypatch):
    _seed(maker)
    _scribe(maker)
    draft = _pending(maker)[0].draft
    _due_now(maker)
    n, sent = _process(maker, monkeypatch)
    assert n == 1 and sent == [draft]
    assert _actions(maker, ("sent",))[0].draft == draft


def test_a_reply_after_planning_withdraws_it_at_send_time(maker, monkeypatch):
    conv = _seed(maker)
    _scribe(maker)
    _msg(maker, conv, "inbound", "ok noted")     # no scribe ran for this message
    _due_now(maker)
    n, sent = _process(maker, monkeypatch)
    assert n == 0 and sent == []
    v = _actions(maker, ("vetoed",))
    assert len(v) == 1 and "[customer replied]" in v[0].reason


def test_a_thread_taken_by_a_human_withdraws_it_at_send_time(maker, monkeypatch):
    from sqlalchemy import update
    from app.models.conversation import Conversation, InterceptMode
    _seed(maker)
    _scribe(maker)

    async def take():
        async with maker() as db:
            await db.execute(update(Conversation).values(intercept_mode=InterceptMode.human))
            await db.commit()
    run(take())
    _due_now(maker)
    n, sent = _process(maker, monkeypatch)
    assert n == 0 and sent == []
    assert "[thread is not in AI mode]" in _actions(maker, ("vetoed",))[0].reason


# ── needs_approval says why ───────────────────────────────────────────────────

def test_needs_approval_stores_the_reason_and_the_api_returns_it(maker, monkeypatch, fresh_db):  # noqa: F811
    from sqlalchemy import update
    from app.models.deal import Deal
    _seed(maker)
    _scribe(maker)

    async def big():
        async with maker() as db:
            await db.execute(update(Deal).values(items_snapshot=[
                {"name": "Aluminium Tray", "qty": 10, "price": 7000}]))
            await db.commit()
    run(big())
    _due_now(maker)
    n, sent = _process(maker, monkeypatch)
    assert n == 0 and sent == []
    held = _actions(maker, ("needs_approval",))
    assert len(held) == 1
    assert held[0].reason.endswith("[needs approval: deal total above KES 50,000]")
    assert held[0].draft.startswith("Hi Grace")             # the quote's text, kept

    from app.services.actions import hold_reason, with_hold_reason
    assert hold_reason(held[0].reason) == "deal total above KES 50,000"
    # re-held → one marker, the newest
    again = with_hold_reason(held[0].reason, "conversation is human-held")
    assert again.count("[needs approval:") == 1 and hold_reason(again) == "conversation is human-held"


def test_needs_approval_reason_is_listed_for_staff(maker, monkeypatch, fresh_db):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers import crm
    from app.core.security import create_access_token, hash_password
    aid = str(uuid.uuid4())
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE agents CASCADE"))
        c.execute(sa.text(
            "INSERT INTO agents (id, name, email, password_hash, role, is_available, "
            "is_superuser, active_convs, created_at) VALUES "
            "(:id, 'Ben', 'ben@x.ke', :pw, 'agent', TRUE, FALSE, 0, NOW())"),
            {"id": aid, "pw": hash_password("whatever-pass")})
        c.execute(sa.text(
            "INSERT INTO agent_actions (id, due_at, kind, reason, status, created_by) VALUES "
            "(:id, NOW(), 'replenishment', 'check in [needs approval: outside the 24h "
            "messaging window]', 'needs_approval', 'ai')"), {"id": str(uuid.uuid4())})
    eng.dispose()

    async def _db():
        async with maker() as s:
            yield s
    app = FastAPI()
    app.include_router(crm.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as cl:
        r = cl.get("/api/admin/actions", headers={"Authorization": f"Bearer {create_access_token(aid)}"})
    assert r.status_code == 200
    row = r.json()["actions"][0]
    assert row["approval_reason"] == "outside the 24h messaging window"


# ── The words and the clock (pure) ────────────────────────────────────────────

def _figures(text):
    return {float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def test_the_text_uses_only_quoted_figures_and_asks_one_question():
    from app.services import quote_followup as qf
    quote = qf.extract_quote(TOOLS, "The Aluminium Tray is KES 7,000 and the Brass Chalice "
                                    "KES 4,500. The cassock is made to order.")
    assert quote == [{"name": "Aluminium Tray", "price": 7000, "currency": "KES"},
                     {"name": "Brass Chalice", "price": 4500, "currency": "KES"}]
    en = qf.compose(quote, name="Grace")
    assert en == ("Hi Grace 🙏 Just following up on the Aluminium Tray at KES 7,000 and the "
                  "Brass Chalice at KES 4,500 I shared earlier. Shall I reserve them for you?")
    assert _figures(en) <= {7000.0, 4500.0}
    assert en.count("?") == 1 and en.endswith("?")

    sw = qf.compose(quote[:1], name="Juma", swahili=True)
    assert sw == ("Habari Juma 🙏 Nafuatilia tu bei niliyokutajia: Aluminium Tray kwa KES 7,000. "
                  "Nikuwekee?\n(Just following up on the Aluminium Tray at KES 7,000 — shall I "
                  "reserve it for you?)")
    for line in sw.split("\n"):
        assert line.count("?") == 1
    assert _figures(sw) <= {7000.0}


def test_dollars_stay_dollars_and_nothing_unquoted_is_picked_up():
    from app.services import quote_followup as qf
    usd = [{"tool": "search_catalog", "out": {"currency": "USD", "results": [
        {"name": "Clergy Collar", "made_to_order": False, "price": 4.5, "currency": "USD",
         "variants": [{"label": "8 inch", "price": 3.5}, {"label": "10 inch", "price": 4}]},
        {"name": "Silver Tray", "made_to_order": False, "price": 70, "currency": "USD",
         "match": "partial"}]}}]
    q = qf.extract_quote(usd, "The 8-inch collar is $3.50. Silver tray $70?")
    assert q == [{"name": "Clergy Collar (8 inch)", "price": 3.5, "currency": "USD"}]
    assert "$3.50" in qf.compose(q)
    # a bare number is not a price; a figure no tool returned is never used
    assert qf.extract_quote(TOOLS, "We have 7000 in stock, and the tray is KES 6,500") == []
    assert qf.extract_quote(None, REPLY) == [] and qf.extract_quote(TOOLS, "") == []


def test_due_time_respects_quiet_hours_and_the_window():
    from app.services import quote_followup as qf

    def nbo(day, h):
        return datetime(2026, 10, day, h, 0, tzinfo=timezone.utc) - NBO
    # 14:00 Nairobi quote → 18:00 the same day
    assert qf.plan_due(nbo(12, 14), nbo(12, 14)) == nbo(12, 18)
    # 18:00 quote → 22:00 is quiet → 08:00 next morning (still inside 24 h)
    assert qf.plan_due(nbo(12, 18), nbo(12, 18)) == nbo(13, 8)
    # the customer last wrote 20 h ago → 4 h on is past the window's last hour
    assert qf.plan_due(nbo(12, 14) - timedelta(hours=20), nbo(12, 14)) is None
    assert qf.plan_due(None, nbo(12, 14)) is None
