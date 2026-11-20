"""HOLDS REACH A PERSON (owner, 2026-10-10).

Thirty days of evidence: staff replied within 24 h to only 5–10% of holds.
Two sweeps undid every hand-off before anyone could answer it:

  * auto_release handed a human-held thread back to Neema after 45 minutes of
    colleague silence even while the customer's newest message was still
    unanswered — 1,500 of 1,544 auto-releases happened on exactly such a thread,
    so the colleague who was alerted never got the chance to reply;
  * the missed-reply sweeper, once a message had burnt its three strikes,
    re-escalated the SAME message every time the thread came back to AI
    (1,524 flags on 111 threads, ~14 each, ~6 minutes apart), burying the
    real holds under copies.

Pinned here on a real Postgres: a held thread whose newest message is an
unanswered customer message stays with the person; once a colleague answers,
the quiet thread is released as before and carries an internal note saying
why; a thread handed over by a hold (reviewer hold, failed order, sweeper
escalation) stays with staff until a colleague replies — Neema's own
"a colleague will confirm" line is not an answer; the sweeper escalates — flag
and one team bell — once per unanswered customer message, and a NEW unanswered
message earns exactly one more.
"""
import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests.test_security_db import _reachable, _sync_url, fresh_db  # noqa: F401

pytestmark = pytest.mark.skipif(not _sync_url() or not _reachable(_sync_url()),
                                reason="needs a reachable Postgres (CI migrations job / Docker harness)")

WA = "254700000077"
PSID = "psid-holds-77"


class _Redis:
    def __init__(self):
        self.kv: dict = {}
        self.published: list = []

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k) or 0) + 1
        return self.kv[k]

    async def expire(self, *a):
        return True

    async def delete(self, *keys):
        for k in keys:
            self.kv.pop(k, None)

    async def publish(self, channel, payload):
        self.published.append((channel, payload))


def _ago(**kw):
    return datetime.now(timezone.utc) - timedelta(**kw)


