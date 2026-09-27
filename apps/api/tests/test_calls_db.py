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
    ids = {"ann": str(uuid.uuid4()), "ben": str(uuid.uuid4()), "boss": str(uuid.uuid4())}
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE calls, conversations, agents CASCADE"))
        for key, name, role in (("ann", "Ann Wanjiru", "agent"), ("ben", "Ben Otieno", "agent"),
                                ("boss", "Bea Admin", "admin")):
            c.execute(sa.text(
                "INSERT INTO agents (id, name, email, password_hash, role, is_available, "
                "is_superuser, active_convs, created_at) VALUES "
                "(:id, :n, :e, 'x', :r, TRUE, FALSE, 0, NOW())"),
                {"id": ids[key], "n": name, "e": f"{key}@x.ke", "r": role})
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

    meta = types.SimpleNamespace(sent=[], connect_error=None, perm=None, perm_error=None,
                                 request_error=None, opaque={})

    async def accept(cid, sdp, **kw):
        meta.sent.append(("accept", cid))
        meta.opaque[cid] = kw.get("biz_opaque")

    async def terminate(cid):
        meta.sent.append(("terminate", cid))

    async def connect(to, sdp, **kw):
        if meta.connect_error:
            raise RuntimeError(meta.connect_error)
        meta.sent.append(("connect", to))
        meta.opaque[f"wacid.out.{to}"] = kw.get("biz_opaque")
        return {"calls": [{"id": f"wacid.out.{to}"}]}

    async def request_perm(to, text=None):
        if meta.request_error:
            raise meta.request_error
        meta.sent.append(("permission", to))
        return {}

    async def request_perm_template(to, name, lang, params):
        if meta.request_error:
            raise meta.request_error
        meta.sent.append(("permission_template", to, name, lang, tuple(params)))
        return {}

    async def get_perm(wa_id):
        meta.sent.append(("get_permission", wa_id))
        if meta.perm_error:
            raise meta.perm_error
        if meta.perm is None:
            raise wa_calling.MetaError("WABA not configured — cannot read call permission")
        return wa_calling.normalize_permission(meta.perm)

    monkeypatch.setattr(wa_calling, "accept", accept)
    monkeypatch.setattr(wa_calling, "terminate", terminate)
    monkeypatch.setattr(wa_calling, "connect", connect)
    monkeypatch.setattr(wa_calling, "request_call_permission", request_perm)
    monkeypatch.setattr(wa_calling, "request_call_permission_template", request_perm_template)
    monkeypatch.setattr(wa_calling, "get_call_permission", get_perm)

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


def _inbound_message(env, wa, *, hours_ago=1, name="Grace Njeri"):
    """The customer wrote to us on WhatsApp `hours_ago` hours ago."""
    eng = sa.create_engine(env.db_url)
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO messages (id, name, wa_id, channel, external_id, direction, sender, text, created_at) "
            "VALUES (:id, :n, :wa, 'whatsapp', :wa, 'inbound', 'user', 'hi', NOW() - make_interval(hours => :h))"),
            {"id": str(uuid.uuid4()), "n": name, "wa": wa, "h": hours_ago})
    eng.dispose()


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
    _inbound_message(env, wa)                     # they wrote today: inside the 24 h window
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


# ── Meta doesn't promise order: events that beat the row they belong to ──────

async def _webhook_async(env, *calls):
    """[_webhook] from inside a running request (a fake Meta call)."""
    from app.routers import whatsapp_webhook as ww
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "calls", "value": {
        "metadata": {"phone_number_id": "PNID"}, "contacts": [], "calls": list(calls)}}]}]}
    req = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=env.redis)))
    await ww._handle_calls(req, payload)


def test_a_terminate_that_beats_its_connect_never_rings_a_phone(env, world):
    _end(env, "wacid.10", status="FAILED")        # the caller gave up at once …
    _ring(env, "wacid.10")                          # … and the connect limps in after
    assert env.redis.events("incoming_call") == []
    assert _get(env, "wacid.10", world["ann"])["status"] == "missed"
    assert env.redis.events("call_ended")[-1]["outcome"] == "missed"


def test_a_redelivered_connect_for_a_logged_call_never_rings_again(env, world):
    _ring(env, "wacid.11")
    _end(env, "wacid.11")
    env.redis.store.pop("wa:call:wacid.11:connect", None)   # the dedup key expired
    _ring(env, "wacid.11")
    assert len(env.redis.events("incoming_call")) == 1
    assert _get(env, "wacid.11", world["ann"])["status"] == "missed"


