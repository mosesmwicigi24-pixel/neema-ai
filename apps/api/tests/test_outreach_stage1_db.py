"""OUTBOUND COMMUNICATION, STAGE 1 — the screenshot cases replayed on a real
Postgres through the real code paths (audit, 2026-11-05). Each test checks
what the CUSTOMER would see — which texts went out, in what words — not just
what a function returned. Skips without a reachable Postgres."""
import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests.test_security_db import fresh_db, pytestmark  # noqa: F401
from app.core.config import settings

JUDAS, WILLY, PASTOR = "211985555188", "255754648158", "919098346693"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def maker(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as database
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE agent_actions, deals, messages, order_events, intercepts, "
                          "conversations, persons, users CASCADE"))
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    mk = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                            class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", mk)
    monkeypatch.setattr(settings, "agent_initiative", True, raising=False)
    monkeypatch.setattr("app.services.hub_events.is_quiet_hours", lambda now=None: False)
    return mk


class _Redis:
    def __init__(self):
        self.kv, self.published = {}, []
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
    async def publish(self, ch, msg):
        import json
        self.published.append((ch, json.loads(msg)))


def _seed(maker, wa, *, name, mode="ai"):
    from app.models.conversation import Conversation, InterceptMode
    from app.models.person import Person
    from app.models.user import User

    async def go():
        async with maker() as db:
            p = Person(id=uuid.uuid4(), display_name=name)
            db.add(p)
            await db.flush()
            c = Conversation(id=uuid.uuid4(), wa_id=wa, channel="whatsapp", external_id=wa,
                             person_id=p.id, intercept_mode=InterceptMode(mode))
            db.add(c)
            db.add(User(wa_id=wa, name=name, person_id=p.id))
            await db.commit()
            return c.id
    return run(go())


