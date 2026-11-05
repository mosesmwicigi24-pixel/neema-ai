"""OUTBOUND COMMUNICATION, STAGE 3 — on a real Postgres: what the customer
said decides what the schedulers do. Willy (comparing in Arusha) holds every
sales nudge; a Hindi-speaking pastor's unprompted messages wait for a person
while the live turn answers; "contact me on Thursday" is one promise and one
hold; "I have already paid" is noted, never believed; a language switch is
followed; the hold lifts when they return. Skips without a reachable Postgres."""
from datetime import datetime, timedelta, timezone

from tests.test_outreach_stage2_db import (  # noqa: F401 — the fixture and helpers
    _Redis, _msg, _outbound, _rows, _seed, _tick, _wire, maker, run)
from tests.test_security_db import fresh_db, pytestmark  # noqa: F401
from app.core.config import settings

WILLY, PASTOR, GRACE = "255754648158", "919876543210", "254722000111"


def _scribe(maker, wa, reply, inbound):  # noqa: F811 — the fixture
    from app.services import deals

    async def go():
        async with maker() as db:
            await deals.scribe_update(db, wa, "whatsapp", reply, inbound_text=inbound)
    run(go())


def _deal(maker, cid):  # noqa: F811 — the fixture
    from app.services.deals import open_deal_for

    async def go():
        async with maker() as db:
            return await open_deal_for(db, conversation_id=cid)
    return run(go())


def _person_state(maker, cid):  # noqa: F811 — the fixture
    async def go():
        async with maker() as db:
            from app.models.conversation import Conversation
            from app.models.person import Person
            c = await db.get(Conversation, cid)
            return dict((await db.get(Person, c.person_id)).state or {})
    return run(go())


def _live_note(maker, wa):  # noqa: F811 — the fixture
    from app.services import customer_state

    async def go():
        async with maker() as db:
            return await customer_state.live_note(db, wa, "whatsapp")
    return run(go())


def _plan(maker, cid, kind, reason, *, source, deal_id=None, minutes_ago=1):  # noqa: F811 — the fixture
    from app.services import actions

    async def go():
        async with maker() as db:
            row, _ = await actions.plan(db, conversation_id=cid, kind=kind, deal_id=deal_id,
                                        due_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
                                        reason=reason, source=source)
            return row.id
    return run(go())


def _due(maker, cid):  # noqa: F811 — the fixture
    from sqlalchemy import select
    from app.models.agent_action import AgentAction

    async def go():
        async with maker() as db:
            return {a.kind: (a.status, a.due_at.replace(tzinfo=timezone.utc) if a.due_at.tzinfo is None else a.due_at)
                    for a in (await db.execute(select(AgentAction).where(
                        AgentAction.conversation_id == cid))).scalars().all()}
    return run(go())


def _set_hold(maker, cid, until):  # noqa: F811 — the fixture
    from sqlalchemy.orm.attributes import flag_modified
    from app.services.deals import open_deal_for

    async def go():
        async with maker() as db:
            deal = await open_deal_for(db, conversation_id=cid)
            nxt = dict(deal.next_action or {})
            nxt["hold"]["until"] = until.isoformat(timespec="seconds")
            deal.next_action = nxt
            flag_modified(deal, "next_action")
            await db.commit()
    run(go())


def _compose(monkeypatch, text):
    from app.services import actions

    async def compose(db, redis, c, reason): return text
    monkeypatch.setattr(actions, "_compose_follow_up", compose)


# ── Willy: "I'm checking the sellers here in Arusha" ─────────────────────────