def test_an_answer_that_beats_the_outbound_row_still_marks_it_answered(env, world, monkeypatch):
    from app.services import wa_calling

    async def connect(to, sdp, **kw):
        cid = f"wacid.out.{to}"
        await _webhook_async(env, {"id": cid, "event": "connect",
                                   "session": {"sdp_type": "answer", "sdp": "v=0 ans"}})
        return {"calls": [{"id": cid}]}
    monkeypatch.setattr(wa_calling, "connect", connect)
    cid = env.client.post("/api/admin/calls/connect", json={"to": "254722000010", "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    row = _get(env, cid, world["ann"])
    assert row["status"] == "answered" and row["agent_name"] == "Ann Wanjiru"
    assert env.redis.events("call_answered")[-1]["agent_name"] == "Ann Wanjiru"
    _end(env, cid, duration=30)
    assert _get(env, cid, world["ann"])["status"] == "completed"


def test_a_terminate_that_beats_the_outbound_row_closes_it(env, world, monkeypatch):
    from app.services import wa_calling

    async def connect(to, sdp, **kw):
        cid = f"wacid.out.{to}"
        await _webhook_async(env, {"id": cid, "event": "terminate", "status": "REJECTED"})
        return {"calls": [{"id": cid}]}
    monkeypatch.setattr(wa_calling, "connect", connect)
    cid = env.client.post("/api/admin/calls/connect", json={"to": "254722000011", "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    assert _get(env, cid, world["ann"])["status"] == "no_answer"
    assert env.redis.events("call_ended")[-1]["outcome"] == "no_answer"


def test_the_stale_sweep_never_touches_a_live_call_and_runs_on_a_polled_row(env, world):
    _ring(env, "wacid.12")
    env.client.post("/api/admin/calls/wacid.12/answer", json={"sdp": "v=0"}, headers=_as(world["ann"]))
    _ring(env, "wacid.13", frm="254700111333")
    eng = sa.create_engine(env.db_url)
    with eng.begin() as c:
        c.execute(sa.text("UPDATE calls SET started_at = NOW() - INTERVAL '5 minutes' "
                          "WHERE call_id IN ('wacid.12', 'wacid.13')"))
    eng.dispose()
    # A phone polling only its own row still learns the ring is over.
    assert _get(env, "wacid.13", world["ben"])["status"] == "missed"
    assert _get(env, "wacid.12", world["ann"])["status"] == "answered"


# ═════════════════════════════════════════════════════════════════════════════
# 2026-09-27 platform refresh (docs/research/NEEMA_CALLING_GAPS.md)
# ═════════════════════════════════════════════════════════════════════════════

def _perm_get(env, wa, who):
    r = env.client.get(f"/api/admin/calls/permission?wa_id={wa}", headers=_as(who))
    assert r.status_code == 200, r.text
    return r.json()


def _meta_perm(status="temporary", *, exp_key="expiration_time", exp=None, can_request=True,
               can_call=True, req_limits=None, call_limits=None):
    perm = {"status": status}
    if status == "temporary":
        perm[exp_key] = exp or int((datetime.now(timezone.utc) + timedelta(days=5)).timestamp())
    return {"messaging_product": "whatsapp", "permission": perm, "actions": [
        {"action_name": "send_call_permission_request", "can_perform_action": can_request,
         "limits": req_limits or [{"time_period": "PT24H", "max_allowed": 1, "current_usage": 0}]},
        {"action_name": "start_call", "can_perform_action": can_call,
         "limits": call_limits or [{"time_period": "PT24H", "max_allowed": 100, "current_usage": 3}]}]}


def _meta_calls(env):
    return [s for s in env.meta.sent if s[0] == "get_permission"]


# ── C1 permission truth ──────────────────────────────────────────────────────

def test_permission_is_metas_answer_cached_briefly(env, world):
    wa = "254755000001"
    env.meta.perm = _meta_perm("temporary")
    p = _perm_get(env, wa, world["ann"])
    assert p["status"] == "granted" and p["meta_status"] == "temporary" and p["source"] == "meta"
    assert p["can_call"] is True and p["expires_at"] and p["permanent"] is False
    assert p["calls_left_today"] == 97 and p["unanswered_streak"] == 0
    # Two more reads inside the cache window never reach Meta again.
    _perm_get(env, wa, world["ann"])
    _perm_get(env, wa, world["ben"])
    assert len(_meta_calls(env)) == 1


def test_permission_accepts_both_expiry_spellings_and_permanent(env, world):
    exp = int((datetime.now(timezone.utc) + timedelta(days=3)).timestamp())
    env.meta.perm = _meta_perm("temporary", exp_key="expiration", exp=exp)
    p = _perm_get(env, "254755000002", world["ann"])
    assert p["status"] == "granted" and p["expires_at"].startswith(
        datetime.fromtimestamp(exp, tz=timezone.utc).date().isoformat())
    env.meta.perm = _meta_perm("permanent")
    p = _perm_get(env, "254755000003", world["ann"])
    assert p["status"] == "granted" and p["permanent"] is True and p["expires_at"] is None
    # An expiry already in the past is no permission, whatever the status says.
    env.meta.perm = _meta_perm("temporary", exp=int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()))
    p = _perm_get(env, "254755000004", world["ann"])
    assert p["status"] == "unknown" and p["meta_status"] == "no_permission"


def test_a_profile_grant_beats_our_old_denied_record(env, world):
    wa = "254755000005"
    _webhook(env, field="messages", messages=[{
        "from": wa, "type": "interactive",
        "interactive": {"type": "call_permission_reply", "call_permission_reply": {"response": "reject"}}}])
    env.meta.perm = _meta_perm("permanent")
    assert _perm_get(env, wa, world["ann"])["status"] == "granted"


def test_no_permission_at_meta_merges_what_we_asked_and_what_they_said(env, world):
    wa = "254755000006"
    env.meta.perm = _meta_perm("no_permission", can_call=False)
    assert _perm_get(env, wa, world["ann"])["status"] == "unknown"
    _inbound_message(env, wa)
    assert env.client.post("/api/admin/calls/request-permission", json={"to": wa},
                           headers=_as(world["ann"])).status_code == 200
    # Our request dropped the cached answer; Meta still says no_permission.
    p = _perm_get(env, wa, world["ann"])
    assert p["status"] == "requested" and p["source"] == "meta" and p["can_call"] is False
    # A request older than 7 days has expired at Meta: no longer "requested".
    raw = json.loads(env.redis.store[f"wa:call:perm:{wa}"])
    raw["at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    env.redis.store[f"wa:call:perm:{wa}"] = json.dumps(raw)
    env.redis.store.pop(f"wa:call:permmeta:{wa}", None)
    assert _perm_get(env, wa, world["ann"])["status"] == "unknown"


@pytest.mark.parametrize("err", [
    "WA call-permission read failed (429): {\"error\":{\"code\":613}}",
    "WA call-permission read failed (503): upstream",
    "WA call-permission read failed (network): timed out",
    "WA call-permission read failed (401): {\"error\":{\"type\":\"OAuthException\",\"code\":190}}",
])
def test_meta_down_falls_back_to_our_store_with_a_short_negative_cache(env, world, err):
    from app.services import wa_calling
    wa = "254755000007"
    _webhook(env, field="messages", messages=[{
        "from": wa, "type": "interactive",
        "interactive": {"type": "call_permission_reply",
                        "call_permission_reply": {"response": "accept", "is_permanent": True}}}])
    env.meta.perm_error = wa_calling.MetaError(err)
    p = _perm_get(env, wa, world["ann"])
    assert p["status"] == "granted" and p["permanent"] is True and p["source"] == "store"
    assert p["can_call"] is True and p["meta_status"] is None
    _perm_get(env, wa, world["ann"])                      # negative cache: Meta not asked again
    assert len(_meta_calls(env)) == 1
    env.redis.store.pop(f"wa:call:permmeta:fail:{wa}")    # the short negative cache expires …
    env.meta.perm_error, env.meta.perm = None, _meta_perm("permanent")
    assert _perm_get(env, wa, world["ann"])["source"] == "meta"   # … and Meta is the truth again


def test_request_limits_say_when_asking_works_again(env, world):
    wa = "254755000008"
    until = int((datetime.now(timezone.utc) + timedelta(hours=20)).timestamp())
    week = int((datetime.now(timezone.utc) + timedelta(days=4)).timestamp())
    env.meta.perm = _meta_perm("no_permission", can_request=False, can_call=False, req_limits=[
        {"time_period": "PT24H", "max_allowed": 1, "current_usage": 1, "limit_expiration_time": until},
        {"time_period": "P7D", "max_allowed": 2, "current_usage": 2, "limit_expiration_time": week}])
    p = _perm_get(env, wa, world["ann"])
    assert p["can_request"] is False
    assert p["request_available_at"] == datetime.fromtimestamp(week, tz=timezone.utc).isoformat()
    # The cached answer already says no: the request is refused without asking Meta.
    _inbound_message(env, wa)
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa}, headers=_as(world["ann"]))
    assert r.status_code == 409 and r.json()["code"] == "138009" and r.json()["action"] == "wait"
    assert r.json()["request_available_at"] and isinstance(r.json()["detail"], str)
    assert not [s for s in env.meta.sent if s[0].startswith("permission")]


def test_a_reply_and_a_connected_call_drop_the_cached_answer(env, world):
    wa = "254755000009"
    env.meta.perm = _meta_perm("no_permission", can_call=False)
    _perm_get(env, wa, world["ann"])
    assert f"wa:call:permmeta:{wa}" in env.redis.store
    _webhook(env, field="messages", messages=[{
        "from": wa, "type": "interactive",
        "interactive": {"type": "call_permission_reply", "call_permission_reply": {"response": "accept"}}}])
    assert f"wa:call:permmeta:{wa}" not in env.redis.store
    env.meta.perm = _meta_perm("temporary")
    _perm_get(env, wa, world["ann"])
    cid = env.client.post("/api/admin/calls/connect", json={"to": wa, "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    _webhook(env, {"id": cid, "event": "connect", "session": {"sdp_type": "answer", "sdp": "a"}})
    assert f"wa:call:permmeta:{wa}" not in env.redis.store


def test_request_meets_an_existing_permanent_permission(env, world):
    from app.services import wa_calling
    wa = "254755000010"
    _inbound_message(env, wa)
    env.meta.request_error = wa_calling.MetaError(
        'WA call-permission request failed (400): {"error":{"code":138017}}', status=400, code=138017)
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa}, headers=_as(world["ann"]))
    assert r.status_code == 200 and r.json()["already_permitted"] is True
    assert r.json()["permission"]["status"] == "granted" and r.json()["permission"]["permanent"] is True
    assert env.redis.events("call_permission")[-1]["status"] == "granted"


def test_request_over_the_limit_says_when_from_metas_counters(env, world):
    from app.services import wa_calling
    wa = "254755000011"
    _inbound_message(env, wa)
    env.meta.request_error = wa_calling.MetaError(
        'WA call-permission request failed (400): {"error":{"code":138009}}', status=400, code=138009)
    when = int((datetime.now(timezone.utc) + timedelta(hours=9)).timestamp())
    env.meta.perm = _meta_perm("no_permission", can_request=False, req_limits=[
        {"time_period": "PT24H", "max_allowed": 1, "current_usage": 1, "limit_expiration_time": when}])
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa}, headers=_as(world["ann"]))
    body = r.json()
    assert r.status_code == 409 and body["code"] == "138009" and body["action"] == "wait"
    assert body["request_available_at"] == datetime.fromtimestamp(when, tz=timezone.utc).isoformat()
    assert r.headers["X-Neema-Reason"] == "138009"
    # Nothing was recorded as "requested": no request went out.
    assert f"wa:call:perm:{wa}" not in env.redis.store


