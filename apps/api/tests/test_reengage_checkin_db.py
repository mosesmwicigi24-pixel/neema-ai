"""Re-engage: a FRESH check-in or nothing — real Postgres.

The 2026-10-10 preview: all 5 re-engage drafts replayed or continued an
interrupted turn ("Thank you for your patience.", "I'm confirming the blue
and red chasubles with our team now…", "At today's rate, $350 is about
R5,788.62 … Shall I place the order now?"). Root cause: the sweep re-ran the
live reply turn on the customer's last message. Now it only takes threads
where WE spoke last and the customer went quiet, composes a fresh check-in
with no tools, and a quality gate refuses anything that is not one.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests.test_security_db import fresh_db, pytestmark  # noqa: F401
from tests.test_recovery_jobs_db import FakeRedis

HANDOFF_WA, CLOSER_WA, TRAYS_WA = "254711100001", "254711100002", "254711100003"
HUMAN_WA, SW_WA, CART_WA, OLD_WA = "254711100004", "254711100005", "254711100006", "254711100007"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def re(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.jobs import reengage
    from app.services import n8n_bridge, meta_send

    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE agent_actions, deals, messages, order_events, users, "
                          "intercepts, conversations, persons CASCADE"))
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    maker = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                               class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(reengage, "AsyncSessionLocal", maker)
    monkeypatch.setattr(reengage, "within_quiet_hours", lambda *a, **k: True)

    llm = {"answers": {}, "prompts": []}

    async def compose(system, user, redis=None):
        llm["prompts"].append((system, user))
        for key, answer in llm["answers"].items():
            if key in user:
                return answer
        return '{"skip": "nothing discussed"}'
    monkeypatch.setattr(reengage, "_compose_llm", compose)

    sent = []

    async def waba(to, text, *a, **k):
        sent.append((to, text))
        return "wamid.x"

    async def meta(channel, to, text, *a, **k):
        sent.append((to, text))

    async def save(*a, **k):
        return None
    monkeypatch.setattr(n8n_bridge, "_send_waba", waba)
    monkeypatch.setattr(n8n_bridge, "save_outbound_message", save)
    monkeypatch.setattr(meta_send, "send_to_channel", meta)
    _seed(maker)
    return {"maker": maker, "sent": sent, "llm": llm}


def _seed(maker):
    from app.models.conversation import Conversation, InterceptMode
    from app.models.message import Message, MsgDirection, MsgSender
    from app.models.user import User
    now = datetime.now(timezone.utc)

    threads = {
        # bad case 2 (preview): our last line handed the thread to the team
        HANDOFF_WA: ("Major Otieno", [
            ("in", "Do you have the chasuble in blue and red?", 6),
            ("out", "Thank you for waiting. I'm confirming the blue and red chasubles with "
                    "our team now — they'll have the answer for you here in a moment…", 5)]),
        # bad case 1: the customer's closer is the newest turn (unanswered)
        CLOSER_WA: ("Ruth Achieng", [
            ("in", "How much is the Clergy Shirt?", 6),
            ("out", "The Clergy Shirt is KES 2,500 🙏 Which size would you like?", 5.9),
            ("in", "ok thanks", 5)]),
        # bad case 3: quoted in dollars, then quiet — a real check-in candidate
        TRAYS_WA: ("Sipho Ndlovu", [
            ("in", "How much for 5 Aluminium Trays in dollars?", 6),
            ("out", "The 5 Aluminium Trays come to $350 in total 🙏 Shall I place the order?", 5)]),
        HUMAN_WA: ("Peter", [
            ("in", "Do you have red stoles?", 6),
            ("out", "Yes, the Red Stole is KES 3,500.", 5)]),
        SW_WA: ("Mercy Wambui", [
            ("in", "Nataka cassock nyeusi, bei gani?", 6),
            ("out", "Black Cassock ni KES 6,500 🙏 Ungependa size gani?", 5)]),
        CART_WA: ("Grace", [
            ("in", "Add the Gold Cope please", 6),
            ("out", "Added the Gold Cope to your cart 🙏", 5)]),
        OLD_WA: ("John", [
            ("in", "Do you sell albs?", 23.5),
            ("out", "Yes, the Linen Alb is KES 4,000.", 23)]),
    }

    async def go():
        async with maker() as db:
            for wa, (name, msgs) in threads.items():
                state = ({"agent_cart": {"items": [{"name": "Gold Cope", "qty": 1,
                                                    "unit_price": 25000}]}}
                         if wa == CART_WA else {})
                db.add(User(wa_id=wa, name=name, state=state))
                cid = uuid.uuid4()
                db.add(Conversation(
                    id=cid, wa_id=wa, channel="whatsapp", external_id=wa,
                    intercept_mode=InterceptMode.human if wa == HUMAN_WA else InterceptMode.ai,
                    last_message_at=now - timedelta(hours=msgs[-1][2])))
                await db.flush()
                for d, text, ago in msgs:
                    inbound = d == "in"
                    db.add(Message(id=uuid.uuid4(), conversation_id=cid, wa_id=wa,
                                   external_id=wa, channel="whatsapp", text=text,
                                   direction=MsgDirection.inbound if inbound else MsgDirection.outbound,
                                   sender=MsgSender.user if inbound else MsgSender.ai,
                                   created_at=now - timedelta(hours=ago)))
            await db.commit()
    run(go())


def _skips(maker):
    from app.jobs import reengage

    async def go():
        from app.models.conversation import Conversation
        out = {}
        async with maker() as db:
            for conv in (await db.execute(sa.select(Conversation))).scalars().all():
                reason, _ = await reengage.why_not(db, conv, datetime.now(timezone.utc))
                out[conv.wa_id] = reason
        return out
    return run(go())


def test_only_quiet_threads_we_answered_are_candidates(re):
    reasons = _skips(re["maker"])
    assert reasons[HANDOFF_WA] == "last outbound handed off to the team"
    assert reasons[CLOSER_WA] == "unanswered customer message"      # missed-reply's, not ours
    assert reasons[HUMAN_WA] == "human mode / closed"
    assert reasons[CART_WA] == "cart in progress (cart recovery's)"
    assert reasons[OLD_WA] == "24h window closed"
    assert reasons[TRAYS_WA] is None and reasons[SW_WA] is None


def test_the_three_bad_shapes_end_as_a_proper_check_in_or_a_skip(re):
    from app.jobs import reengage
    # the model misbehaves exactly as the preview did → refused, nothing sent
    re["llm"]["answers"] = {
        "Aluminium Trays": json.dumps({"item": "Aluminium Trays", "text":
                                       "At today's rate, $350 is about R5,788.62 for the 5 "
                                       "Aluminium Trays… Shall I place the order now?"}),
        "Black Cassock": json.dumps({"item": "Black Cassock",
                                     "text": "Thank you for your patience."}),
    }
    r = FakeRedis()
    out = run(reengage.run(send=True, redis=r))
    assert re["sent"] == []
    assert out["candidates"] == 2 and out["sent"] == 0 and out["skipped"] == 2
    assert {x["reason"] for x in out["refused"]} == {
        "continues a turn / thanks for waiting / promises a colleague / new price"}
    assert out["samples"] == []
    # a live run claimed each message's guard before composing, so a rerun on
    # the same redis is a skip — never a second attempt at nonsense
    assert len([k for k in r.kv if k.startswith("reengage:")]) == 2

    # a well-behaved model → a proper check-in naming the item, in the thread's terms
    re["llm"]["answers"] = {
        "Aluminium Trays": json.dumps({"item": "Aluminium Trays", "text":
                                       "Hello Sipho 🙏 just checking in on the 5 Aluminium "
                                       "Trays at $350. Would you like me to place the order?"}),
    }
    out2 = run(reengage.run(send=True, redis=FakeRedis()))
    assert [to for to, _ in re["sent"]] == [TRAYS_WA]
    text = re["sent"][0][1]
    assert "Sipho" in text and "Aluminium Trays" in text and "$350" in text
    assert out2["sent"] == 1
    for _, t in re["sent"]:
        assert not reengage._BAD_RE.search(t)
    # the handoff / closer / human / cart / stale threads were never even composed
    composed = " ".join(u for _, u in re["llm"]["prompts"])
    assert "chasubles with our team" not in composed and "ok thanks" not in composed


def test_language_follows_the_thread(re):
    from app.jobs import reengage
    re["llm"]["answers"] = {"Black Cassock": json.dumps({"item": "Black Cassock", "text":
                            "Hello Mercy 🙏 would you still like the Black Cassock at KES 6,500?"})}
    out = run(reengage.run(send=True, redis=FakeRedis()))
    system = next(s for s, u in re["llm"]["prompts"] if "Black Cassock" in u)
    assert "Swahili" in system and "Mercy" in system
    assert re["sent"] == []
    assert any(x["reason"] == "not in the thread's language (Swahili)" for x in out["refused"])

    re["llm"]["answers"] = {"Black Cassock": json.dumps({"item": "Black Cassock", "text":
                            "Habari Mercy 🙏 bado unataka ile Black Cassock ya KES 6,500? "
                            "Nikuwekee size yako?"})}
    run(reengage.run(send=True, redis=FakeRedis()))
    assert [to for to, _ in re["sent"]] == [SW_WA]


def test_once_per_customer_message_and_a_dry_run_claims_nothing(re):
    from app.jobs import reengage
    re["llm"]["answers"] = {"Aluminium Trays": json.dumps({"item": "Aluminium Trays", "text":
                            "Hello Sipho 🙏 would you still like the 5 Aluminium Trays at $350?"})}
    r = FakeRedis()
    dry = run(reengage.run(send=False, redis=r, max_drafts=3))
    assert re["sent"] == [] and not r.kv
    assert len(dry["samples"]) == 1 and "Aluminium Trays" in dry["samples"][0]["text"]
    assert dry["samples"][0]["to"] == "…0003"
    run(reengage.run(send=True, redis=r))
    assert [to for to, _ in re["sent"]] == [TRAYS_WA]
    assert [k for k in r.kv if k.startswith("reengage:")]
    re["sent"].clear()
    again = run(reengage.run(send=True, redis=r))
    assert re["sent"] == [] and again["sent"] == 0


def test_a_customer_reply_after_selection_stops_the_send(re, monkeypatch):
    """The customer speaks between selection and send → the check-in is the
    wrong message; the thread is the live path's again."""
    from app.jobs import reengage
    from app.models.message import Message, MsgDirection, MsgSender
    re["llm"]["answers"] = {"Aluminium Trays": json.dumps({"item": "Aluminium Trays", "text":
                            "Hello Sipho 🙏 would you still like the 5 Aluminium Trays at $350?"})}
    real = reengage._compose_llm

    async def compose_then_reply(system, user, redis=None):
        if "Aluminium Trays" in user:
            async with re["maker"]() as db:
                conv_id = (await db.execute(sa.text(
                    "SELECT id FROM conversations WHERE wa_id=:w"), {"w": TRAYS_WA})).scalar()
                db.add(Message(id=uuid.uuid4(), conversation_id=conv_id, wa_id=TRAYS_WA,
                               external_id=TRAYS_WA, channel="whatsapp", text="yes please",
                               direction=MsgDirection.inbound, sender=MsgSender.user,
                               created_at=datetime.now(timezone.utc)))
                await db.commit()
        return await real(system, user, redis)
    monkeypatch.setattr(reengage, "_compose_llm", compose_then_reply)
    run(reengage.run(send=True, redis=FakeRedis()))
    assert re["sent"] == []
