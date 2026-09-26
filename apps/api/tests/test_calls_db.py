"""WhatsApp calling — every call state, proven against a real Postgres.

Owner, 2026-09-26: the calling experience must never show a wrong state:
"100% of calls clearly show the correct state", "only the first successful
answer connects; all others immediately see that the call was answered",
"every completed / missed / declined call is accurately logged against the
correct customer and conversation", and "information from the call
immediately becomes available to the ongoing customer conversation".

Each test drives the real webhook + routes and checks both the row the Calls
view reads and the live events every agent's screen reacts to. Skips cleanly
without a database (the CI migrations job has one).
"""
import asyncio
import json
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests.test_security_db import _as, _reachable, _sync_url, fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = pytest.mark.skipif(
    not _sync_url() or not _reachable(_sync_url()),
    reason="needs a reachable Postgres (CI migrations job / Docker harness)")


class FakeRedis:
    """What calling uses of redis: set (nx/ex), get, delete, publish."""

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

    async def publish(self, channel, message):
        self.published.append((channel, json.loads(message)))

    def events(self, kind=None):
        return [m for c, m in self.published if c == "ws:channel:calls" and (kind is None or m["type"] == kind)]


@pytest.fixture
def world(fresh_db):  # noqa: F811
    eng = sa.create_engine(fresh_db)
    ids = {"ann": str(uuid.uuid4()), "ben": str(uuid.uuid4())}
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE calls, conversations, agents CASCADE"))
        for key, name in (("ann", "Ann Wanjiru"), ("ben", "Ben Otieno")):
            c.execute(sa.text(
                "INSERT INTO agents (id, name, email, password_hash, role, is_available, "
                "is_superuser, active_convs, created_at) VALUES "
                "(:id, :n, :e, 'x', 'agent', TRUE, FALSE, 0, NOW())"),
                {"id": ids[key], "n": name, "e": f"{key}@x.ke"})
    eng.dispose()
    return ids