@pytest.fixture
def rig(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database
    from app.core.config import settings
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE intercepts, messages, conversations CASCADE"))
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    maker = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                               class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(app.database, "AsyncSessionLocal", maker)
    monkeypatch.setattr(settings, "auto_release_minutes", 45, raising=False)
    return types.SimpleNamespace(maker=maker, redis=_Redis())


def _conv(rig, *, channel="whatsapp", ext=WA, mode="human", since=None):
    async def go():
        from app.models.conversation import Conversation, InterceptMode
        async with rig.maker() as db:
            c = Conversation(id=uuid.uuid4(), wa_id=(ext if channel == "whatsapp" else None),
                             channel=channel, external_id=ext,
                             intercept_mode=InterceptMode(mode), intercept_since=since)
            db.add(c)
            await db.commit()
            return c.id
    return asyncio.run(go())


def _msg(rig, conv_id, *, inbound, at, text, sender=None, note=False, channel="whatsapp", ext=WA):
    async def go():
        from app.models.message import Message, MsgDirection, MsgSender
        async with rig.maker() as db:
            m = Message(id=uuid.uuid4(), conversation_id=conv_id, channel=channel,
                        wa_id=(ext if channel == "whatsapp" else None), external_id=ext,
                        direction=MsgDirection.inbound if inbound else MsgDirection.outbound,
                        sender=MsgSender(sender or ("user" if inbound else "ai")),
                        text=text, media_type=("note" if note else None), created_at=at)
            db.add(m)
            await db.commit()
            return m.id
    return asyncio.run(go())


def _hold(rig, conv_id, *, at, note):
    async def go():
        from app.models.intercept import Intercept, InterceptAction
        async with rig.maker() as db:
            db.add(Intercept(conversation_id=conv_id, action=InterceptAction.flag, note=note,
                             created_at=at))
            await db.commit()
    asyncio.run(go())


def _state(rig, conv_id):
    async def go():
        from app.models.conversation import Conversation
        from app.models.intercept import Intercept
        from app.models.message import Message
        async with rig.maker() as db:
            c = await db.get(Conversation, conv_id)
            rows = (await db.execute(sa.select(Intercept).where(
                Intercept.conversation_id == conv_id).order_by(Intercept.created_at))).scalars().all()
            notes = (await db.execute(sa.select(Message).where(
                Message.conversation_id == conv_id, Message.media_type == "note")
                .order_by(Message.created_at))).scalars().all()
            return c.intercept_mode.value, rows, notes
    return asyncio.run(go())


def _release_tick(rig):
    from app.services.auto_release import sweep_auto_release
    return asyncio.run(sweep_auto_release(rig.redis))


# ── auto_release ─────────────────────────────────────────────────────────────

def _held_with_unanswered_customer(rig):
    cid = _conv(rig, since=_ago(hours=3))
    _msg(rig, cid, inbound=True, at=_ago(hours=3), text="Habari, do you have stoles?")
    _msg(rig, cid, inbound=False, sender="human_agent", at=_ago(hours=2),
         text="Yes Pastor — which colour?")
    _msg(rig, cid, inbound=True, at=_ago(minutes=90), text="Purple. How much is it?")
    # an internal note is not an answer the customer ever saw
    _msg(rig, cid, inbound=False, sender="ai", note=True, at=_ago(minutes=89),
         text="HELD BACK BY THE REVIEWER — …")
    return cid


def test_a_customer_who_waited_thirty_minutes_goes_back_to_neema_once(rig):
    # owner, 2026-11-19: "If the human interception remains for 30 minutes
    # without being released and without chats continue, release that chat to
    # Neema." Until then a waiting customer kept the chat with the person for
    # good (the rule of 2026-10-10).
    cid = _held_with_unanswered_customer(rig)             # waited 90 minutes
    assert _release_tick(rig) == 1
    mode, rows, notes = _state(rig, cid)
    assert mode == "ai"
    assert [r.action.value for r in rows] == ["release"] and "waited" in rows[0].note
    assert "the customer was still waiting for an answer" in notes[-1].text
    # Neema is told, on her next turn, how she got the chat back
    from app.services import auto_release
    assert rig.redis.kv.get(auto_release.PICKED_UP_KEY.format(channel="whatsapp", key=WA))

    # ONCE PER WAIT: her answer is held and the chat is flagged back to staff —
    # it now stays with them (the flag→release ping-pong of 2026-10 cannot start)
    async def back_to_staff():
        from app.models.conversation import Conversation, InterceptMode
        async with rig.maker() as db:
            c = await db.get(Conversation, cid)
            c.intercept_mode = InterceptMode.human
            await db.commit()
    asyncio.run(back_to_staff())
    _hold(rig, cid, at=_ago(minutes=0), note="HELD BACK BY THE REVIEWER — …")
    assert _release_tick(rig) == 0
    assert _state(rig, cid)[0] == "human"


def test_the_person_still_has_their_thirty_minutes(rig):
    cid = _conv(rig, since=_ago(hours=3))
    _msg(rig, cid, inbound=False, sender="human_agent", at=_ago(hours=2), text="Which colour, Pastor?")
    _msg(rig, cid, inbound=True, at=_ago(minutes=10), text="Purple. How much is it?")
    assert _release_tick(rig) == 0                        # ten minutes is not thirty
    assert _state(rig, cid)[0] == "human"


def test_the_switch_keeps_a_waiting_customer_with_the_person(rig, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "auto_release_waiting", False, raising=False)
    cid = _held_with_unanswered_customer(rig)
    assert _release_tick(rig) == 0 and _state(rig, cid)[0] == "human"


# ── a hold stays with staff until a PERSON replies (owner: "held replies → Human + notify")

_HOLDS = [
    ("HELD BACK BY THE REVIEWER — Neema's reply did not pass verification and was NOT sent",
     "Let me confirm the exact item and price for you 🙏 One of our team will confirm it right here shortly."),
    ("ORDER NOT PLACED — Neema could not create this order in the hub; the customer was told "
     "a colleague will confirm it here.",
     "Thank you Pastor — a colleague has your order and will confirm it with you here."),
    ("Neema composed a reply 3 times but delivery keeps failing on whatsapp — please answer "
     "from here and check the page connection.", None),
]


def _held_by_a_hold(rig, note, hold_line):
    cid = _conv(rig)                              # a hand-off leaves intercept_since empty
    _msg(rig, cid, inbound=True, at=_ago(hours=4), text="Habari, do you have stoles?")
    _msg(rig, cid, inbound=False, sender="human_agent", at=_ago(hours=3), text="Yes Pastor.")
    _msg(rig, cid, inbound=True, at=_ago(hours=2), text="How much is the purple stole?")
    _hold(rig, cid, at=_ago(minutes=119), note=note)
    if hold_line:                                 # Neema's own hand-off line is not an answer
        _msg(rig, cid, inbound=False, sender="ai", at=_ago(minutes=119), text=hold_line)
    # a system note written as human_agent (availability check, brief) is not a person replying
    _msg(rig, cid, inbound=False, sender="human_agent", note=True, at=_ago(minutes=100),
         text="🔎 AVAILABILITY CHECK — the customer asked for: purple stole")
    return cid


@pytest.mark.parametrize("note,hold_line", _HOLDS)
def test_a_hold_nobody_answered_goes_back_once_then_stays_with_staff(rig, note, hold_line):
    # owner, 2026-11-19 (30 minutes, every human-held chat). Before: a hold
    # stayed with staff until a person replied, however long that took.
    cid = _held_by_a_hold(rig, note, hold_line)           # flagged 119 minutes ago, no colleague reply
    assert _release_tick(rig) == 1
    mode, rows, notes = _state(rig, cid)
    assert mode == "ai" and [r.action.value for r in rows].count("release") == 1
    assert "the customer was still waiting for an answer" in notes[-1].text
    assert _release_tick(rig) == 0                        # nothing left to release


def test_a_hold_a_colleague_answered_is_released_as_before(rig):
    note, line = _HOLDS[0]
    cid = _held_by_a_hold(rig, note, line)
    _msg(rig, cid, inbound=False, sender="human_agent", at=_ago(minutes=60),
         text="The purple stole is KES 3,500, Pastor.")
    assert _release_tick(rig) == 1
    mode, rows, notes = _state(rig, cid)
    assert mode == "ai" and "a colleague answered" in notes[-1].text


def test_a_fresh_hold_still_waits_for_a_person(rig):
    cid = _conv(rig)
    _msg(rig, cid, inbound=True, at=_ago(minutes=12), text="How much is the purple stole?")
    _hold(rig, cid, at=_ago(minutes=11), note=_HOLDS[0][0])
    assert _release_tick(rig) == 0 and _state(rig, cid)[0] == "human"


def test_a_held_customer_who_signs_off_has_nothing_pending(rig):
    note, line = _HOLDS[0]
    cid = _held_by_a_hold(rig, note, line)
    _msg(rig, cid, inbound=True, at=_ago(minutes=90), text="🙏")
    assert _release_tick(rig) == 1
    assert "polite close" in _state(rig, cid)[2][-1].text


# ── reply_sweeper ────────────────────────────────────────────────────────────

def _sweeper_rig(rig, monkeypatch):
    from app.agent import runtime as rt
    from app.services import reply_sweeper as sw
    attempts = []

    async def failing_send(redis, channel, ext, text, page_id=None, media=None, **kw):
        attempts.append(text)
        return False                              # delivery keeps failing

    async def not_paused(*a, **k):
        return False
    monkeypatch.setattr(rt, "_run_and_send_meta", failing_send)
    monkeypatch.setattr(rt, "_is_paused", not_paused)
    monkeypatch.setattr(sw, "AsyncSessionLocal", rig.maker)
    return sw, attempts


def _sweep_tick(rig, sw, cid):
    """One sweeper pass on a thread that is back with Neema (a person's Release,
    or the catch-up tool) — the pacing lock has expired between passes."""
    async def back_to_ai():
        from app.models.conversation import Conversation, InterceptMode
        async with rig.maker() as db:
            c = await db.get(Conversation, cid)
            c.intercept_mode = InterceptMode.ai
            await db.commit()
    asyncio.run(back_to_ai())
    for k in [k for k in rig.redis.kv if k.startswith("agent:missed:lock:")]:
        rig.redis.kv.pop(k)
    asyncio.run(sw.sweep_missed_replies(rig.redis))


def _bells(rig):
    import json
    return [json.loads(p) for ch, p in rig.redis.published if ch == "ws:channel:agents:all"]


def _flags(rig, cid):
    return [r for r in _state(rig, cid)[1] if r.action.value == "flag"]


def test_the_sweeper_escalates_once_per_unanswered_message(rig, monkeypatch):
    sw, attempts = _sweeper_rig(rig, monkeypatch)
    cid = _conv(rig, channel="messenger", ext=PSID, mode="ai")
    _msg(rig, cid, inbound=True, at=_ago(minutes=30), text="Is the purple stole available?",
         channel="messenger", ext=PSID)
    for _ in range(3):                            # three strikes, three real attempts
        _sweep_tick(rig, sw, cid)
    assert len(attempts) == 3 and _flags(rig, cid) == []
    for _ in range(5):                            # every later pass: ONE flag, not five
        _sweep_tick(rig, sw, cid)
    assert len(_flags(rig, cid)) == 1
    assert "delivery keeps failing" in _flags(rig, cid)[0].note
    assert len(attempts) == 3                     # and no model turn is bought for it
    # …and the team HEARS of it: one bell, with the customer's own words
    assert len(_bells(rig)) == 1
    bell = _bells(rig)[0]
    assert bell["type"] == "draft_ready" and bell["conv_id"] == str(cid) and bell["wa_id"] == PSID
    assert bell["body"].startswith("\u201cIs the purple stole available?\u201d")
    assert len(bell["body"]) <= 200

    # a NEW unanswered message earns its own strikes and exactly one more flag
    _msg(rig, cid, inbound=True, at=_ago(minutes=5), text="Hello? Still there?",
         channel="messenger", ext=PSID)
    for _ in range(8):
        _sweep_tick(rig, sw, cid)
    assert len(attempts) == 6
    assert len(_flags(rig, cid)) == 2
    assert len(_bells(rig)) == 2 and "Still there?" in _bells(rig)[1]["body"]
