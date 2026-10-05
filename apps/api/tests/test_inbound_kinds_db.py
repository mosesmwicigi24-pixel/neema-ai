"""Cycle 2 end to end on a real Postgres: a webhook message goes through the
native ingest (wa_native → upsert_message), lands with its raw_meta, and the
thread the dashboard reads shows the record — minus the redacted payload copy.

Skips cleanly without a database (the Docker harness / CI migrations job has one).
"""
import asyncio
import json
import types
import uuid

import pytest
import sqlalchemy as sa

from tests.test_security_db import _as, _reachable, _sync_url, fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = pytest.mark.skipif(
    not _sync_url() or not _reachable(_sync_url()),
    reason="needs a reachable Postgres (CI migrations job / Docker harness)")

WA = "254700555001"


class FakeRedis:
    def __init__(self):
        self.store: dict = {}
        self.published: list = []

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)

    async def incr(self, key):
        self.store[key] = int(self.store.get(key) or 0) + 1
        return self.store[key]

    async def expire(self, key, ttl):
        return True

    async def rpush(self, key, value):
        self.store.setdefault(key, []).append(value)

    async def lrange(self, key, a, b):
        return list(self.store.get(key) or [])

    async def publish(self, channel, message):
        self.published.append((channel, json.loads(message)))


@pytest.fixture
def env(fresh_db, monkeypatch):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as database
    from app.database import get_db
    from app.routers import admin

    async_url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)

    turns: list = []

    async def fake_schedule(redis, wa_id, text, dedup, media=None):
        turns.append({"wa_id": wa_id, "text": text, "media": media})
        return True
    monkeypatch.setattr("app.agent.runtime.schedule_reply", fake_schedule)
    monkeypatch.setattr("app.core.config.settings.whatsapp_debounce_seconds", 0, raising=False)

    agent_id = str(uuid.uuid4())
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE messages, conversations, users, persons, agents CASCADE"))
        c.execute(sa.text(
            "INSERT INTO agents (id, name, email, password_hash, role, is_available, "
            "is_superuser, active_convs, created_at) VALUES "
            "(:id, 'Ann Wanjiru', 'ann@x.ke', 'x', 'agent', TRUE, FALSE, 0, NOW())"), {"id": agent_id})
    eng.dispose()

    async def _db():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    redis = FakeRedis()
    app = FastAPI()
    app.include_router(admin.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = _db
    app.state.redis = redis
    with TestClient(app) as c:
        yield types.SimpleNamespace(client=c, redis=redis, maker=maker, db_url=fresh_db,
                                    turns=turns, agent=agent_id)


def _deliver(env, *msgs):
    """One webhook payload through the real native ingest; waits for the
    debounced reply tasks so `env.turns` is final."""
    from app.services import wa_native as wn
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"wa_id": WA, "profile": {"name": "Grace Njeri"}}],
        "messages": [{"from": WA, "timestamp": "1759600000", **m} for m in msgs]}}]}]}

    async def go():
        n, failed = await wn.handle_webhook(payload, env.redis)
        if wn._bg_tasks:
            await asyncio.gather(*list(wn._bg_tasks), return_exceptions=True)
        return n, failed
    return asyncio.run(go())


def _rows(env):
    eng = sa.create_engine(env.db_url)
    with eng.connect() as c:
        rows = c.execute(sa.text(
            "SELECT text, raw_meta, conversation_id, waba_msg_id FROM messages WHERE wa_id = :w "
            "ORDER BY created_at"), {"w": WA}).mappings().all()
    eng.dispose()
    return rows


def _thread(env):
    conv = _rows(env)[0]["conversation_id"]
    r = env.client.get(f"/api/admin/conversations/{conv}/messages", headers=_as(env.agent))
    assert r.status_code == 200, r.text
    return [i for i in r.json() if i["type"] == "message"]


