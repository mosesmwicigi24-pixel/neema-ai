"""UNCLAIMED HUMAN CHATS (owner, 2026-11-05): a chat handed to the team that
nobody picked up is rung again after 30 minutes, and Neema answers a plain
price or stock question from the hub, then says a colleague will follow.
Real Postgres through the real sweep; skips without one."""
import asyncio
from datetime import datetime, timedelta, timezone

from tests import test_calls_db as _calls, test_security_db as _sec

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark


def _held(env, wa, text, *, minutes_ago=40, assigned=None, mode="human"):
    from app.models.conversation import InterceptMode
    from app.models.message import Message, MsgDirection, MsgSender
    from app.services.channel import get_or_create_conversation

    async def go():
        async with env.maker() as db:
            conv = await get_or_create_conversation(db, "whatsapp", wa, wa_id=wa)
            conv.intercept_mode = InterceptMode(mode)
            conv.assigned_agent_id = assigned
            db.add(Message(channel="whatsapp", wa_id=wa, external_id=wa, conversation_id=conv.id,
                           direction=MsgDirection.inbound, sender=MsgSender.user, text=text,
                           created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
            await db.commit()
            return str(conv.id)
    return asyncio.run(go())


def _wire(monkeypatch, reply):
    sent = []

    async def _run_turn(db, redis, wa_id, user_text, llm, media=None, **kw):
        _run_turn.notes.append(kw.get("extra_note") or "")
        return reply
    _run_turn.notes = []
    monkeypatch.setattr("app.agent.runtime.run_turn", _run_turn)

    async def _send_waba(to, text, **kw):
        sent.append((to, text))
        return f"wamid.{len(sent)}"
    monkeypatch.setattr("app.services.messaging._send_waba", _send_waba)
    return sent, _run_turn


def _bells(env):
    return [m for c, m in env.redis.published
            if c == "ws:channel:agents:all" and m.get("type") == "human_transfer"]


def test_an_unclaimed_price_question_is_answered_and_a_colleague_promised(env, world, monkeypatch):
    from app.services import unclaimed
    cid = _held(env, "254700000601", "What about the incense burner?")
    sent, rt = _wire(monkeypatch, "The Incense Burner / Thurible is KES 15,000.")
    out = asyncio.run(unclaimed.sweep_unclaimed(env.redis, minutes=30))
    assert out == {"rung": 1, "answered": 1}
    assert [t for _, t in sent] == ["The Incense Burner / Thurible is KES 15,000.",
                                     unclaimed.FOLLOW["en"]]
    assert "UNCLAIMED HUMAN CHAT" in rt.notes[0] and "SKIP" in rt.notes[0]
    bell = _bells(env)[0]
    assert "Nobody has picked up" in bell["title"] and "30 min" in bell["title"]
    assert bell["conversationId"] == cid
    # Once per customer message: the next tick does nothing.
    assert asyncio.run(unclaimed.sweep_unclaimed(env.redis, minutes=30)) == {"rung": 0, "answered": 0}
    assert len(sent) == 2
    # The chat stays with the team.
    assert asyncio.run(_mode(env, cid)) == ("human", None)


async def _mode(env, cid):
    from app.models.conversation import Conversation
    async with env.maker() as db:
        c = await db.get(Conversation, cid)
        return (c.intercept_mode.value if hasattr(c.intercept_mode, "value") else str(c.intercept_mode),
                c.assigned_agent_id)


def test_anything_but_a_price_or_stock_question_is_left_to_the_colleague(env, world, monkeypatch):
    from app.services import unclaimed
    _held(env, "254700000602", "Mlisema kuna bargain ya hizi prices")
    sent, _ = _wire(monkeypatch, "SKIP")
    out = asyncio.run(unclaimed.sweep_unclaimed(env.redis, minutes=30))
    assert out == {"rung": 1, "answered": 0} and sent == []
    assert len(_bells(env)) == 1


def test_a_claimed_chat_a_fresh_one_and_an_ai_one_are_not_touched(env, world, monkeypatch):
    from app.services import unclaimed
    _held(env, "254700000603", "How much?", assigned=world["ann"])           # claimed
    _held(env, "254700000604", "How much?", minutes_ago=10)                  # too fresh
    _held(env, "254700000605", "How much?", mode="ai")                       # Neema's own
    sent, _ = _wire(monkeypatch, "KES 1.")
    assert asyncio.run(unclaimed.sweep_unclaimed(env.redis, minutes=30)) == {"rung": 0, "answered": 0}
    assert sent == [] and _bells(env) == []


def test_escalating_to_a_human_stamps_when_the_hand_over_began(env, world):
    from app.agent.runtime import escalate_to_human
    from app.models.conversation import Conversation
    cid = _held(env, "254700000606", "hello", mode="ai")
    assert asyncio.run(escalate_to_human("whatsapp", "254700000606", "test", redis=env.redis))

    async def since():
        async with env.maker() as db:
            return (await db.get(Conversation, cid)).intercept_since
    assert asyncio.run(since()) is not None


def test_the_tick_is_registered():
    import inspect
    import app.main as m
    src = inspect.getsource(m)
    assert "_unclaimed_loop" in src and "sweep_unclaimed(redis)" in src