def test_willy_comparing_in_arusha_holds_the_nudge_and_tells_the_next_turn(maker, monkeypatch):  # noqa: F811 — the fixture
    cid = _seed(maker, WILLY, name="Willy K. Ackyoo")
    _msg(maker, cid, WILLY, "inbound", "Bei ya tray?", minutes_ago=180)
    _msg(maker, cid, WILLY, "outbound", "Golden Communion Tray ni $220.", minutes_ago=179)
    _plan(maker, cid, "buying_follow_up", "They built a cart — Golden Communion Tray", source="cart_recovery",
          minutes_ago=1)
    inbound = "Ninataka kufuatilia wanaouza hapa Arusha. Nitakuambia nikishapata majibu"
    _msg(maker, cid, WILLY, "inbound", inbound, minutes_ago=60)
    _msg(maker, cid, WILLY, "outbound", "Sawa, Rev. Dr. Ackyoo — tutakungoja.", minutes_ago=59)
    _scribe(maker, WILLY, "Sawa, Rev. Dr. Ackyoo — tutakungoja.", inbound)

    deal = _deal(maker, cid)
    assert deal is not None and deal.next_action["hold"]["said"] == "comparing"
    assert deal.blocking.startswith("Comparing prices — until")
    st = _person_state(maker, cid)
    assert st["contact_preferences"]["language"] == "sw" and st["customer_state"]["said"] == "comparing"

    sent = _wire(monkeypatch)
    _compose(monkeypatch, "Habari Willy, tray bado ipo — nikuwekee?")
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)  # the hold is never shadowed
    assert _tick(maker, _Redis()) == 0 and sent == []
    status, due = _due(maker, cid)["buying_follow_up"]
    assert status == "planned" and due > datetime.now(timezone.utc) + timedelta(days=6)
    note = _live_note(maker, WILLY)
    assert "comparing prices" in note and "do NOT ask again when they will decide" in note

    # a week on he writes again about the item: the hold lifts, the nudge may go
    _set_hold(maker, cid, datetime.now(timezone.utc) - timedelta(minutes=5))
    _msg(maker, cid, WILLY, "inbound", "Habari, bado mnayo tray?", minutes_ago=2)
    _scribe(maker, WILLY, "Ndiyo, bado ipo.", "Habari, bado mnayo tray?")
    assert _live_note(maker, WILLY) is None
    async def bring_forward():
        from sqlalchemy import update
        from app.models.agent_action import AgentAction
        async with maker() as db:
            await db.execute(update(AgentAction).where(AgentAction.conversation_id == cid)
                             .values(due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                                     created_at=datetime.now(timezone.utc)))
            await db.commit()
    run(bring_forward())
    assert _tick(maker, _Redis()) == 1 and len(sent) == 1


# ── a pastor who writes in Hindi ─────────────────────────────────────────────

def test_a_hindi_speaking_pastor_is_answered_live_but_never_nudged_by_a_machine(maker, monkeypatch):  # noqa: F811 — the fixture
    cid = _seed(maker, PASTOR, name="Pastor Emmanuel")
    inbound = "नमस्ते, कृपया मुझे बैंगनी चेज़ुबल की कीमत बताएं"
    _msg(maker, cid, PASTOR, "inbound", inbound, minutes_ago=30)
    _msg(maker, cid, PASTOR, "outbound", "नमस्ते पास्टर, बैंगनी चेज़ुबल $140 है।", minutes_ago=29)
    _scribe(maker, PASTOR, "नमस्ते पास्टर, बैंगनी चेज़ुबल $140 है।", inbound)
    assert _person_state(maker, cid)["contact_preferences"]["language"] == "hi"

    _plan(maker, cid, "buying_follow_up", "They built a cart — purple chasuble", source="cart_recovery")
    sent = _wire(monkeypatch)
    _compose(monkeypatch, "should never be composed")
    assert _tick(maker, _Redis()) == 0 and sent == []
    rows = _rows(maker, cid)
    assert rows[-1][1] == "needs_approval" and "they write in 'hi'" in rows[-1][4]


# ── "I will consult the committee and contact you on Thursday" ──────────────