def test_call_permission_reply_lands_with_words_and_record_not_empty(env):
    n, failed = _deliver(env, {"id": "wamid.P1", "type": "interactive", "interactive": {
        "type": "call_permission_reply",
        "call_permission_reply": {"response": "accept", "is_permanent": True}}})
    assert (n, failed) == (1, 0)
    row = _rows(env)[0]
    assert row["text"] == "✅ Allowed WhatsApp calls — permanently"
    assert row["raw_meta"]["kind"] == "call_permission"
    assert env.turns == []                      # never a sales turn


def test_unsupported_keeps_metas_error_in_db_but_not_in_the_thread(env):
    _deliver(env, {"id": "wamid.U1", "type": "unsupported",
                   "unsupported": {"type": "view_once"},
                   "errors": [{"code": 131051, "title": "Message type unknown",
                               "error_data": {"details": "Message type is currently not supported."}}]})
    row = _rows(env)[0]
    assert row["raw_meta"]["errors"][0]["code"] == 131051
    assert row["raw_meta"]["payload"]["type"] == "unsupported"       # kept for the team
    item = _thread(env)[0]
    assert item["meta"]["kind"] == "unsupported" and item["meta"]["subtype"] == "view_once"
    assert "payload" not in item["meta"]                             # never shipped to a browser
    # The agent got a description it can act on — not "resend as text".
    assert env.turns and "view-once" in env.turns[0]["text"] and "resend" not in env.turns[0]["text"]


def test_reaction_resolves_the_message_it_reacts_to(env):
    eng = sa.create_engine(env.db_url)
    _deliver(env, {"id": "wamid.T0", "type": "text", "text": {"body": "hello"}})
    with eng.begin() as c:
        conv = c.execute(sa.text("SELECT conversation_id FROM messages WHERE wa_id=:w"),
                         {"w": WA}).scalar()
        c.execute(sa.text(
            "INSERT INTO messages (id, wa_id, channel, external_id, conversation_id, direction, sender, "
            "text, waba_msg_id, created_at) VALUES (:id, :w, 'whatsapp', :w, :c, 'outbound', 'ai', "
            "'The brass chalice is KES 12,000', 'wamid.OURS', NOW())"),
            {"id": str(uuid.uuid4()), "w": WA, "c": conv})
    eng.dispose()
    env.turns.clear()
    _deliver(env, {"id": "wamid.R1", "type": "reaction",
                   "reaction": {"emoji": "❤️", "message_id": "wamid.OURS"}})
    meta = [r for r in _rows(env) if (r["raw_meta"] or {}).get("kind") == "reaction"][0]["raw_meta"]
    assert meta["to_text"] == "The brass chalice is KES 12,000"
    assert meta["to_sender"] == "ai"
    assert env.turns == []


def test_live_broadcast_carries_id_direction_and_meta(env):
    _deliver(env, {"id": "wamid.L1", "type": "location",
                   "location": {"latitude": -1.28, "longitude": 36.82, "name": "Bethany House"}})
    evs = [m for ch, m in env.redis.published if m.get("type") == "new_message"]
    assert evs, env.redis.published
    ev = evs[-1]
    assert ev["direction"] == "inbound" and ev["id"]
    assert ev["meta"]["kind"] == "location" and ev["meta"]["lat"] == -1.28
    assert "payload" not in ev["meta"]


def test_request_welcome_wakes_the_agent_to_greet(env):
    _deliver(env, {"id": "wamid.W1", "type": "request_welcome"})
    assert _rows(env)[0]["text"] == "👋 Opened a chat with us for the first time"
    assert env.turns and "Greet them" in env.turns[0]["text"]


def test_plain_text_has_no_record_and_replies_as_before(env):
    _deliver(env, {"id": "wamid.X1", "type": "text", "text": {"body": "how much is the alb?"}})
    row = _rows(env)[0]
    assert row["raw_meta"] is None
    assert env.turns and env.turns[0]["text"] == "how much is the alb?"
    assert _thread(env)[0]["meta"] is None