def test_request_with_an_expired_token_tells_the_agent_an_admin_must_act(env, world):
    from app.services import wa_calling
    wa = "254755000012"
    _inbound_message(env, wa)
    env.meta.request_error = wa_calling.MetaError(
        'WA call-permission request failed (401): {"error":{"message":"Error validating access token: '
        'Session has expired","type":"OAuthException","code":190}}', status=401, code=190)
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa}, headers=_as(world["ann"]))
    assert r.status_code == 502 and r.json()["code"] == "190" and r.json()["action"] == "admin"
    assert "access token expired" in r.json()["detail"]


# ── C2 template outside the 24 h window ──────────────────────────────────────

def test_outside_the_window_without_a_template_is_a_clear_409(env, world):
    wa = "254766000001"
    _inbound_message(env, wa, hours_ago=30, name="Grace Njeri")
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa}, headers=_as(world["ann"]))
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "template_required" and r.headers["X-Neema-Reason"] == "template_required"
    assert body["detail"].startswith("Grace hasn't messaged in 24 hours") and "Settings" in body["detail"]
    assert not [s for s in env.meta.sent if s[0].startswith("permission")]


def test_outside_the_window_the_template_carries_their_first_name(env, world, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "call_permission_template", "call_ok", raising=False)
    monkeypatch.setattr(settings, "call_permission_template_lang", "en_US", raising=False)
    wa = "254766000002"
    _inbound_message(env, wa, hours_ago=48, name="Grace Njeri")
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa}, headers=_as(world["ann"]))
    assert r.status_code == 200 and r.json()["route"] == "template"
    assert env.meta.sent[-1] == ("permission_template", wa, "call_ok", "en_US", ("Grace",))
    # A template without body variables: no parameters at all. (Another
    # customer: WhatsApp allows one request a day, so a second to Grace is a 409.)
    monkeypatch.setattr(settings, "call_permission_template_params", "", raising=False)
    wa2 = "254766000012"
    _inbound_message(env, wa2, hours_ago=48, name="Mary Atieno")
    env.client.post("/api/admin/calls/request-permission", json={"to": wa2, "name": "Mary"},
                    headers=_as(world["ann"]))
    assert env.meta.sent[-1][-1] == ()


def test_an_inbound_call_opens_the_window_even_unanswered(env, world):
    wa = "254766000003"
    _inbound_message(env, wa, hours_ago=40)
    _ring(env, "wacid.win.1", frm=wa)
    _end(env, "wacid.win.1", status="FAILED")          # missed — still opens the window
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa}, headers=_as(world["ann"]))
    assert r.status_code == 200 and r.json()["route"] == "free_form"
    # Our own outbound calls never open it.
    wa2 = "254766000004"
    env.client.post("/api/admin/calls/connect", json={"to": wa2, "sdp": "v=0"}, headers=_as(world["ann"]))
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa2}, headers=_as(world["ann"]))
    assert r.status_code == 409 and r.json()["code"] == "template_required"


