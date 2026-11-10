"""INTENT DISCERNMENT on a real Postgres — the owner's eight scenarios
(directive of 2026-11-10, §6), as far as they are decided before the model
speaks: who gets the boundary, who gets one more line, who gets silence, and
— the larger half — who is never touched. The words of the reply itself are
the writer's (cases in app/jobs/eval_cases/intent_discernment.jsonl, run only
on the owner's word). Skips without a reachable Postgres.

Scenario 1 uses a stand-in for the Pakistan conversation (the thread itself
was not attached to the directive): a price asked, a quote given, then
repeated hardship appeals and a request for a gift."""
import asyncio

import app.main  # noqa: F401
from tests import test_calls_db as _calls, test_security_db as _sec

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark


def _run(coro):
    return asyncio.run(coro)


async def _start(db, wa, name="Pastor"):
    from app.services.channel import get_or_create_conversation
    from app.services.messaging import provision_user
    await provision_user(db, wa, name=name)
    conv = await get_or_create_conversation(db, "whatsapp", wa, wa_id=wa)
    await db.commit()
    return conv


async def _say(env, wa, text, **kw):
    from app.services import buyer_intent as bi
    async with env.maker() as db:
        return await bi.decide(db, env.redis, channel="whatsapp", key=wa, text=text, **kw)


async def _record(env, wa):
    from sqlalchemy import select
    from app.models.person import Person
    from app.models.user import User
    from app.services import buyer_intent as bi
    async with env.maker() as db:
        u = (await db.execute(select(User).where(User.wa_id == wa))).scalar_one()
        p = await db.get(Person, u.person_id)
        return bi.record(p.state), dict(p.state or {})


async def _timeline(env, wa):
    from sqlalchemy import select
    from app.models.agent_activity import AgentActivity
    async with env.maker() as db:
        rows = (await db.execute(select(AgentActivity).where(
            AgentActivity.contact == wa, AgentActivity.tool == "customer_state")
            .order_by(AgentActivity.created_at))).scalars().all()
        return [(r.summary, r.detail) for r in rows]


def test_1_the_repeated_appeal_gets_one_boundary_one_line_then_silence(env, world):
    from app.services import buyer_intent as bi
    wa = "923001234567"                                   # a Pakistani number

    async def go():
        async with env.maker() as db:
            await _start(db, wa)
        # he asks the price like any customer: nothing is read into where he writes from
        assert await _say(env, wa, "Hello, how much is the ordination gown?") is None
        assert (await _record(env, wa))[0] == {}
        # hardship alone, after a quote: still nothing — a buyer short of money says the same
        assert await _say(env, wa, "I am a poor pastor, we are a small church in the village") is None
        # the request
        v1 = await _say(env, wa, "Please bless me with one as a gift, I have no money")
        assert v1["action"] == "note" and v1["boundary"] == 1 and v1["note"] == bi.FIRST_NOTE
        # the appeal again — no new ask in the words, but the request stands
        v2 = await _say(env, wa, "Please have mercy, God will reward you, remember us orphans")
        assert v2["action"] == "note" and v2["boundary"] == 2 and v2["note"] == bi.SECOND_NOTE
        # and again, and again: no automatic reply to that request
        v3 = await _say(env, wa, "Kindly help, I am asking for a gift only")
        v4 = await _say(env, wa, "please please remember me, I am poor")
        assert v3 == {"action": "silence", "why": "request closed", "boundary": 3}
        assert v4["action"] == "silence"
        rec, state = await _record(env, wa)
        assert rec["reading"] == "assistance" and rec["boundary"]["closed"] is True
        assert bi.suppresses_promotion(state)
        assert await _timeline(env, wa) == [
            ("Asked for goods without payment", "the boundary was given"),
            ("Asked for goods without payment", "acknowledged once more; the request is closed")]
    _run(go())


def test_2_a_pastor_saving_toward_an_alb_is_a_buyer(env, world):
    wa = "254711000002"

    async def go():
        async with env.maker() as db:
            await _start(db, wa)
        for text in ("How much is the alb?",
                     "That is a lot for me now, I am saving little by little",
                     "I will order next month when I have the full amount",
                     "Can I pay bit by bit until then?"):
            assert await _say(env, wa, text) is None, text
        assert (await _record(env, wa))[0] == {}             # nothing was ever recorded against him
    _run(go())


def test_3_a_bulk_negotiator_is_never_touched(env, world):
    wa = "254711000003"

    async def go():
        async with env.maker() as db:
            await _start(db, wa)
        for text in ("We need 30 cassocks for the diocese. What is your best price?",
                     "That is too high, can you give us a discount? Our budget is small",
                     "Other suppliers are cheaper. Give us your last price and we order today"):
            assert await _say(env, wa, text) is None, text
        assert (await _record(env, wa))[0] == {}
    _run(go())