def _msg(maker, conv_id, wa, direction, text, *, minutes_ago=0.0, sender=None, wamid=None):
    from app.models.message import Message, MsgDirection, MsgSender
    mid = uuid.uuid4()

    async def go():
        async with maker() as db:
            db.add(Message(id=mid, conversation_id=conv_id, wa_id=wa, external_id=wa,
                           channel="whatsapp", direction=MsgDirection(direction),
                           sender=sender or (MsgSender.user if direction == "inbound" else MsgSender.ai),
                           text=text, waba_msg_id=wamid,
                           created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
            await db.commit()
    run(go())
    return mid


def _plan(maker, conv_id, kind, reason, *, minutes_ago=5, deal_id=None, draft=None):
    from app.models.agent_action import AgentAction
    aid = uuid.uuid4()

    async def go():
        async with maker() as db:
            db.add(AgentAction(id=aid, conversation_id=conv_id, deal_id=deal_id, kind=kind,
                               reason=reason, draft=draft,
                               due_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
            await db.commit()
    run(go())
    return aid


def _actions(maker, conv_id):
    from sqlalchemy import select
    from app.models.agent_action import AgentAction

    async def go():
        async with maker() as db:
            return [(a.kind, a.status, a.reason or "", a.draft) for a in (await db.execute(
                select(AgentAction).where(AgentAction.conversation_id == conv_id)
                .order_by(AgentAction.created_at))).scalars().all()]
    return run(go())


def _outbound(maker, conv_id):
    from sqlalchemy import select
    from app.models.message import Message, MsgDirection

    async def go():
        async with maker() as db:
            return [(m.text, m.raw_meta, m.waba_msg_id) for m in (await db.execute(
                select(Message).where(Message.conversation_id == conv_id,
                                      Message.direction == MsgDirection.outbound,
                                      Message.media_type.is_(None))
                .order_by(Message.created_at))).scalars().all()]
    return run(go())


def _wire_sends(monkeypatch):
    sent, templates = [], []

    async def _send_waba(to, text, **kw):
        sent.append((to, text))
        return f"wamid.{len(sent)}"
    async def _tpl(to, name, lang, params):
        templates.append((to, name, lang, list(params)))
        return {"messages": [{"id": f"wamid.t{len(templates)}"}]}
    monkeypatch.setattr("app.services.messaging._send_waba", _send_waba)
    monkeypatch.setattr("app.services.messaging.send_wa_template", _tpl)
    return sent, templates


def _tool_ctx(db, wa):
    from app.agent.tools import ToolContext
    return ToolContext(db=db, redis=None, wa_id=wa)


# ── Judas ────────────────────────────────────────────────────────────────────

def test_judas_thursday_promise_is_one_row_and_never_the_replenishment_template(maker, monkeypatch):
    """Two turns both call schedule_check_in(on_day=thursday) about the $335
    quotation → ONE row. Thursday evening the window is closed: with no
    approved follow-up template the row waits for a person and the customer
    receives NOTHING (not "about time for the next round of supplies?");
    with the follow-up template approved he receives its enquiry text once."""
    from app.agent import tools
    from app.services import actions
    cid = _seed(maker, JUDAS, name="Judas Othow")
    _msg(maker, cid, JUDAS, "inbound", "Thank you very much.", minutes_ago=2 * 24 * 60)
    _msg(maker, cid, JUDAS, "outbound", "You're welcome, Judas. I'll check in with you on Thursday.",
         minutes_ago=2 * 24 * 60 - 1)

    async def book(reason):
        async with maker() as db:
            return await tools._schedule_check_in(
                {"on_day": "thursday", "reason": reason}, _tool_ctx(db, JUDAS))
    first = run(book("the $335 quotation — collect in Nairobi or DHL to Juba"))
    second = run(book("check in on the quotation as agreed"))
    assert first["already_booked"] is False and second["already_booked"] is True
    rows = _actions(maker, cid)
    assert len(rows) == 1 and rows[0][0] == "check_in"

    # Thursday 18:00 arrives: make the row due, window closed (last inbound 2 days ago).
    async def make_due():
        from sqlalchemy import update
        from app.models.agent_action import AgentAction
        async with maker() as db:
            await db.execute(update(AgentAction).values(due_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await db.commit()
    run(make_due())
    sent, templates = _wire_sends(monkeypatch)
    monkeypatch.setattr(settings, "wa_event_template", "orderupdate_category", raising=False)
    monkeypatch.setattr(settings, "wa_followup_template", "", raising=False)

    async def tick():
        async with maker() as db:
            return await actions.process_due(db, _Redis())
    assert run(tick()) == 0
    assert sent == [] and templates == []                      # the customer got nothing wrong
    kind, status, reason, _ = _actions(maker, cid)[0]
    assert status == "needs_approval" and "no approved template for purpose 'check_in'" in reason

    # The owner approves a follow-up template: the SAME row goes out once, as that template.
    monkeypatch.setattr(settings, "wa_followup_template", "bh_enquiry_followup", raising=False)
    async def approve_again():
        from sqlalchemy import update
        from app.models.agent_action import AgentAction
        async with maker() as db:
            await db.execute(update(AgentAction).values(status="planned"))
            await db.commit()
    run(approve_again())
    assert run(tick()) == 1
    assert templates == [(JUDAS, "bh_enquiry_followup", settings.wa_invite_lang, ["Judas"])]
    out = _outbound(maker, cid)[-1]
    assert out[0] == "Hello Judas, this is Bethany House following up on your enquiry. Reply to this message and we'll pick up right where we left off."
    assert out[1]["kind"] == "outreach" and out[1]["template"]["template"] == "bh_enquiry_followup"
    assert out[2] == "wamid.t1"
    assert "replenishment" not in str(templates) and "supplies" not in str(templates)


def test_judas_wednesday_three_due_rows_become_one_message_without_a_greeting(maker, monkeypatch):
    """Three rows due the same morning, inside the window → one message, and
    the model's 'Good morning, Judas.' opener is dropped because we spoke
    within the day."""
    from app.services import actions
    cid = _seed(maker, JUDAS, name="Judas Othow")
    _msg(maker, cid, JUDAS, "inbound", "Thank you very much.", minutes_ago=60)
    _msg(maker, cid, JUDAS, "outbound", "You're welcome, Judas.", minutes_ago=59)
    _plan(maker, cid, "customer_promise", "Customer said they'd respond (tomorrow)", minutes_ago=9)
    _plan(maker, cid, "check_in", "Customer-agreed check-in (WhatsApp): the quotation", minutes_ago=8)
    _plan(maker, cid, "follow_up", "Neema promised: confirm DHL to Juba", minutes_ago=7)
    sent, _ = _wire_sends(monkeypatch)

    async def fake_turn(db, redis, wa_id, user_text, llm, **kw):
        return "Good morning, Judas. There's no rush on our side — your quotation of $335 stands until 17 November."
    monkeypatch.setattr("app.agent.runtime.run_turn", fake_turn)

    async def tick():
        async with maker() as db:
            return await actions.process_due(db, _Redis())
    assert run(tick()) == 1
    assert sent == [(JUDAS, "Judas, there's no rush on our side — your quotation of $335 stands until 17 November.")]
    statuses = {k: (s, r) for k, s, r, _ in _actions(maker, cid)}
    assert statuses["customer_promise"][0] == "sent"
    assert statuses["check_in"][0] == "vetoed" and "merged" in statuses["check_in"][1]
    assert statuses["follow_up"][0] == "vetoed" and "merged" in statuses["follow_up"][1]
    # and the next tick sends nothing more
    assert run(tick()) == 0 and len(sent) == 1
    assert _outbound(maker, cid)[-1][1]["source"] == "actions"


# ── Pastor Emmanuel ──────────────────────────────────────────────────────────

def test_pastor_emmanuel_open_availability_check_holds_every_sales_follow_up(maker, monkeypatch):
    """check_availability on the gold embroidery records a team check on the
    deal; a due quote nudge is withdrawn and a due promise waits for a person;
    when a colleague answers, the check closes and routine nudges are gone."""
    from app.agent import tools
    from app.services import actions, deals
    cid = _seed(maker, PASTOR, name="PASTOR : SURDAS Emmanuel")
    _msg(maker, cid, PASTOR, "inbound", "Bishop's purple vestment set with gold embroidery?", minutes_ago=30)

    async def empty_catalog(db, redis): return []
    monkeypatch.setattr("app.services.messaging.catalog_items", empty_catalog)
    async def ask():
        async with maker() as db:
            return await tools._check_availability({"item": "gold embroidery on the purple cope"},
                                                   _tool_ctx(db, PASTOR))
    out = run(ask())
    assert out["team_check_open"] is True and "do NOT ask them to start" in out["note"]

    async def open_item():
        async with maker() as db:
            d = await deals.open_deal_for(db, conversation_id=cid)
            return deals.team_check_open(d), d.id
    item, deal_id = run(open_item())
    assert item == "gold embroidery on the purple cope"

    _plan(maker, cid, "quote_follow_up", "Quote follow-up: Neema quoted Cope $450", deal_id=deal_id,
          draft="Hi 🙏 Just following up on the Cope at $450. Shall I reserve it?")
    _plan(maker, cid, "follow_up", "Neema promised: confirm the embroidery", deal_id=deal_id)
    sent, templates = _wire_sends(monkeypatch)

    async def tick():
        async with maker() as db:
            return await actions.process_due(db, _Redis())
    assert run(tick()) == 0 and sent == [] and templates == []
    rows = {k: (s, r) for k, s, r, _ in _actions(maker, cid)}
    assert rows["quote_follow_up"][0] == "vetoed" and "team check open" in rows["quote_follow_up"][1]
    assert rows["follow_up"][0] == "needs_approval" and "team still confirming" in rows["follow_up"][1]

    # The workshop answers through a colleague: the check closes, nudges are withdrawn.
    async def colleague_answered():
        async with maker() as db:
            closed = await deals.clear_team_check(db, cid, by="agent:test")
            n = await actions.withdraw_routine(db, cid, why="team answer delivered")
            d = await deals.open_deal_for(db, conversation_id=cid)
            return closed, n, deals.team_check_open(d)
    closed, n, still = run(colleague_answered())
    assert closed is True and still is None and n == 1          # the parked promise row withdrawn
    assert all(s in ("vetoed",) for _, s, _, _ in _actions(maker, cid))


# ── overlapping inbound messages ─────────────────────────────────────────────

def test_second_message_during_a_turn_is_seen_once_and_flagged(maker):
    """Willy, 22:20: msg₁, then msg₂ while reply₁ composes (Meta-timestamped
    before reply₁). The turn answering msg₂ sees it ONCE, after reply₁, with
    the overlap note — never twice."""
    from app.agent import runtime
    cid = _seed(maker, WILLY, name="Willy K. Ackyoo")
    _msg(maker, cid, WILLY, "inbound", "Naomba kujua bei kwa Ksh.", minutes_ago=3)
    m2 = _msg(maker, cid, WILLY, "inbound", "Naomba kujua bei kwa Ksh.", minutes_ago=2)
    _msg(maker, cid, WILLY, "outbound", "Bei zetu kwako ni kwa USD: Golden Communion Tray $220.", minutes_ago=1)
    seen = {}

    class _LLM:
        _model = settings.tier2_model
        purpose = "whatsapp"
        async def complete(self, *, system, messages, tools, **kw):
            seen.setdefault("messages", list(messages))     # the FIRST call's transcript
            return types.SimpleNamespace(text="Sawa.", tool_calls=[], assistant_content=[], usage={})

    async def go():
        async with maker() as db:
            return await runtime.run_turn(db, None, WILLY, "Naomba kujua bei kwa Ksh.", _LLM(),
                                          inbound_ids=[str(m2)])
    run(go())
    msgs = seen["messages"]
    texts = [str(m["content"]) for m in msgs]
    assert sum("Naomba kujua bei kwa Ksh" in t for t in texts) == 2       # msg₁ in history + the live msg₂
    assert msgs[-1]["role"] == "user" and "Naomba kujua bei kwa Ksh." in str(msgs[-1]["content"])
    assert "arrived WHILE your previous reply was being written" in str(msgs[-1]["content"])
    assert msgs[-2]["role"] == "assistant" and "$220" in msgs[-2]["content"]


# ── opt-out ──────────────────────────────────────────────────────────────────

def test_opt_out_is_acknowledged_once_recorded_for_good_and_ends_outreach(maker, monkeypatch):
    from app.agent import runtime
    from app.services import actions, intent
    from app.jobs import cart_recovery
    cid = _seed(maker, WILLY, name="Willy K. Ackyoo")
    _msg(maker, cid, WILLY, "inbound", "Acha kunitumia ujumbe tafadhali", minutes_ago=1)
    _plan(maker, cid, "quote_follow_up", "Quote follow-up: tray $220", draft="Nikuwekee?")
    sent, _ = _wire_sends(monkeypatch)
    r = _Redis()
    assert run(runtime.schedule_reply(r, WILLY, "Acha kunitumia ujumbe tafadhali", "d1")) is True
    assert sent == [(WILLY, "Sawa, tumeelewa — hatutakutumia ujumbe tena. Tuko hapa wakati wowote utakapotuhitaji.")]
    # durable: on the person, in the timeline, in redis
    async def check():
        from sqlalchemy import select
        from app.models.conversation import Conversation
        from app.models.intercept import Intercept
        from app.models.person import Person
        async with maker() as db:
            conv = await db.get(Conversation, cid)
            person = await db.get(Person, conv.person_id)
            flags = (await db.execute(select(Intercept).where(Intercept.conversation_id == cid))).scalars().all()
            return intent.preferences(person), [f.note for f in flags], await intent.opted_out(db, _Redis(), conv)
    prefs, notes, durable = run(check())
    assert prefs["opt_out"]["said"].startswith("Acha kunitumia") and durable is True
    assert any("asked not to be messaged" in n for n in notes)
    # the pending nudge is withdrawn, and a second opt-out gets silence
    assert _actions(maker, cid)[0][1] == "vetoed"
    assert run(runtime.schedule_reply(r, WILLY, "please stop messaging me", "d2")) is True
    assert len(sent) == 1
    # every unprompted path stands down
    _plan(maker, cid, "fit_check", "Order BH-9 was delivered 6 days ago")
    async def tick():
        async with maker() as db:
            return await actions.process_due(db, r)
    assert run(tick()) == 0 and len(sent) == 1
    assert dict((k, s) for k, s, _, _ in _actions(maker, cid))["fit_check"] == "needs_approval"
    async def cart():
        async with maker() as db:
            from app.models.conversation import Conversation
            conv = await db.get(Conversation, cid)
        row = {"conv": conv, "to": WILLY, "items": [{"name": "Golden Communion Tray", "qty": 1}],
               "owner": "o", "total": 220}
        return await cart_recovery._handle(r, row, send=True)
    assert run(cart())["skipped"] == "customer asked not to be messaged"
    assert _outbound(maker, cid)[0][1]["source"] == "opt_out"


# ── delivery statuses and duplicate webhooks ─────────────────────────────────

def test_delivery_statuses_land_on_the_sent_row_and_duplicate_webhooks_ingest_once(maker, monkeypatch):
    from app.services import wa_native
    cid = _seed(maker, JUDAS, name="Judas Othow")
    _msg(maker, cid, JUDAS, "outbound", "Your quotation stands until 17 November.", minutes_ago=5,
         wamid="wamid.OUT1")
    r = _Redis()
    status_payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "statuses": [{"id": "wamid.OUT1", "status": "delivered", "timestamp": "1762340000", "recipient_id": JUDAS},
                     {"id": "wamid.OUT1", "status": "read", "timestamp": "1762340100", "recipient_id": JUDAS}]}}]}]}
    run(wa_native.handle_webhook(status_payload, r))
    text, meta, _ = _outbound(maker, cid)[0]
    assert meta["delivery"]["status"] == "read"

    async def no_turn(*a, **k): return None
    monkeypatch.setattr(wa_native, "_reply_after_debounce", no_turn)
    inbound = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"wa_id": JUDAS, "profile": {"name": "Judas Othow"}}],
        "messages": [{"from": JUDAS, "id": "wamid.IN1", "timestamp": "1762340200", "type": "text",
                      "text": {"body": "Can my friend collect on Monday?"}}]}}]}]}
    assert run(wa_native.handle_webhook(inbound, r)) == (1, 0)
    assert run(wa_native.handle_webhook(inbound, r)) == (1, 0)      # Meta redelivers: absorbed
    async def count():
        from sqlalchemy import func, select
        from app.models.message import Message, MsgDirection
        async with maker() as db:
            return (await db.execute(select(func.count()).select_from(Message).where(
                Message.conversation_id == cid, Message.direction == MsgDirection.inbound))).scalar()
    assert run(count()) == 1