def test_template_admin_needs_manage_settings_and_creates_exactly_the_documented_shape(env, world, monkeypatch):
    from app.core.config import settings
    from app.services import wa_calling
    monkeypatch.setattr(settings, "waba_business_account_id", "WABA1", raising=False)
    monkeypatch.setattr(settings, "waba_token", "T", raising=False)
    sent = []

    async def fake_send(method, url, what, *, json_body=None, params=None, retry=False):
        sent.append((method, url, json_body, params))
        if method == "POST":
            return {"id": "tpl1", "status": "PENDING", "category": "UTILITY"}
        return {"data": [{"name": "neema_call_permission", "language": "en", "status": "APPROVED",
                          "category": "UTILITY"}]}
    monkeypatch.setattr(wa_calling, "_send", fake_send)

    assert env.client.get("/api/admin/calls/permission-template", headers=_as(world["ann"])).status_code == 403
    assert env.client.post("/api/admin/calls/permission-template", json={},
                           headers=_as(world["ann"])).status_code == 403
    g = env.client.get("/api/admin/calls/permission-template", headers=_as(world["boss"])).json()
    assert g["configured"] is False and g["exists"] is None

    bad = env.client.post("/api/admin/calls/permission-template", json={"body_text": "Hi {{1}} {{2}}"},
                          headers=_as(world["boss"]))
    assert bad.status_code == 400
    r = env.client.post("/api/admin/calls/permission-template", json={}, headers=_as(world["boss"]))
    assert r.status_code == 200 and r.json()["status"] == "pending"
    method, url, payload, _ = sent[-1]
    assert method == "POST" and url.endswith("/WABA1/message_templates") and "/v23.0/" in url
    assert payload["category"] == "UTILITY" and payload["language"] == "en"
    assert payload["components"][0]["type"] == "BODY" and payload["components"][0]["text"].count("{{1}}") == 1
    assert payload["components"][0]["example"] == {"body_text": [["Grace"]]}
    assert payload["components"][1] == {"type": "call_permission_request"}

    g = env.client.get("/api/admin/calls/permission-template", headers=_as(world["boss"])).json()
    assert g == {**g, "configured": True, "source": "app", "exists": True, "status": "approved"}
    assert sent[-1][3] == {"name": "neema_call_permission"}

    # The template the admin created is what outside-window requests now use.
    wa = "254766000005"
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa, "name": "Peter Kamau"},
                        headers=_as(world["ann"]))
    assert r.status_code == 200 and r.json()["route"] == "template"
    assert env.meta.sent[-1] == ("permission_template", wa, "neema_call_permission", "en", ("Peter",))


def test_template_status_degrades_when_meta_is_down(env, world, monkeypatch):
    from app.core.config import settings
    from app.services import wa_calling
    monkeypatch.setattr(settings, "waba_business_account_id", "WABA1", raising=False)
    monkeypatch.setattr(settings, "call_permission_template", "call_ok", raising=False)

    async def down(*a, **k):
        raise wa_calling.MetaError("WA template read failed (500): oops", status=500)
    monkeypatch.setattr(wa_calling, "find_template", down)
    g = env.client.get("/api/admin/calls/permission-template", headers=_as(world["boss"])).json()
    assert g["configured"] is True and g["exists"] is None and g["error"]["action"] == "retry"


# ── C3 calling settings ──────────────────────────────────────────────────────

def _settings_meta(monkeypatch, current, *, read_error=None):
    from app.services import wa_calling
    box = types.SimpleNamespace(sent=[], reads=0, current=current)

    async def get_settings():
        box.reads += 1
        if read_error:
            raise read_error
        return box.current

    async def update_settings(calling):
        box.sent.append(calling)
        return {"success": True}
    monkeypatch.setattr(wa_calling, "get_settings", get_settings)
    monkeypatch.setattr(wa_calling, "update_settings", update_settings)
    return box


CURRENT_CALLING = {
    "status": "ENABLED", "call_icon_visibility": "DEFAULT", "callback_permission_status": "DISABLED",
    "call_hours": {"status": "ENABLED", "timezone_id": "Africa/Nairobi",
                   "weekly_operating_hours": [{"day_of_week": "MONDAY", "open_time": "0800", "close_time": "1700"}],
                   "holiday_schedule": [{"date": "2026-12-25", "open_time": "0000", "close_time": "2359"}]},
    "voicemail": {"status": "DISABLED", "triggers": ["TIMEOUT"], "timeout_seconds": 20,
                  "audio": {"default": {"announcement_media_id": "m1"}}},
    "restrictions": {"restrictions_list": [{"type": "RESTRICTED_BUSINESS_INITIATED_CALLING",
                                            "expiration": 1790000000}]},
}


def test_calling_settings_read_is_admin_only_and_shows_restrictions(env, world, monkeypatch):
    _settings_meta(monkeypatch, CURRENT_CALLING)
    assert env.client.get("/api/admin/calls/settings", headers=_as(world["ann"])).status_code == 403
    s = env.client.get("/api/admin/calls/settings", headers=_as(world["boss"])).json()
    assert s["status"] == "ENABLED" and s["callback_permission_status"] == "DISABLED"
    assert s["call_hours"]["holiday_schedule"] == [{"date": "2026-12-25", "start_time": "0000", "end_time": "2359"}]
    assert s["voicemail"] == {"status": "DISABLED", "triggers": ["TIMEOUT"], "timeout_seconds": 20}
    assert s["restrictions"][0]["type"] == "RESTRICTED_BUSINESS_INITIATED_CALLING"


def test_changing_one_setting_sends_only_that_field(env, world, monkeypatch):
    box = _settings_meta(monkeypatch, CURRENT_CALLING)
    r = env.client.post("/api/admin/calls/settings", json={"callback_permission_status": "enabled"},
                        headers=_as(world["boss"]))
    assert r.status_code == 200 and box.sent == [{"callback_permission_status": "ENABLED"}]


def test_changing_hours_never_wipes_the_holiday_schedule(env, world, monkeypatch):
    box = _settings_meta(monkeypatch, CURRENT_CALLING)
    r = env.client.post("/api/admin/calls/settings", json={"call_hours": {"weekly_operating_hours": [
        {"day_of_week": "TUESDAY", "open_time": "0900", "close_time": "1800"}]}}, headers=_as(world["boss"]))
    assert r.status_code == 200
    sent = box.sent[-1]["call_hours"]
    assert sent["holiday_schedule"] == [{"date": "2026-12-25", "start_time": "0000", "end_time": "2359"}]
    assert sent["weekly_operating_hours"][0]["day_of_week"] == "TUESDAY" and sent["timezone_id"] == "Africa/Nairobi"
    assert "restrictions" not in box.sent[-1]
    # Voicemail merges too: the announcement Meta holds is re-sent, not dropped.
    env.client.post("/api/admin/calls/settings", json={"voicemail": {"status": "ENABLED", "timeout_seconds": 10}},
                    headers=_as(world["boss"]))
    vm = box.sent[-1]["voicemail"]
    assert vm["status"] == "ENABLED" and vm["timeout_seconds"] == 10
    assert vm["audio"] == {"default": {"announcement_media_id": "m1"}}


def test_hours_are_not_written_blind_when_meta_cant_be_read(env, world, monkeypatch):
    from app.services import wa_calling
    box = _settings_meta(monkeypatch, CURRENT_CALLING,
                         read_error=wa_calling.MetaError("WA settings read failed (503): x", status=503))
    r = env.client.post("/api/admin/calls/settings", json={"call_hours": {"status": "DISABLED"}},
                        headers=_as(world["boss"]))
    assert r.status_code == 503 and r.json()["action"] == "retry" and box.sent == []
    for bad in ({"status": "ON"}, {"voicemail": {"timeout_seconds": 31}},
                {"voicemail": {"triggers": ["HANGUP"]}}, {}):
        assert env.client.post("/api/admin/calls/settings", json=bad,
                               headers=_as(world["boss"])).status_code == 400
    assert box.sent == []