@pytest.fixture
def env(fresh_db, monkeypatch):  # noqa: F811
    """The admin router on the fresh database, a fake redis, a fake Meta."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as database
    from app.database import get_db
    from app.routers import admin
    from app.services import call_log, wa_calling, identity

    async_url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)
    monkeypatch.setattr(call_log, "AsyncSessionLocal", maker)

    async def no_person(db, wa_id, source=None):
        return None
    monkeypatch.setattr(identity, "resolve_person_id_for_wa_id", no_person)

    meta = types.SimpleNamespace(sent=[], connect_error=None)

    async def accept(cid, sdp):
        meta.sent.append(("accept", cid))

    async def terminate(cid):
        meta.sent.append(("terminate", cid))

    async def connect(to, sdp):
        if meta.connect_error:
            raise RuntimeError(meta.connect_error)
        meta.sent.append(("connect", to))
        return {"calls": [{"id": f"wacid.out.{to}"}]}

    async def request_perm(to, text=None):
        meta.sent.append(("permission", to))
        return {}

    monkeypatch.setattr(wa_calling, "accept", accept)
    monkeypatch.setattr(wa_calling, "terminate", terminate)
    monkeypatch.setattr(wa_calling, "connect", connect)
    monkeypatch.setattr(wa_calling, "request_call_permission", request_perm)

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
        yield types.SimpleNamespace(client=c, redis=redis, meta=meta, maker=maker, db_url=fresh_db)


def _webhook(env, *calls, contacts=None, field="calls", messages=None):
    """Deliver one WhatsApp webhook payload through the real calls / permission taps."""
    from app.routers import whatsapp_webhook as ww
    value = {"metadata": {"phone_number_id": "PNID"}, "contacts": contacts or []}
    if field == "calls":
        value["calls"] = list(calls)
    else:
        value["messages"] = messages or []
    payload = {"object": "whatsapp_business_account",
               "entry": [{"changes": [{"field": field, "value": value}]}]}
    req = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=env.redis)))
    if field == "calls":
        asyncio.run(ww._handle_calls(req, payload))
    else:
        asyncio.run(ww._tap_call_permission(payload, env.redis))


def _ring(env, cid, frm="254700111222", name="Grace"):
    _webhook(env, {"id": cid, "event": "connect", "from": frm, "to": "254785",
                   "session": {"sdp_type": "offer", "sdp": "v=0 offer"}},
             contacts=[{"wa_id": frm, "profile": {"name": name}}])


def _end(env, cid, duration=None, status="COMPLETED"):
    ev = {"id": cid, "event": "terminate", "status": status}
    if duration is not None:
        ev["duration"] = duration
    _webhook(env, ev)


def _get(env, cid, who):
    r = env.client.get(f"/api/admin/calls/{cid}", headers=_as(who))
    assert r.status_code == 200, r.text
    return r.json()


# ── 1 + 2 + 8: one call, many agents — the first answer wins, everyone knows ──

def test_first_answer_connects_and_every_other_screen_hears_who(env, world):
    _ring(env, "wacid.1")
    ring = env.redis.events("incoming_call")
    assert ring and ring[0]["call_id"] == "wacid.1" and ring[0]["name"] == "Grace"
    # The row lands right after the ring (the ring never waits on the database).
    assert env.redis.events("call_update")[-1]["call"]["status"] == "ringing"

    a = env.client.post("/api/admin/calls/wacid.1/answer", json={"sdp": "v=0 a"}, headers=_as(world["ann"]))
    b = env.client.post("/api/admin/calls/wacid.1/answer", json={"sdp": "v=0 b"}, headers=_as(world["ben"]))
    assert a.status_code == 200
    assert b.status_code == 409 and "Ann Wanjiru" in b.json()["detail"]
    assert [s for s in env.meta.sent if s[0] == "accept"] == [("accept", "wacid.1")]   # Meta accepted once

    answered = env.redis.events("call_answered")
    assert len(answered) == 1 and answered[0]["agent_name"] == "Ann Wanjiru"
    row = _get(env, "wacid.1", world["ben"])
    assert row["status"] == "answered" and row["agent_name"] == "Ann Wanjiru" and row["answered_at"]

    _end(env, "wacid.1", duration=73)
    row = _get(env, "wacid.1", world["ben"])
    assert row["status"] == "completed" and row["duration"] == 73 and not row["follow_up_open"]
    ended = env.redis.events("call_ended")[-1]
    assert ended["outcome"] == "completed" and ended["duration"] == 73 and ended["status"] == "COMPLETED"


# ── 3: an agent declines ─────────────────────────────────────────────────────

def test_a_decline_is_logged_against_the_agent_and_ends_every_ring(env, world):
    _ring(env, "wacid.2")
    r = env.client.post("/api/admin/calls/wacid.2/terminate", json={}, headers=_as(world["ben"]))
    assert r.status_code == 200 and r.json()["outcome"] == "declined"
    ended = env.redis.events("call_ended")[-1]
    assert ended["outcome"] == "declined" and ended["agent_name"] == "Ben Otieno"
    # Meta's own terminate arrives after: the row stays declined, and a screen
    # that missed our event still hears the true outcome.
    _end(env, "wacid.2", status="REJECTED")
    assert _get(env, "wacid.2", world["ann"])["status"] == "declined"
    assert env.redis.events("call_ended")[-1]["outcome"] == "declined"


# ── 4: missed, then followed up ──────────────────────────────────────────────

def test_a_missed_call_is_an_open_follow_up_until_they_are_called_back(env, world):
    _ring(env, "wacid.3", frm="254711000001")
    _end(env, "wacid.3", status="FAILED")
    row = _get(env, "wacid.3", world["ann"])
    assert row["status"] == "missed" and row["follow_up_open"] is True
    follow = env.client.get("/api/admin/calls?view=follow_up", headers=_as(world["ann"])).json()
    assert [c["call_id"] for c in follow] == ["wacid.3"]

    # Ben calls them back and they talk: the missed call is no longer owed.
    r = env.client.post("/api/admin/calls/connect", json={"to": "254711000001", "sdp": "v=0 o"},
                        headers=_as(world["ben"]))
    out = r.json()["call_id"]
    _webhook(env, {"id": out, "event": "connect", "session": {"sdp_type": "answer", "sdp": "v=0 ans"}})
    assert _get(env, "wacid.3", world["ann"])["follow_up_open"] is False
    assert env.client.get("/api/admin/calls?view=follow_up", headers=_as(world["ann"])).json() == []


def test_marking_a_follow_up_done_clears_it(env, world):
    _ring(env, "wacid.4")
    _end(env, "wacid.4")
    assert env.client.post("/api/admin/calls/wacid.4/follow-up-done", headers=_as(world["ann"])).status_code == 200
    row = _get(env, "wacid.4", world["ann"])
    assert row["status"] == "missed" and row["follow_up_open"] is False and row["follow_up_done_at"]
    assert env.redis.events("call_update")[-1]["call"]["follow_up_open"] is False


def test_call_back_later_is_saved_against_the_agent(env, world):
    _ring(env, "wacid.5")
    assert env.client.post("/api/admin/calls/wacid.5/callback", headers=_as(world["ann"])).status_code == 200
    row = _get(env, "wacid.5", world["ben"])
    assert row["status"] == "callback" and row["agent_name"] == "Ann Wanjiru" and row["follow_up_open"]
    assert env.redis.events("call_ended")[-1]["outcome"] == "callback"


# ── 5 + 7 + 14: outbound — answered, unanswered, cancelled ───────────────────

def test_an_outbound_call_keeps_the_agent_who_placed_it(env, world):
    r = env.client.post("/api/admin/calls/connect", json={"to": "+254722000002", "sdp": "v=0 o", "name": "Mary"},
                        headers=_as(world["ann"]))
    cid = r.json()["call_id"]
    row = _get(env, cid, world["ann"])
    assert row["direction"] == "outbound" and row["status"] == "ringing" and row["agent_name"] == "Ann Wanjiru"
    # Nobody else can "answer" our outbound call.
    assert env.client.post(f"/api/admin/calls/{cid}/answer", json={"sdp": "x"},
                           headers=_as(world["ben"])).status_code == 409
    _webhook(env, {"id": cid, "event": "connect", "session": {"sdp_type": "answer", "sdp": "v=0 ans"}})
    assert env.redis.events("outbound_answer")[-1]["sdp"] == "v=0 ans"
    assert env.redis.events("call_answered")[-1]["agent_name"] == "Ann Wanjiru"
    row = _get(env, cid, world["ann"])
    assert row["status"] == "answered" and row["agent_name"] == "Ann Wanjiru"   # not wiped by the webhook


def test_an_outbound_call_nobody_answers_is_no_answer_not_missed(env, world):
    cid = env.client.post("/api/admin/calls/connect", json={"to": "254722000003", "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    _end(env, cid, status="REJECTED")
    row = _get(env, cid, world["ann"])
    assert row["status"] == "no_answer" and row["follow_up_open"] is False
    assert env.redis.events("call_ended")[-1]["outcome"] == "no_answer"


def test_hanging_up_before_they_answer_cancels(env, world):
    cid = env.client.post("/api/admin/calls/connect", json={"to": "254722000004", "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    r = env.client.post(f"/api/admin/calls/{cid}/terminate", json={}, headers=_as(world["ann"]))
    assert r.json()["outcome"] == "cancelled"
    assert _get(env, cid, world["ann"])["status"] == "cancelled"


def test_hanging_up_a_live_call_completes_it(env, world):
    _ring(env, "wacid.6")
    env.client.post("/api/admin/calls/wacid.6/answer", json={"sdp": "v=0"}, headers=_as(world["ann"]))
    r = env.client.post("/api/admin/calls/wacid.6/terminate", json={}, headers=_as(world["ann"]))
    assert r.json()["outcome"] == "completed"
    assert _get(env, "wacid.6", world["ann"])["status"] == "completed"


# ── 6: permission required ───────────────────────────────────────────────────

def test_permission_is_requested_then_granted_by_the_customer(env, world):
    wa = "254733000005"
    assert env.client.get(f"/api/admin/calls/permission?wa_id={wa}", headers=_as(world["ann"])).json()["status"] == "unknown"
    env.meta.connect_error = "WA call connect failed (400): {\"error\":{\"code\":138006}}"
    r = env.client.post("/api/admin/calls/connect", json={"to": wa, "sdp": "v=0"}, headers=_as(world["ann"]))
    assert r.status_code == 409 and "Allow" in r.json()["detail"]
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa}, headers=_as(world["ann"]))
    assert r.status_code == 200 and r.json()["permission"]["status"] == "requested"
    assert env.redis.events("call_permission")[-1]["status"] == "requested"

    exp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    _webhook(env, field="messages", messages=[{
        "from": wa, "type": "interactive",
        "interactive": {"type": "call_permission_reply",
                        "call_permission_reply": {"response": "accept", "expiration_timestamp": exp}}}])
    perm = env.client.get(f"/api/admin/calls/permission?wa_id=+{wa}", headers=_as(world["ann"])).json()
    assert perm["status"] == "granted" and perm["expires_at"]
    ev = env.redis.events("call_permission")[-1]
    assert ev["wa_id"] == wa and ev["status"] == "granted"


def test_a_refused_permission_is_remembered(env, world):
    wa = "254733000006"
    _webhook(env, field="messages", messages=[{
        "from": wa, "type": "interactive",
        "interactive": {"type": "call_permission_reply", "call_permission_reply": {"response": "reject"}}}])
    assert env.client.get(f"/api/admin/calls/permission?wa_id={wa}", headers=_as(world["ann"])).json()["status"] == "denied"


def test_an_unreachable_customer_gets_a_reason_not_a_stack_trace(env, world):
    env.meta.connect_error = "WA call connect failed (400): {\"error\":{\"code\":138001}}"
    r = env.client.post("/api/admin/calls/connect", json={"to": "254733000007", "sdp": "v=0"}, headers=_as(world["ann"]))
    assert r.status_code == 502 and "can't take calls" in r.json()["detail"]


# ── Stale rings never haunt a screen ─────────────────────────────────────────

def test_a_call_whose_end_was_lost_is_closed_and_announced(env, world):
    _ring(env, "wacid.7")
    eng = sa.create_engine(env.db_url)
    with eng.begin() as c:
        c.execute(sa.text("UPDATE calls SET started_at = NOW() - INTERVAL '5 minutes' WHERE call_id = 'wacid.7'"))
    eng.dispose()
    env.client.get("/api/admin/calls", headers=_as(world["ann"]))
    assert _get(env, "wacid.7", world["ann"])["status"] == "missed"
    assert env.redis.events("call_ended")[-1] == {
        "type": "call_ended", "call_id": "wacid.7", "outcome": "missed", "duration": None, "direction": "inbound"}
    # A late answer can't resurrect it, and never reaches Meta.
    r = env.client.post("/api/admin/calls/wacid.7/answer", json={"sdp": "x"}, headers=_as(world["ann"]))
    assert r.status_code == 410 and "already ended" in r.json()["detail"]
    assert ("accept", "wacid.7") not in env.meta.sent
    assert _get(env, "wacid.7", world["ann"])["status"] == "missed"


# ── 19 + 20: the call is part of the conversation ────────────────────────────

def test_the_call_shows_in_the_customers_thread_with_its_brief(env, world):
    wa = "254744000008"
    eng = sa.create_engine(env.db_url)
    conv_id = str(uuid.uuid4())
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO conversations (id, wa_id, channel, external_id, intercept_mode, status, created_at, updated_at) "
            "VALUES (:id, :wa, 'whatsapp', :wa, 'ai', 'open', NOW(), NOW())"), {"id": conv_id, "wa": wa})
    _ring(env, "wacid.8", frm=wa)
    env.client.post("/api/admin/calls/wacid.8/answer", json={"sdp": "v=0"}, headers=_as(world["ann"]))
    _end(env, "wacid.8", duration=125)
    with eng.begin() as c:
        c.execute(sa.text(
            "UPDATE calls SET summary = 'Wants two cassocks, size 52.', transcript_status = 'done', "
            "insights = CAST(:i AS jsonb) WHERE call_id = 'wacid.8'"),
            {"i": json.dumps({"next_action": "Send the price for two cassocks"})})
    eng.dispose()

    # The call row links straight to the chat …
    assert _get(env, "wacid.8", world["ann"])["conversation_id"] == conv_id
    # … and the chat shows the call where it happened.
    thread = env.client.get(f"/api/admin/conversations/{conv_id}/messages", headers=_as(world["ann"])).json()
    calls = [t for t in thread if t.get("event_kind") == "call"]
    assert len(calls) == 1
    item = calls[0]
    assert item["type"] == "system_event" and item["text"] == "Incoming call · 2:05"
    assert item["agent_name"] == "Ann Wanjiru" and item["event_reason"] == "Wants two cassocks, size 52."
    assert item["call"]["insights"]["next_action"] == "Send the price for two cassocks"


def test_an_outbound_call_our_side_could_not_connect_is_failed(env, world):
    cid = env.client.post("/api/admin/calls/connect", json={"to": "254722000009", "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    r = env.client.post(f"/api/admin/calls/{cid}/terminate", json={"reason": "failed"}, headers=_as(world["ann"]))
    assert r.json()["outcome"] == "failed"
    assert _get(env, cid, world["ann"])["status"] == "failed"


def test_a_decline_a_moment_after_a_colleague_answered_never_cuts_them_off(env, world):
    _ring(env, "wacid.9")
    assert env.client.post("/api/admin/calls/wacid.9/answer", json={"sdp": "v=0"},
                           headers=_as(world["ann"])).status_code == 200
    for route in ("terminate", "callback"):
        r = env.client.post(f"/api/admin/calls/wacid.9/{route}", json={}, headers=_as(world["ben"]))
        assert r.status_code == 409 and "Ann Wanjiru" in r.json()["detail"]
    assert ("terminate", "wacid.9") not in env.meta.sent
    assert _get(env, "wacid.9", world["ann"])["status"] == "answered"
    # Ann herself can still hang up.
    assert env.client.post("/api/admin/calls/wacid.9/terminate", json={},
                           headers=_as(world["ann"])).json()["outcome"] == "completed"
