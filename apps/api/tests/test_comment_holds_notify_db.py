"""A COMMENT HANDED TO THE TEAM RINGS THE TEAM (owner, 2026-10-05: "notify on
comments too").

Public-comment hand-offs were only a silent flag: 12 in a week, none answered.
Now the flag is kept AND one `draft_ready` notification goes to every agent
(web + Android ring it) — while the thread stays in AI mode, because muting
Neema on a public thread once left complaints with one apology and silence
(see _route_comment_to_human). A grave complaint still rings once, through
record_escalation, never twice.
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

PSID = "1750000000000001_2290000000000001"
ASK = "How much is the set?"


class _Redis:
    def __init__(self):
        self.published: list = []

    async def publish(self, channel, payload):
        self.published.append((channel, json.loads(payload)))


@pytest.fixture
def rig(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as database
    from app.agent import runtime as rt
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE intercepts, conversations CASCADE"))
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    maker = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                               class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)

    async def conv():
        from app.models.conversation import Conversation
        async with maker() as db:
            c = Conversation(id=uuid.uuid4(), channel="facebook", external_id=PSID)
            db.add(c)
            await db.commit()
            return c.id
    return types.SimpleNamespace(maker=maker, rt=rt, conv_id=asyncio.run(conv()), redis=_Redis())


def _route(rig, **kw):
    asyncio.run(rig.rt._route_comment_to_human("facebook", PSID, ASK, redis=rig.redis, **kw))


def _state(rig):
    async def go():
        from app.models.conversation import Conversation
        from app.models.intercept import Intercept
        async with rig.maker() as db:
            c = await db.get(Conversation, rig.conv_id)
            flags = (await db.execute(sa.select(Intercept).where(
                Intercept.conversation_id == rig.conv_id))).scalars().all()
            return c.intercept_mode.value, flags
    return asyncio.run(go())


def _bells(rig):
    return [p for ch, p in rig.redis.published if ch == "ws:channel:agents:all"
            and p.get("type") == "draft_ready"]


def test_a_comment_handed_to_the_team_rings_the_team_and_neema_stays_on(rig):
    _route(rig, kind="question", severity=0, ask="a price", answered="",
           issues=["they asked for a set; 'Golden Communion Tray' is a tray"])
    mode, flags = _state(rig)
    assert mode == "ai"                                   # Neema not muted on the public thread
    assert len(flags) == 1 and flags[0].action.value == "flag"
    bells = _bells(rig)
    assert len(bells) == 1
    assert bells[0]["conv_id"] == str(rig.conv_id) and bells[0]["wa_id"] == PSID
    assert bells[0]["title"] == "Facebook comment needs you"
    assert bells[0]["body"].startswith("\u201cHow much is the set?\u201d")
    assert "is a tray" in bells[0]["body"] and len(bells[0]["body"]) <= 200
    # no draft card on a public thread
    assert not [p for ch, p in rig.redis.published if p.get("type") == "ai_draft_ready"]


def test_a_grave_complaint_rings_once_through_the_escalation_not_twice(rig, monkeypatch):
    import app.services.conversation as convsvc
    calls = []

    async def fake_escalation(db, conv_id, note, redis=None):
        calls.append(note)
    monkeypatch.setattr(convsvc, "record_escalation", fake_escalation)
    _route(rig, kind="complaint", severity=2)
    assert len(calls) == 1 and _bells(rig) == []


def test_without_redis_the_flag_is_still_kept(rig):
    asyncio.run(rig.rt._route_comment_to_human("facebook", PSID, ASK, kind="question",
                                               severity=0, redis=None))
    mode, flags = _state(rig)
    assert mode == "ai" and len(flags) == 1