def test_calling_restrictions_and_settings_changes_reach_every_agent(env, world, monkeypatch):
    from app.routers import whatsapp_webhook as ww
    _settings_meta(monkeypatch, CURRENT_CALLING)

    def deliver(field, value):
        asyncio.run(ww._tap_account_updates({"object": "whatsapp_business_account", "entry": [
            {"changes": [{"field": field, "value": value}]}]}, env.redis))
    deliver("account_update", {"event": "ACCOUNT_UPDATE", "ban_info": {"x": 1}})      # unrelated
    assert env.redis.events("calling_restricted") == []
    deliver("account_update", {"event": "ACCOUNT_VIOLATION",
                               "violation_info": {"violation_type": "LOW_BUSINESS_INITIATED_CALLING_QUALITY"}})
    ev = env.redis.events("calling_restricted")[-1]
    assert ev["event"] == "ACCOUNT_VIOLATION" and ev["reasons"] == ["LOW_BUSINESS_INITIATED_CALLING_QUALITY"]
    deliver("account_settings_update", {"phone_number_id": "PNID", "calling": {"status": "DISABLED"}})
    assert env.redis.events("call_settings")[-1]["value"]["calling"]["status"] == "DISABLED"
    s = env.client.get("/api/admin/calls/settings", headers=_as(world["boss"])).json()
    assert s["last_restriction_event"]["event"] == "ACCOUNT_VIOLATION"
    assert s["last_settings_event"]["type"] == "call_settings"


# ── C4 business-initiated call statuses + opaque data + unanswered streak ────

def _status(env, cid, status, **extra):
    from app.routers import whatsapp_webhook as ww
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "calls", "value": {
        "metadata": {"phone_number_id": "PNID"},
        "statuses": [{"id": cid, "type": "call", "status": status, "timestamp": "1", **extra}]}}]}]}
    req = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=env.redis)))
    asyncio.run(ww._handle_calls(req, payload))


def test_ringing_then_rejected_is_told_at_once_and_logged_rejected(env, world):
    cid = env.client.post("/api/admin/calls/connect", json={"to": "254777000001", "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    _status(env, cid, "RINGING")
    _status(env, cid, "RINGING")                     # a Meta retry: told once
    assert env.redis.events("call_status") == [{"type": "call_status", "call_id": cid, "status": "ringing"}]
    _status(env, cid, "REJECTED")
    row = _get(env, cid, world["ann"])
    assert row["status"] == "rejected" and row["agent_name"] == "Ann Wanjiru" and not row["follow_up_open"]
    ended = env.redis.events("call_ended")[-1]
    assert ended["outcome"] == "rejected" and ended["status"] == "REJECTED"
    _end(env, cid)                                   # Meta's terminate follows: still rejected
    assert _get(env, cid, world["ann"])["status"] == "rejected"
    assert env.redis.events("call_ended")[-1]["outcome"] == "rejected"


def test_accepted_status_is_idempotent_audit_only(env, world):
    cid = env.client.post("/api/admin/calls/connect", json={"to": "254777000002", "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    _webhook(env, {"id": cid, "event": "connect", "session": {"sdp_type": "answer", "sdp": "a"}})
    before = list(env.redis.published)
    _status(env, cid, "ACCEPTED")
    _status(env, cid, "ACCEPTED")
    assert env.redis.published == before and _get(env, cid, world["ann"])["status"] == "answered"


def test_a_terminate_that_beat_the_rejected_status_is_corrected(env, world):
    cid = env.client.post("/api/admin/calls/connect", json={"to": "254777000003", "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    _end(env, cid)
    assert _get(env, cid, world["ann"])["status"] == "no_answer"
    _status(env, cid, "REJECTED")
    assert _get(env, cid, world["ann"])["status"] == "rejected"


def test_connect_and_accept_carry_our_opaque_data(env, world):
    wa = "254777000004"
    eng = sa.create_engine(env.db_url)
    conv_id = str(uuid.uuid4())
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO conversations (id, wa_id, channel, external_id, intercept_mode, status, created_at, updated_at) "
            "VALUES (:id, :wa, 'whatsapp', :wa, 'ai', 'open', NOW(), NOW())"), {"id": conv_id, "wa": wa})
    eng.dispose()
    cid = env.client.post("/api/admin/calls/connect", json={"to": wa, "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    assert json.loads(env.meta.opaque[cid]) == {"a": world["ann"], "c": conv_id}
    assert len(env.meta.opaque[cid]) <= 512
    _ring(env, "wacid.op.1", frm=wa)
    env.client.post("/api/admin/calls/wacid.op.1/answer", json={"sdp": "v=0"}, headers=_as(world["ben"]))
    assert json.loads(env.meta.opaque["wacid.op.1"]) == {"a": world["ben"], "c": conv_id}


def test_a_status_that_beats_our_row_writes_it_from_the_opaque_data(env, world, monkeypatch):
    from app.services import wa_calling

    async def connect(to, sdp, **kw):
        cid = f"wacid.out.{to}"
        # Meta rings the customer before /calls/connect has its answer back.
        await _webhook_async_status(env, cid, "RINGING", biz_opaque_callback_data=kw["biz_opaque"],
                                    recipient_id=to)
        return {"calls": [{"id": cid}]}
    monkeypatch.setattr(wa_calling, "connect", connect)
    r = env.client.post("/api/admin/calls/connect", json={"to": "254777000005", "sdp": "v=0", "name": "Mary"},
                        headers=_as(world["ann"]))
    cid = r.json()["call_id"]
    row = _get(env, cid, world["ben"])
    assert row["direction"] == "outbound" and row["agent_name"] == "Ann Wanjiru"
    assert row["name"] == "Mary" and row["wa_id"] == "254777000005" and row["status"] == "ringing"
    eng = sa.create_engine(env.db_url)
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT COUNT(*) FROM calls WHERE call_id = :c"), {"c": cid}).scalar() == 1
    eng.dispose()


async def _webhook_async_status(env, cid, status, **extra):
    from app.routers import whatsapp_webhook as ww
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "calls", "value": {
        "statuses": [{"id": cid, "type": "call", "status": status, **extra}]}}]}]}
    req = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=env.redis)))
    await ww._handle_calls(req, payload)


