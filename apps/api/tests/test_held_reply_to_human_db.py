"""A HELD REPLY GOES TO A HUMAN, AND THE TEAM HEARS OF IT (owner, 2026-10-05:
"Move to Human + notify").

When the gate holds both drafts, the customer is told "One of our team will
confirm it right here shortly". Until now the thread was only flagged: it
stayed in AI mode, never reached the Human tab, and no one was told — 55 of
65 such threads in a week had no reply from the team. Pinned here, on a real
Postgres: a held reply moves the thread to HUMAN (the Human tab's own query
finds it), publishes ONE alert the way escalate_to_human does, and keeps the
flag with its reasons and the unsent draft; a second hold on a thread
already with a human does not alert again; a reply that passes leaves the
thread with Neema. What the customer is sent does not change.
"""
import asyncio
import json
import types
import uuid

import pytest
import sqlalchemy as sa

from tests.test_security_db import _reachable, _sync_url, fresh_db  # noqa: F401

pytestmark = pytest.mark.skipif(not _sync_url() or not _reachable(_sync_url()),
                                reason="needs a reachable Postgres (CI migrations job / Docker harness)")

WA = "254700000001"
ASK = "How much is the Silver Communion Tray?"
SILVER = {"name": "Silver Communion Tray", "sku": "843GLV9RC-D69A", "slug": "silver-communion-tray",
          "price": 18000, "price_usd": None, "prices": {}, "category": "Communion Items", "aliases": [],
          "description": "Silver-tone communion tray for 40 cups."}
GOOD = "The Silver Communion Tray is KES 18,000 — 40 cups, lid, holder and basin. How many would you like?"
MADE_UP = "The Silver Communion Tray is KES 16,500 — 40 cups. How many would you like?"


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

    async def publish(self, channel, payload):
        self.published.append((channel, json.loads(payload)))

    async def hincrby(self, *a):
        return 1

    async def expire(self, *a):
        return True


class _Writer:
    def __init__(self, *texts):
        self.texts = list(texts)

    async def complete(self, system, messages, tools=None, **kw):
        return types.SimpleNamespace(text=self.texts.pop(0) if self.texts else "")


@pytest.fixture
def rig(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.agent import review as rv
    from app.agent import runtime as rt

    async def rules_only(*a, **k):
        return None

    async def no_facts(ctx, user_text, tool_log):
        return []
    monkeypatch.setattr(rv, "reviewer_verdict", rules_only)
    monkeypatch.setattr(rt, "_facts_for_ask", no_facts)
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE intercepts, conversations CASCADE"))
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    maker = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                               class_=AsyncSession, expire_on_commit=False)

    async def conv():
        from app.models.conversation import Conversation
        async with maker() as db:
            c = Conversation(id=uuid.uuid4(), wa_id=WA, channel="whatsapp", external_id=WA)
            db.add(c)
            await db.commit()
            return c.id
    return types.SimpleNamespace(maker=maker, rt=rt, conv_id=asyncio.run(conv()), redis=_Redis())


def _turn(rig, draft, *rewrites):
    async def go():
        async with rig.maker() as db:
            ctx = types.SimpleNamespace(seen_products=[SILVER], read_only=False, currency="KES")
            return await rig.rt._gate_turn_reply(
                draft, user_text=ASK, transcript=[{"role": "user", "content": ASK}], tool_log=[],
                ctx=ctx, currency="KES", channel="whatsapp", public_comment=False,
                llm=_Writer(*rewrites), sys_blocks=["SYSTEM"], redis=rig.redis, db=db, key=WA,
                fx=None, closer=False)
    return asyncio.run(go())


def _state(rig):
    async def go():
        from app.models.conversation import Conversation
        from app.models.intercept import Intercept
        from app.routers.admin import _inbox_conditions
        async with rig.maker() as db:
            c = await db.get(Conversation, rig.conv_id)
            human_tab = (await db.execute(sa.select(Conversation.id).where(
                *_inbox_conditions(agent_id=None, tab="human")))).scalars().all()
            flags = (await db.execute(sa.select(Intercept).where(
                Intercept.conversation_id == rig.conv_id).order_by(Intercept.created_at))).scalars().all()
            return c.intercept_mode.value, list(human_tab), flags
    return asyncio.run(go())


def _alerts(rig):
    return [p for ch, p in rig.redis.published if ch == "ws:channel:agents:all"]


def test_a_held_reply_goes_to_a_human_and_the_team_is_alerted_once(rig):
    reply, held, outcome = _turn(rig, MADE_UP, MADE_UP)
    # the customer is sent exactly what they were sent before
    assert outcome == "held" and reply == rig.rt._REVIEW_HOLD_DM_PRICE
    mode, human_tab, flags = _state(rig)
    assert mode == "human" and rig.conv_id in human_tab
    assert len(flags) == 1 and flags[0].action.value == "flag"
    assert "HELD BACK BY THE REVIEWER" in flags[0].note and "unverified figure(s) 16,500" in flags[0].note
    assert flags[0].ai_reply_held == MADE_UP
    alerts = _alerts(rig)
    assert len(alerts) == 1
    a = alerts[0]
    assert a["event"] == "notification" and a["type"] == "draft_ready"
    assert a["conv_id"] == str(rig.conv_id) and a["wa_id"] == WA
    assert "unverified figure(s) 16,500" in a["body"]
    draft_cards = [p for ch, p in rig.redis.published if ch == f"ws:channel:{rig.conv_id}"]
    assert draft_cards == [{"type": "ai_draft_ready", "conversationId": str(rig.conv_id),
                            "waId": WA, "draft": MADE_UP}]
    # a second hold on the thread now with a human: flagged again, NOT alerted again
    _turn(rig, MADE_UP, MADE_UP)
    mode, _tab, flags = _state(rig)
    assert mode == "human" and len(flags) == 2
    assert len(_alerts(rig)) == 1


def test_a_reply_that_passes_or_is_rewritten_stays_with_neema(rig):
    assert _turn(rig, GOOD) == (GOOD, [], "pass")
    assert _turn(rig, MADE_UP, GOOD) == (GOOD, [], "rewritten")
    mode, human_tab, flags = _state(rig)
    assert mode == "ai" and rig.conv_id not in human_tab and flags == []
    assert rig.redis.published == []