def test_a_named_day_is_one_promise_and_one_hold(maker, monkeypatch):  # noqa: F811 — the fixture
    cid = _seed(maker, GRACE, name="Grace W.")
    _msg(maker, cid, GRACE, "inbound", "How much for 2 cassock sets?", minutes_ago=50)
    _msg(maker, cid, GRACE, "outbound", "Two Cassock Sets come to $420.", minutes_ago=49)
    inbound = "I will consult the committee and contact you on Thursday"
    _msg(maker, cid, GRACE, "inbound", inbound, minutes_ago=10)
    _msg(maker, cid, GRACE, "outbound", "Thank you, Grace — we'll be waiting.", minutes_ago=9)
    _scribe(maker, GRACE, "Thank you, Grace — we'll be waiting.", inbound)
    _scribe(maker, GRACE, "Of course — Thursday it is.", inbound)          # said twice, one promise

    rows = _rows(maker, cid)
    assert [r[0] for r in rows] == ["customer_promise"] and rows[0][2].startswith("customer_promise:")
    deal = _deal(maker, cid)
    hold = deal.next_action["hold"]
    assert hold["said"] == "consulting" and deal.next_action["kind"] == "customer_promise"
    until = datetime.fromisoformat(hold["until"])
    assert until.weekday() == 3 and until > datetime.now(timezone.utc)           # Thursday 10:00 Nairobi
    note = _live_note(maker, GRACE)
    assert "consulting someone" in note and "Thursday" in note

    # a sales nudge planned meanwhile waits for Thursday …
    _plan(maker, cid, "buying_follow_up", "They built a cart — 2 Cassock Sets", source="cart_recovery",
          deal_id=deal.id)
    sent = _wire(monkeypatch)
    _compose(monkeypatch, "Hello Grace, as agreed — any word from the committee?")
    assert _tick(maker, _Redis()) == 0 and sent == []
    due = _due(maker, cid)
    assert due["buying_follow_up"][0] == "planned" and due["buying_follow_up"][1].date() == until.date()
    # … while the promise itself goes when its day comes (the nudge behind it is merged, not sent)
    async def promise_due_now():
        from sqlalchemy import update
        from app.models.agent_action import AgentAction
        async with maker() as db:
            await db.execute(update(AgentAction).where(AgentAction.kind == "customer_promise")
                             .values(due_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await db.commit()
    run(promise_due_now())
    assert _tick(maker, _Redis()) == 1 and len(sent) == 1 and "committee" in sent[0][1]
    due = _due(maker, cid)
    assert due["customer_promise"][0] == "sent"
    assert due["buying_follow_up"][0] in ("planned", "vetoed")       # never a second message


# ── "I have already paid" ────────────────────────────────────────────────────

def test_a_payment_claim_is_recorded_for_a_person_and_never_marked_paid(maker):  # noqa: F811 — the fixture
    cid = _seed(maker, GRACE, name="Grace W.")
    _msg(maker, cid, GRACE, "inbound", "I want the purple stole", minutes_ago=100)
    _msg(maker, cid, GRACE, "outbound", "Purple Stole, $45 — here is the link.", minutes_ago=99)
    _scribe(maker, GRACE, "Purple Stole, $45 — here is the link.", "I want the purple stole")
    _msg(maker, cid, GRACE, "inbound", "I have already paid, check your Mpesa", minutes_ago=5)
    _scribe(maker, GRACE, "Thank you! The confirmation reaches you here.", "I have already paid, check your Mpesa")
    deal = _deal(maker, cid)
    assert deal is not None and deal.blocking.startswith("Says they have paid — awaiting the hub")
    assert deal.status == "open" and deal.stage != "won"
    assert "never announce it as received" in _live_note(maker, GRACE)


# ── the language follows them ────────────────────────────────────────────────

def test_the_stored_language_follows_a_switch(maker):  # noqa: F811 — the fixture
    cid = _seed(maker, GRACE, name="Grace W.")
    _scribe(maker, GRACE, "Stola ni $45.", "Habari, bei ya stola ni ngapi?")
    assert _person_state(maker, cid)["contact_preferences"]["language"] == "sw"
    _scribe(maker, GRACE, "The chasuble is $140.", "And how much is the chasuble please?")
    assert _person_state(maker, cid)["contact_preferences"]["language"] == "en"