def test_a_terminate_with_opaque_data_closes_a_row_that_never_landed(env, world):
    from app.services import wa_calling
    opaque = wa_calling.opaque(world["ben"], None)
    _webhook(env, {"id": "wacid.lost.1", "event": "terminate", "status": "COMPLETED", "to": "254777000006",
                   "direction": "BUSINESS_INITIATED", "biz_opaque_callback_data": opaque})
    row = _get(env, "wacid.lost.1", world["ann"])
    assert row["status"] == "no_answer" and row["agent_name"] == "Ben Otieno" and row["direction"] == "outbound"
    # Someone else's opaque data (not ours) never invents a row.
    _webhook(env, {"id": "wacid.lost.2", "event": "terminate", "status": "COMPLETED",
                   "biz_opaque_callback_data": "order-123"})
    assert env.client.get("/api/admin/calls/wacid.lost.2", headers=_as(world["ann"])).status_code == 404


def test_rejected_before_any_row_or_opaque_is_parked_and_applied(env, world, monkeypatch):
    from app.services import wa_calling

    async def connect(to, sdp, **kw):
        cid = f"wacid.out.{to}"
        await _webhook_async_status(env, cid, "REJECTED")          # no opaque data at all
        await _webhook_async(env, {"id": cid, "event": "terminate", "status": "COMPLETED"})
        return {"calls": [{"id": cid}]}
    monkeypatch.setattr(wa_calling, "connect", connect)
    cid = env.client.post("/api/admin/calls/connect", json={"to": "254777000007", "sdp": "v=0"},
                          headers=_as(world["ann"])).json()["call_id"]
    assert _get(env, cid, world["ann"])["status"] == "rejected"
    assert env.redis.events("call_ended")[-1]["outcome"] == "rejected"


def test_the_route_and_the_webhook_racing_write_one_row(env, world):
    from app.services import call_log, wa_calling
    opaque = wa_calling.opaque(world["ann"], None)

    async def race():
        return await asyncio.gather(*(
            [call_log.upsert_outbound("wacid.race", "254777000008", agent_id=uuid.UUID(world["ann"]), name="Joy")
             for _ in range(3)] +
            [call_log.row_from_opaque("wacid.race", "254777000008", opaque) for _ in range(3)]))
    results = asyncio.run(race())
    assert sum(1 for r in results if r) == 1
    row = _get(env, "wacid.race", world["ann"])
    assert row["agent_name"] == "Ann Wanjiru" and row["name"] == "Joy"


def test_the_unanswered_streak_counts_since_the_last_connected_call(env, world):
    wa = "254777000009"

    def call_out(outcome):
        cid = env.client.post("/api/admin/calls/connect", json={"to": wa, "sdp": "v=0"},
                              headers=_as(world["ann"])).json()["call_id"]
        env.redis.store.pop(f"wa:call:{cid}:terminate", None)
        if outcome == "rejected":
            _status(env, cid, "REJECTED")
        elif outcome == "completed":
            _webhook(env, {"id": cid, "event": "connect", "session": {"sdp_type": "answer", "sdp": "a"}})
            _end(env, cid, duration=40)
        elif outcome == "cancelled":
            env.client.post(f"/api/admin/calls/{cid}/terminate", json={}, headers=_as(world["ann"]))
        else:
            _end(env, cid)
        # Rows need distinct ids + times: rename, then age it.
        eng = sa.create_engine(env.db_url)
        with eng.begin() as c:
            new = f"wacid.s.{uuid.uuid4().hex[:8]}"
            c.execute(sa.text("UPDATE calls SET call_id = :n, started_at = NOW() - make_interval(secs => :k) "
                              "WHERE call_id = :c"), {"n": new, "c": cid, "k": 1000 - len(env.redis.published)})
        eng.dispose()
        for k in [k for k in env.redis.store if cid in k]:
            env.redis.store.pop(k)

    call_out("no_answer")
    call_out("completed")
    call_out("no_answer")
    call_out("cancelled")        # neither counts nor resets
    call_out("rejected")
    assert _perm_get(env, wa, world["ann"])["unanswered_streak"] == 2
    call_out("no_answer")
    assert _perm_get(env, wa, world["ann"])["unanswered_streak"] == 3
    _ring(env, "wacid.s.in", frm=wa)                 # they call us and we talk: reset
    env.client.post("/api/admin/calls/wacid.s.in/answer", json={"sdp": "v=0"}, headers=_as(world["ben"]))
    assert _perm_get(env, wa, world["ann"])["unanswered_streak"] == 0


def test_an_automatic_revoke_is_recorded_distinctly(env, world):
    wa = "254777000010"
    _webhook(env, field="messages", messages=[{
        "from": wa, "type": "interactive", "interactive": {
            "type": "call_permission_reply",
            "call_permission_reply": {"response": "reject", "response_source": "automatic"}}}])
    ev = env.redis.events("call_permission")[-1]
    assert ev["status"] == "denied" and ev["revoked"] is True and ev["reason"] == "automatic"
    p = _perm_get(env, wa, world["ann"])
    assert p["status"] == "denied" and p["revoked"] is True
    # A customer's own "no" is not a revoke.
    _webhook(env, field="messages", messages=[{
        "from": "254777000011", "type": "interactive", "interactive": {
            "type": "call_permission_reply",
            "call_permission_reply": {"response": "reject", "response_source": "user_action"}}}])
    assert env.redis.events("call_permission")[-1]["revoked"] is False


# ── C5 errors on every route ─────────────────────────────────────────────────

@pytest.mark.parametrize("code,status,action", [
    ("138001", 502, "none"), ("138005", 502, "wait"), ("138012", 502, "wait"),
    ("138000", 502, "admin"), ("138004", 502, "retry"), ("190", 502, "admin"),
])
def test_connect_errors_carry_code_and_action(env, world, code, status, action):
    env.meta.connect_error = f'WA call connect failed (400): {{"error":{{"code":{code}}}}}'
    r = env.client.post("/api/admin/calls/connect", json={"to": "254788000001", "sdp": "v=0"},
                        headers=_as(world["ann"]))
    assert r.status_code == status and r.json()["code"] == code and r.json()["action"] == action
    assert r.json()["detail"].startswith("call failed: ")
    assert [s for s in env.meta.sent if s[0] == "connect"] == []     # never retried


def test_no_permission_on_connect_says_request_permission(env, world):
    env.meta.connect_error = 'WA call connect failed (400): {"error":{"code":138006}}'
    r = env.client.post("/api/admin/calls/connect", json={"to": "254788000002", "sdp": "v=0"},
                        headers=_as(world["ann"]))
    assert r.status_code == 409 and r.json()["action"] == "request_permission"