def test_4_a_free_cassock_for_ministry_gets_the_one_boundary(env, world):
    from app.services import buyer_intent as bi
    wa = "256771000004"

    async def go():
        async with env.maker() as db:
            await _start(db, wa)
        v = await _say(env, wa, "Praise God. I am an evangelist, kindly give me a free cassock for the ministry")
        assert v == {"action": "note", "note": bi.FIRST_NOTE, "boundary": 1}
        rec, _ = await _record(env, wa)
        assert rec["reading"] == "assistance" and rec["boundary"]["count"] == 1 and not rec["boundary"]["closed"]
        # one boundary given, and he says thank you: nothing more from the ladder
        assert (await _say(env, wa, "Okay thank you, God bless you"))["note"] == bi.STANDING_NOTE
    _run(go())


def test_5_credit_until_sunday_is_a_buyer_asking_a_question(env, world):
    wa = "254711000005"

    async def go():
        async with env.maker() as db:
            await _start(db, wa)
        for text in ("Can you send the cassock today and I pay on Sunday after the offering?",
                     "Please, I will pay on Sunday, I promise",
                     "Can I take it on credit until month end?"):
            assert await _say(env, wa, text) is None, text      # the writer answers: payment before delivery, bit by bit
        assert (await _record(env, wa))[0] == {}
    _run(go())


def test_6_declined_before_then_returns_as_a_buyer(env, world):
    from app.services import buyer_intent as bi
    wa = "234801000006"

    async def go():
        async with env.maker() as db:
            await _start(db, wa)
        assert (await _say(env, wa, "Can you donate robes to our choir?"))["boundary"] == 1
        assert (await _say(env, wa, "Please, we really need the donation"))["boundary"] == 2
        assert (await _say(env, wa, "Just donate anything please"))["action"] == "silence"
        # weeks later, a real enquiry: answered as any customer, the record reopened, promotion no longer held
        assert await _say(env, wa, "Good morning. How much is one choir robe? We want to order 12") is None
        rec, state = await _record(env, wa)
        assert rec["reading"] == "buyer" and rec["boundary"]["count"] == 0 and not rec["boundary"]["closed"]
        assert not bi.suppresses_promotion(state)
        assert any(h["reading"] == "assistance" for h in rec["history"])       # history kept, nothing held
        assert (await _timeline(env, wa))[-1] == ("Now asking to buy", "the earlier request is closed")
        for text in ("Blue, with white collars", "Deliver to Lagos please", "Thank you"):
            assert await _say(env, wa, text) is None, text
    _run(go())


def test_7_greetings_and_blessings_only(env, world):
    wa = "254711000007"

    async def go():
        async with env.maker() as db:
            await _start(db, wa)
        for text in ("Good morning", "God bless you", "Amen, blessings to you and the team", "Have a blessed day"):
            assert await _say(env, wa, text) is None, text      # the closer gate and pacing own these
        assert (await _record(env, wa))[0] == {}
    _run(go())


def test_8_an_open_promised_check_or_payment_is_never_closed_on(env, world):
    wa = "254711000008"

    async def go():
        from app.services.deals import open_team_check
        async with env.maker() as db:
            conv = await _start(db, wa)
            await open_team_check(db, conv, "the cope")          # something we promised to check
            await db.commit()
        # even an explicit request does not start the ladder while that is open
        assert await _say(env, wa, "While I wait, can you give me a free stole?") is None
        assert await _say(env, wa, "My parcel has not arrived, where is it?") is None
        assert (await _record(env, wa))[0] == {}
    _run(go())


def test_a_giveaway_post_is_not_a_request(env, world):
    wa = "254711000009"

    async def go():
        async with env.maker() as db:
            await _start(db, wa)
        assert await _say(env, wa, "Please give me the free gift", campaign=True) is None
        assert (await _record(env, wa))[0] == {}
    _run(go())


def test_the_models_reading_is_stored_as_evidence_and_closes_nothing(env, world):
    from sqlalchemy import select
    from app.models.conversation import Conversation
    from app.services import buyer_intent as bi
    wa = "254711000010"

    async def go():
        async with env.maker() as db:
            await _start(db, wa)
        async with env.maker() as db:
            conv = (await db.execute(select(Conversation).where(Conversation.wa_id == wa))).scalars().first()
            assert await bi.apply_note(db, conv, "assistance", "keeps asking for free robes, no order step")
        rec, state = await _record(env, wa)
        assert rec["reading"] == "assistance" and rec["by"] == "note" and "boundary" not in rec
        assert not bi.suppresses_promotion(state)                 # no boundary was given: nothing is held
        # with that reading standing, a bare hardship appeal now counts as the request
        assert (await _say(env, wa, "Please have mercy on a poor pastor"))["boundary"] == 1
        # and the model reading a buyer afterwards reopens it
        async with env.maker() as db:
            conv = (await db.execute(select(Conversation).where(Conversation.wa_id == wa))).scalars().first()
            assert await bi.apply_note(db, conv, "constrained", "wants an alb, saving")
        rec, state = await _record(env, wa)
        assert rec["reading"] == "constrained" and rec["boundary"]["count"] == 0
        assert not bi.suppresses_promotion(state)
    _run(go())