def test_accept_and_terminate_failures_are_explained(env, world, monkeypatch):
    from app.services import wa_calling

    async def accept(cid, sdp, **kw):
        raise wa_calling.MetaError('WA call accept failed (400): {"error":{"code":138007}}', status=400, code=138007)

    async def terminate(cid):
        raise wa_calling.MetaError("WA call terminate failed (503): down", status=503)
    monkeypatch.setattr(wa_calling, "accept", accept)
    monkeypatch.setattr(wa_calling, "terminate", terminate)
    _ring(env, "wacid.err.1")
    r = env.client.post("/api/admin/calls/wacid.err.1/answer", json={"sdp": "v=0"}, headers=_as(world["ann"]))
    assert r.status_code == 502 and r.json()["code"] == "138007" and r.json()["action"] == "retry"
    # The lock was released: a colleague may still try.
    assert "wa:call:answered:wacid.err.1" not in env.redis.store
    r = env.client.post("/api/admin/calls/wacid.err.1/terminate", json={}, headers=_as(world["ann"]))
    assert r.status_code == 502 and r.json()["code"] == "meta_unavailable" and r.json()["action"] == "retry"
    assert _get(env, "wacid.err.1", world["ann"])["status"] == "ringing"


# ── C7 Meta transcription + recording ────────────────────────────────────────

def _meta_media(env, monkeypatch, payloads: dict, fail=False):
    from app.services import call_transcribe as ct, wa_calling
    monkeypatch.setattr(ct, "AsyncSessionLocal", env.maker)
    updates = []

    async def publish(cid):
        updates.append(cid)
    monkeypatch.setattr(ct, "_publish_update", publish)

    async def download(media_id):
        if fail:
            raise wa_calling.MetaError("WA media lookup failed (404)", status=404)
        return payloads[media_id], "application/json"
    monkeypatch.setattr(wa_calling, "download_media", download)

    async def analyse(text):
        assert text.startswith("Agent: ")
        return "Wants two cassocks.", {"next_action": "Send price"}
    monkeypatch.setattr(ct, "analyse_call", analyse)
    return updates


TRANSCRIPT_DOC = {"language": "sw", "results": [
    {"channel": 0, "start": 0.2, "text": "Habari, Bethany House."},
    {"channel": 1, "start": 1.5, "text": "Nataka cassock mbili."},
    {"channel": 1, "start": 3.0, "text": "Size 52."},
    {"channel": 0, "start": 4.0, "text": "Sawa, nitakutumia bei."}]}


def test_metas_transcript_lands_speaker_labelled_with_the_brief(env, world, monkeypatch):
    from app.services import call_transcribe as ct
    wa = "254799000001"
    updates = _meta_media(env, monkeypatch, {"m1": json.dumps(TRANSCRIPT_DOC).encode()})
    _ring(env, "wacid.tr.1", frm=wa)
    env.client.post("/api/admin/calls/wacid.tr.1/answer", json={"sdp": "v=0"}, headers=_as(world["ann"]))
    _end(env, "wacid.tr.1", duration=60)
    assert asyncio.run(ct.ingest_meta_transcription("wacid.tr.1", "m1")) == "done"
    t = env.client.get("/api/admin/calls/wacid.tr.1/transcript", headers=_as(world["ann"])).json()
    assert t["transcript"] == ("Agent: Habari, Bethany House.\nCustomer: Nataka cassock mbili. Size 52.\n"
                               "Agent: Sawa, nitakutumia bei.")
    assert t["language"] == "sw" and t["summary"] == "Wants two cassocks." and t["status"] == "done"
    assert t["insights"] == {"next_action": "Send price"} and updates
    eng = sa.create_engine(env.db_url)
    with eng.connect() as c:
        notes = c.execute(sa.text("SELECT state->>'crm_notes' FROM users WHERE wa_id = :w"), {"w": wa}).scalar()
    eng.dispose()
    assert "Wants two cassocks." in notes and "Send price" in notes
    # A redelivered event never writes a second note.
    assert asyncio.run(ct.ingest_meta_transcription("wacid.tr.1", "m1")) == "already"


def test_a_failed_download_never_touches_the_call(env, world, monkeypatch):
    from app.services import call_transcribe as ct
    _meta_media(env, monkeypatch, {}, fail=True)
    _ring(env, "wacid.tr.2")
    _end(env, "wacid.tr.2")
    assert asyncio.run(ct.ingest_meta_transcription("wacid.tr.2", "gone")) == "download_failed"
    assert asyncio.run(ct.ingest_meta_recording("wacid.tr.2", "gone")) == "download_failed"
    row = _get(env, "wacid.tr.2", world["ann"])
    assert row["status"] == "missed" and row["transcript_status"] == "none" and not row["has_recording"]
    assert asyncio.run(ct.ingest_meta_transcription("wacid.unknown", "m")) == "unknown_call"


def test_metas_recording_is_kept_only_when_we_have_none(env, world, monkeypatch, tmp_path):
    from app.services import call_transcribe as ct
    import app.routers.media as media
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path))
    _meta_media(env, monkeypatch, {"r1": b"OggS-audio"})
    _ring(env, "wacid.rec.1")
    _end(env, "wacid.rec.1")
    assert asyncio.run(ct.ingest_meta_recording("wacid.rec.1", "r1")) == "done"
    row = _get(env, "wacid.rec.1", world["ann"])
    assert row["has_recording"] and row["transcript_status"] == "recorded"
    assert asyncio.run(ct.ingest_meta_recording("wacid.rec.1", "r1")) == "already"
    assert len(list(tmp_path.iterdir())) == 1


def test_the_webhook_hands_meta_artifacts_off_without_waiting(env, world, monkeypatch):
    from app.services import call_transcribe as ct
    seen = []
    monkeypatch.setattr(ct, "schedule_meta_artifact", lambda kind, cid, ev: seen.append((kind, cid)))
    _webhook(env, {"id": "wacid.ev.1", "event": "call_transcription_available", "transcription": {"id": "m1"}})
    _webhook(env, {"id": "wacid.ev.1", "event": "call_recording_available", "recording": {"id": "r1"}})
    _webhook(env, {"id": "wacid.ev.1", "event": "call_recording_available", "recording": {"id": "r1"}})
    assert seen == [("transcription", "wacid.ev.1"), ("recording", "wacid.ev.1")]
    assert env.redis.events("incoming_call") == [] and env.redis.events("call_ended") == []


def test_ice_config_says_whether_meta_transcribes(env, world, monkeypatch):
    from app.core.config import settings
    assert env.client.get("/api/admin/calls/ice-config", headers=_as(world["ann"])).json()["meta_transcription"] is False
    monkeypatch.setattr(settings, "call_meta_transcription", True, raising=False)
    assert env.client.get("/api/admin/calls/ice-config", headers=_as(world["ann"])).json()["meta_transcription"] is True


# ── C8 voicemail ─────────────────────────────────────────────────────────────

def _voicemail(env, cid, frm="254700111222", monkeypatch=None):
    from app.routers import whatsapp_webhook as ww
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": "PNID"},
        "messages": [{"from": frm, "id": cid, "timestamp": "1", "type": "audio",
                      "audio": {"id": "media-vm", "mime_type": "audio/ogg"}}]}}]}]}
    asyncio.run(ww._tap_voicemail(payload, env.redis))
    return payload


def test_a_voicemail_is_linked_to_its_call(env, world):
    _ring(env, "wacid.vm.1")
    _end(env, "wacid.vm.1")
    assert _get(env, "wacid.vm.1", world["ann"])["has_voicemail"] is False
    _voicemail(env, "wacid.vm.1")
    row = _get(env, "wacid.vm.1", world["ann"])
    assert row["has_voicemail"] is True and row["status"] == "missed"
    assert env.redis.events("call_update")[-1]["call"]["has_voicemail"] is True
    n = len(env.redis.events("call_update"))
    _voicemail(env, "wacid.vm.1")                    # Meta retry: linked once
    assert len(env.redis.events("call_update")) == n


def test_a_voicemail_before_its_call_is_logged_and_never_rings(env, world):
    _voicemail(env, "wacid.vm.2", frm="254700999888")
    row = _get(env, "wacid.vm.2", world["ann"])
    assert row["has_voicemail"] and row["status"] == "missed" and row["wa_id"] == "254700999888"
    _ring(env, "wacid.vm.2", frm="254700999888")
    assert env.redis.events("incoming_call") == []


def test_ordinary_audio_is_not_a_voicemail_and_ingestion_is_untouched(env, world, monkeypatch):
    from app.routers import whatsapp_webhook as ww
    from app.services import wa_native
    ingested = []

    async def handle(payload, redis):
        ingested.append(payload)
        return 1, 0
    monkeypatch.setattr(wa_native, "handle_webhook", handle)
    _ring(env, "wacid.vm.3")
    _end(env, "wacid.vm.3")
    for mid in ("wamid.HBgM123", "wacid.vm.3"):
        payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
            "messages": [{"from": "254700111222", "id": mid, "type": "audio", "audio": {"id": "a"}}]}}]}]}
        req = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=env.redis)))
        resp = asyncio.run(ww.process_payload(req, json.dumps(payload).encode(), None))
        assert resp.status_code == 200
    assert len(ingested) == 2                        # both still land in the chat
    assert _get(env, "wacid.vm.3", world["ann"])["has_voicemail"] is True


def test_a_window_we_misread_falls_back_to_the_template(env, world, monkeypatch):
    """Our records said they wrote within 24 h, but Meta refuses the free-form
    request (131047): the approved template still reaches them."""
    from app.core.config import settings
    from app.services import wa_calling
    monkeypatch.setattr(settings, "call_permission_template", "call_ok", raising=False)
    wa = "254766000009"
    _inbound_message(env, wa, hours_ago=2, name="Grace Njeri")

    async def refused(to, text=None):
        raise RuntimeError('call-permission request failed (400): {"error":{"code":131047}}')
    monkeypatch.setattr(wa_calling, "request_call_permission", refused)
    r = env.client.post("/api/admin/calls/request-permission", json={"to": wa}, headers=_as(world["ann"]))
    assert r.status_code == 200 and r.json()["route"] == "template"
    assert env.meta.sent[-1][:3] == ("permission_template", wa, "call_ok")


# ── Missed-call follow-up (opt-in) ───────────────────────────────────────────

def test_a_missed_call_gets_one_message_and_a_flag_only_when_switched_on(env, world, monkeypatch):
    import asyncio as _a
    from app.core.config import settings
    from app.services import missed_call, meta_send, n8n_bridge
    sent, saved = [], []

    async def fake_send(channel, to, text, **kw):
        sent.append((channel, to, text))
        return "wamid.1"

    async def fake_save(db, redis, wa_id, text, waba_msg_id=None):
        saved.append((wa_id, waba_msg_id))
    monkeypatch.setattr(meta_send, "send_to_channel", fake_send)
    monkeypatch.setattr(n8n_bridge, "save_outbound_message", fake_save)

    wa = "254777000001"
    _ring(env, "wacid.mc.1", frm=wa)
    _end(env, "wacid.mc.1", status="FAILED")                  # missed
    # Off by default: the terminate schedules nothing, nothing goes out.
    assert settings.missed_call_message_enabled is False
    assert not missed_call._bg and sent == []
    monkeypatch.setattr(settings, "missed_call_message_enabled", True, raising=False)
    assert _a.run(missed_call._follow_up(env.redis, "wacid.mc.1")) is True
    assert sent == [("whatsapp", wa, settings.missed_call_message)] and saved == [(wa, "wamid.1")]
    # A second missed call within the cooldown: no second message.
    _ring(env, "wacid.mc.2", frm=wa)
    _end(env, "wacid.mc.2", status="FAILED")
    assert _a.run(missed_call._follow_up(env.redis, "wacid.mc.2")) is False
    assert len(sent) == 1


def test_no_missed_call_message_once_they_were_called_back(env, world, monkeypatch):
    import asyncio as _a
    from app.core.config import settings
    from app.services import missed_call, meta_send
    monkeypatch.setattr(settings, "missed_call_message_enabled", True, raising=False)
    sent = []

    async def fake_send(channel, to, text, **kw):
        sent.append(to)
    monkeypatch.setattr(meta_send, "send_to_channel", fake_send)
    wa = "254777000002"
    _ring(env, "wacid.mc.3", frm=wa)
    _end(env, "wacid.mc.3", status="FAILED")
    _ring(env, "wacid.mc.4", frm=wa)                           # they call again and Ann answers
    env.client.post("/api/admin/calls/wacid.mc.4/answer", json={"sdp": "v=0"}, headers=_as(world["ann"]))
    assert _a.run(missed_call._follow_up(env.redis, "wacid.mc.3")) is False
    # Answered / declined calls never get it either.
    assert _a.run(missed_call._follow_up(env.redis, "wacid.mc.4")) is False
    assert sent == []


def test_a_failing_send_never_breaks_anything(env, world, monkeypatch):
    import asyncio as _a
    from app.core.config import settings
    from app.services import missed_call, meta_send
    monkeypatch.setattr(settings, "missed_call_message_enabled", True, raising=False)

    async def boom(*a, **k):
        raise RuntimeError("WhatsApp down")
    monkeypatch.setattr(meta_send, "send_to_channel", boom)
    _ring(env, "wacid.mc.5", frm="254777000003")
    _end(env, "wacid.mc.5", status="FAILED")
    assert _a.run(missed_call._follow_up(env.redis, "wacid.mc.5")) is False
    assert _get(env, "wacid.mc.5", world["ann"])["status"] == "missed"


def test_a_pending_request_says_when_it_was_sent(env, world):
    wa = "254788000001"
    _inbound_message(env, wa, hours_ago=1)
    env.client.post("/api/admin/calls/request-permission", json={"to": wa}, headers=_as(world["ann"]))
    perm = env.client.get(f"/api/admin/calls/permission?wa_id={wa}", headers=_as(world["ann"])).json()
    assert perm["status"] == "requested" and perm["requested_at"]
