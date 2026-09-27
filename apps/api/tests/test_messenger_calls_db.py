"""Messenger voice calling — the second channel adapter, proven against a real
Postgres through the real page webhook and the real /calls routes.

The Messenger Calling API (docs/research/META_CALLING_2026-09.md §7a) differs
from WhatsApp in one way that matters here: a customer's call arrives with NO
SDP — the softphone builds the offer, `accept` carries it, and Meta's answer
comes back in the response. Everything else (ringing every agent, first answer
wins, outcomes, permission) behaves exactly like WhatsApp, and a WhatsApp call
alongside is untouched. Skips cleanly without a database.
"""
import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests import test_calls_db as _calls, test_security_db as _sec
from tests.test_calls_db import _get, _ring
from tests.test_security_db import _as

# The shared fixtures (the throwaway database, agents, the admin app + fake
# redis + fake WhatsApp Graph) — bound here so pytest finds them.
fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark

PSID = "5275811702471834"
PAGE = "106378625516323"


@pytest.fixture
def menv(env, monkeypatch):
    """`env` plus a fake Messenger Graph and the switch on."""
    from app.core.config import settings
    from app.services import messenger_calling, wa_calling
    monkeypatch.setattr(settings, "messenger_calling_enabled", True)
    monkeypatch.setattr(settings, "meta_page_token", "page-token")
    m = types.SimpleNamespace(sent=[], perm=None, connect_error=None, request_error=None,
                              accept_error=None)

    async def accept(cid, sdp, *, page_id):
        if m.accept_error:
            raise m.accept_error
        m.sent.append(("accept", cid, page_id, sdp))
        return {"answer": "v=0 meta-answer", "renegotiation": "v=0 meta-reneg"}

    async def reject(cid, *, page_id):
        m.sent.append(("reject", cid, page_id))
        return {"success": True}

    async def terminate(cid, *, page_id):
        m.sent.append(("terminate", cid, page_id))
        return {"success": True}

    async def connect(psid, sdp, *, page_id):
        if m.connect_error:
            raise m.connect_error
        m.sent.append(("connect", psid, page_id))
        return {"id": f"c_out_{psid}", "answer": "v=0 meta-answer", "renegotiation": None}

    async def get_perm(psid, page_id=None):
        m.sent.append(("get_permission", psid))
        if m.perm is None:
            raise wa_calling.MetaError("Messenger call-permission read failed (network)", status=0)
        return messenger_calling.normalize_permission(m.perm)

    async def request_perm(psid, page_id=None):
        if m.request_error:
            raise m.request_error
        m.sent.append(("permission", psid))
        return {"recipient": {"id": psid}, "message_id": "m_1"}

    for name, fn in (("accept", accept), ("reject", reject), ("terminate", terminate),
                     ("connect", connect), ("get_call_permission", get_perm),
                     ("request_call_permission", request_perm)):
        monkeypatch.setattr(messenger_calling, name, fn)
    env.m = m
    return env


def _page(env, *calls, page=PAGE, **entry):
    """One page webhook through the real Messenger calls tap."""
    from app.routers import meta_webhook as mw
    payload = {"object": "page", "entry": [{"id": page, "time": 1671644824,
                                            **({"calls": list(calls)} if calls else {}), **entry}]}
    asyncio.run(mw._handle_messenger_calls(payload, env.redis))


def _m_ring(env, cid, psid=PSID):
    _page(env, {"id": cid, "to": PAGE, "from": psid, "event": "connect",
                "timestamp": 1671644824, "call_direction": "user_initiated"})


def _m_end(env, cid, duration=None, status="Completed"):
    ev = {"id": cid, "event": "terminate", "timestamp": 1671644944, "status": status}
    if duration is not None:
        ev["duration"] = duration
    _page(env, ev)


def _post(env, path, who, json=None):
    return env.client.post(f"/api/admin{path}", json=json if json is not None else {}, headers=_as(who))


# ── Inbound: rings as Messenger, answered through the Messenger adapter ──────

def test_a_messenger_call_rings_everyone_and_is_answered_with_our_offer(menv, world):
    env = menv
    _m_ring(env, "c_in_1")
    ring = env.redis.events("incoming_call")
    assert len(ring) == 1
    assert ring[0]["channel"] == "messenger" and ring[0]["from"] == PSID and ring[0]["call_id"] == "c_in_1"
    row = env.redis.events("call_update")[-1]["call"]
    assert row["channel"] == "messenger" and row["wa_id"] is None and row["external_id"] == PSID
    assert row["status"] == "ringing" and row["person_id"]         # the PSID's person, resolved

    # Messenger sends no offer: the phone is told to build one.
    offer = env.client.get("/api/admin/calls/c_in_1/offer", headers=_as(world["ann"])).json()
    assert offer["offer_required"] is True and offer["sdp"] is None and offer["channel"] == "messenger"

    a = _post(env, "/calls/c_in_1/answer", world["ann"], {"sdp": "v=0 our-offer"})
    b = _post(env, "/calls/c_in_1/answer", world["ben"], {"sdp": "v=0 other-offer"})
    assert a.status_code == 200, a.text
    out = a.json()
    assert out["channel"] == "messenger" and out["sdp"] == "v=0 meta-answer" and out["sdp_type"] == "answer"
    assert out["renegotiation"] == "v=0 meta-reneg"
    assert b.status_code == 409 and "Ann Wanjiru" in b.json()["detail"]
    # The Messenger adapter accepted once, on the Page the call came to — WhatsApp never.
    assert env.m.sent == [("accept", "c_in_1", PAGE, "v=0 our-offer")]
    assert not [s for s in env.meta.sent if s[0] == "accept"]
    assert _get(env, "c_in_1", world["ben"])["status"] == "answered"
    assert len(env.redis.events("call_answered")) == 1

    _m_end(env, "c_in_1", duration=40)
    r = _get(env, "c_in_1", world["ben"])
    assert r["status"] == "completed" and r["duration"] == 40 and r["channel"] == "messenger"
    ended = env.redis.events("call_ended")[-1]
    assert ended["outcome"] == "completed" and ended["channel"] == "messenger" and ended["status"] == "Completed"


def test_first_answer_wins_and_a_whatsapp_call_alongside_is_untouched(menv, world):
    env = menv
    _ring(env, "wacid.par", frm="254700999888")
    _m_ring(env, "c_in_2")
    rings = {e["call_id"]: e["channel"] for e in env.redis.events("incoming_call")}
    assert rings == {"wacid.par": "whatsapp", "c_in_2": "messenger"}

    assert _post(env, "/calls/c_in_2/answer", world["ann"], {"sdp": "v=0 o"}).status_code == 200
    assert _post(env, "/calls/c_in_2/answer", world["ben"], {"sdp": "v=0 o"}).status_code == 409
    wa = _post(env, "/calls/wacid.par/answer", world["ben"], {"sdp": "v=0 answer"})
    assert wa.status_code == 200 and wa.json() == {"ok": True, "call_id": "wacid.par"}   # WhatsApp shape as before
    assert [s for s in env.meta.sent if s[0] == "accept"] == [("accept", "wacid.par")]
    assert [s[:2] for s in env.m.sent] == [("accept", "c_in_2")]

    w = _get(env, "wacid.par", world["ann"])
    assert w["channel"] == "whatsapp" and w["wa_id"] == "254700999888" and w["agent_name"] == "Ben Otieno"
    assert _get(env, "c_in_2", world["ben"])["agent_name"] == "Ann Wanjiru"

    # Hanging up each goes to its own platform.
    _post(env, "/calls/wacid.par/terminate", world["ben"])
    _post(env, "/calls/c_in_2/terminate", world["ann"])
    assert ("terminate", "wacid.par") in env.meta.sent and ("terminate", "c_in_2", PAGE) in env.m.sent
    assert not [s for s in env.m.sent if s[1] == "wacid.par"]
    assert _get(env, "wacid.par", world["ann"])["status"] == "completed"
    assert _get(env, "c_in_2", world["ann"])["status"] == "completed"
    assert {r["channel"] for r in env.client.get("/api/admin/calls", headers=_as(world["ann"])).json()} \
        == {"whatsapp", "messenger"}
    only = env.client.get("/api/admin/calls?channel=messenger", headers=_as(world["ann"])).json()
    assert [r["call_id"] for r in only] == ["c_in_2"]


def test_missed_declined_and_call_back_later(menv, world):
    env = menv
    _m_ring(env, "c_miss")
    _m_end(env, "c_miss")                              # the customer gave up: no duration
    r = _get(env, "c_miss", world["ann"])
    assert r["status"] == "missed" and r["follow_up_open"] is True
    assert env.redis.events("call_ended")[-1]["outcome"] == "missed"

    _m_ring(env, "c_decl", psid="111222333")
    d = _post(env, "/calls/c_decl/terminate", world["ben"])
    assert d.status_code == 200 and d.json()["outcome"] == "declined"
    assert ("reject", "c_decl", PAGE) in env.m.sent               # a ringing call is REJECTED
    _m_end(env, "c_decl")                                          # Meta's terminate after it
    assert _get(env, "c_decl", world["ann"])["status"] == "declined"

    _m_ring(env, "c_cb", psid="444555666")
    assert _post(env, "/calls/c_cb/callback", world["ann"]).status_code == 200
    assert ("reject", "c_cb", PAGE) in env.m.sent
    r = _get(env, "c_cb", world["ben"])
    assert r["status"] == "callback" and r["agent_name"] == "Ann Wanjiru" and r["follow_up_open"]
    assert not [s for s in env.meta.sent if s[0] == "terminate"]   # WhatsApp never asked


# ── Business-initiated ───────────────────────────────────────────────────────

def _granted():
    exp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    return {"permission": {"status": "has_permission", "expiration_time": exp},
            "actions": [{"action_name": "send_call_permission_request", "can_perform": False,
                         "limits": [{"time_period": "PT24H", "max_allowed": 2, "current_usage": 1}]},
                        {"action_name": "start_call", "can_perform": True}]}


def test_our_call_with_permission_rings_is_answered_and_completes(menv, world):
    env = menv
    env.m.perm = _granted()
    r = _post(env, "/calls/connect", world["ann"],
              {"channel": "messenger", "psid": PSID, "sdp": "v=0 o", "name": "Grace"})
    assert r.status_code == 200, r.text
    body = r.json()
    cid = body["call_id"]
    assert body["channel"] == "messenger" and body["sdp"] == "v=0 meta-answer"   # the answer, at once
    assert ("connect", PSID, "me") in env.m.sent and not [s for s in env.meta.sent if s[0] == "connect"]
    row = _get(env, cid, world["ann"])
    assert (row["direction"], row["status"], row["channel"], row["external_id"], row["wa_id"]) == \
        ("outbound", "ringing", "messenger", PSID, None)
    assert row["agent_name"] == "Ann Wanjiru" and row["name"] == "Grace"
    # Nobody else can answer our outbound call.
    assert _post(env, f"/calls/{cid}/answer", world["ben"], {"sdp": "x"}).status_code == 409

    # Meta's connect webhook for our call never rings anyone.
    _page(env, {"id": cid, "to": PSID, "from": PAGE, "event": "connect",
                "call_direction": "business_initiated", "timestamp": 1})
    assert not env.redis.events("incoming_call")
    _page(env, {"id": cid, "event": "call_status", "recipient_id": PSID, "call_status": "ringing"})
    assert env.redis.events("call_status")[-1] == {"type": "call_status", "call_id": cid, "status": "ringing"}
    _page(env, {"id": cid, "event": "call_status", "recipient_id": PSID, "call_status": "accepted"})
    assert env.redis.events("call_answered")[-1]["agent_name"] == "Ann Wanjiru"
    _page(env, {"id": cid, "event": "media_update", "timestamp": 2,
                "session": {"version": 1, "sdp_renegotiation": {"sdp_type": "offer", "sdp": "v=0 reneg"}}})
    mu = [m for c, m in env.redis.published if m["type"] == "media_update"]
    assert mu[-1]["sdp"] == "v=0 reneg" and mu[-1]["version"] == 1 and mu[-1]["channel"] == "messenger"
    _m_end(env, cid, duration=90)
    assert _get(env, cid, world["ann"])["status"] == "completed"


def test_our_call_without_permission_is_a_409_that_offers_the_request(menv, world):
    env = menv
    env.m.perm = {"permission": {"status": "no_permission"},
                  "actions": [{"action_name": "send_call_permission_request", "can_perform": True},
                              {"action_name": "start_call", "can_perform": False}]}
    r = _post(env, "/calls/connect", world["ann"], {"channel": "messenger", "psid": PSID, "sdp": "v=0"})
    assert r.status_code == 409
    assert r.json()["code"] == "no_permission" and r.json()["action"] == "request_permission"
    assert r.headers["X-Neema-Reason"] == "no_permission"
    assert not [s for s in env.m.sent if s[0] == "connect"]          # Meta never asked to ring


def test_permission_request_then_approved_then_declined(menv, world):
    env = menv
    r = _post(env, "/calls/request-permission", world["ann"], {"channel": "messenger", "psid": PSID})
    assert r.status_code == 200, r.text
    assert r.json()["permission"]["status"] == "requested" and r.json()["route"] == "calling_optin"
    assert ("permission", PSID) in env.m.sent
    ev = env.redis.events("call_permission")[-1]
    assert ev["channel"] == "messenger" and ev["external_id"] == PSID and ev["wa_id"] is None
    # The stores never mix: a WhatsApp key of the same digits is untouched.
    assert "wa:call:perm:" + PSID not in env.redis.store

    exp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    # The documented shape: the reply sits on the entry itself.
    _page(env, sender={"id": PSID}, recipient={"id": PAGE}, timestamp=1,
          call_permission_reply={"response": "approve", "expiration_timestamp": str(exp)})
    ev = env.redis.events("call_permission")[-1]
    assert ev["status"] == "granted" and ev["external_id"] == PSID and ev["expires_at"]
    perm = env.client.get(f"/api/admin/calls/permission?channel=messenger&psid={PSID}",
                          headers=_as(world["ann"])).json()
    assert perm["status"] == "granted" and perm["channel"] == "messenger" and perm["source"] == "store"

    # Also read from messaging[] (the prose calls it a postback).
    _page(env, messaging=[{"sender": {"id": PSID}, "recipient": {"id": PAGE},
                           "call_permission_reply": {"response": "reject"}}])
    assert env.redis.events("call_permission")[-1]["status"] == "denied"


def test_request_limit_is_a_409_from_metas_counters(menv, world):
    env = menv
    env.m.perm = {"permission": {"status": "no_permission"},
                  "actions": [{"action_name": "send_call_permission_request", "can_perform": False,
                               "limits": [{"time_period": "PT24H", "max_allowed": 2, "current_usage": 2}]}]}
    p = env.client.get(f"/api/admin/calls/permission?channel=messenger&psid={PSID}", headers=_as(world["ann"]))
    assert p.json()["can_request"] is False and p.json()["source"] == "meta"
    r = _post(env, "/calls/request-permission", world["ann"], {"channel": "messenger", "psid": PSID})
    assert r.status_code == 409 and r.json()["code"] == "request_limit" and r.json()["action"] == "wait"
    assert ("permission", PSID) not in env.m.sent


# ── The switch ───────────────────────────────────────────────────────────────

def test_switched_off_nobody_rings_and_every_route_says_so(menv, world, monkeypatch):
    from app.core.config import settings
    env = menv
    monkeypatch.setattr(settings, "messenger_calling_enabled", False)
    _m_ring(env, "c_off")
    assert not env.redis.events("incoming_call") and not env.redis.events("call_update")
    assert env.client.get("/api/admin/calls/c_off", headers=_as(world["ann"])).status_code == 404
    for path, body in (("/calls/connect", {"channel": "messenger", "psid": PSID, "sdp": "v=0"}),
                       ("/calls/request-permission", {"channel": "messenger", "psid": PSID})):
        r = _post(env, path, world["ann"], body)
        assert r.status_code == 409 and r.json()["code"] == "messenger_calling_off", path
        assert r.headers["X-Neema-Reason"] == "messenger_calling_off"
    r = env.client.get(f"/api/admin/calls/permission?channel=messenger&psid={PSID}", headers=_as(world["ann"]))
    assert r.status_code == 409
    ch = env.client.get("/api/admin/calls/channels", headers=_as(world["ann"])).json()
    assert ch["messenger"]["inbound"] is False and ch["messenger"]["outbound"] is False
    assert ch["whatsapp"]["inbound"] is True and ch["instagram"]["outbound"] is False
    ice = env.client.get("/api/admin/calls/ice-config", headers=_as(world["ann"])).json()
    assert ice["channels"]["messenger"]["outbound"] is False and ice["channels"]["whatsapp"]["video"] is False
    assert env.m.sent == []

    monkeypatch.setattr(settings, "messenger_calling_enabled", True)
    ch = env.client.get("/api/admin/calls/channels", headers=_as(world["ann"])).json()
    assert ch["messenger"] == {"inbound": True, "outbound": True, "video": False, "sdp": "offer"}


# ── Order and repeats ────────────────────────────────────────────────────────

def test_duplicate_and_out_of_order_webhooks(menv, world):
    env = menv
    _m_ring(env, "c_dup")
    _m_ring(env, "c_dup")                                          # Meta retry
    assert len(env.redis.events("incoming_call")) == 1

    _m_end(env, "c_early")                                         # terminate beats its connect
    _m_ring(env, "c_early")
    assert [e["call_id"] for e in env.redis.events("incoming_call")] == ["c_dup"]
    assert _get(env, "c_early", world["ann"])["status"] == "missed"

    # A redelivered connect for a call we already logged (dedup key gone) never rings.
    env.redis.store.pop("wa:call:c_dup:connect", None)
    _m_ring(env, "c_dup")
    assert len(env.redis.events("incoming_call")) == 1

    # A late, older media_update is never applied over a newer one.
    for v in (2, 1):
        _page(env, {"id": "c_dup", "event": "media_update",
                    "session": {"version": v, "sdp_renegotiation": {"sdp_type": "offer", "sdp": f"v{v}"}}})
    mu = [m for c, m in env.redis.published if m["type"] == "media_update"]
    assert [m["version"] for m in mu] == [2]


def test_an_accepted_status_that_beats_our_row_is_applied_when_it_lands(menv, world, monkeypatch):
    env = menv
    env.m.perm = _granted()
    cid = f"c_out_{PSID}"
    _page(env, {"id": cid, "event": "call_status", "recipient_id": PSID, "call_status": "accepted"})
    r = _post(env, "/calls/connect", world["ann"], {"channel": "messenger", "psid": PSID, "sdp": "v=0"})
    assert r.json()["call_id"] == cid
    row = _get(env, cid, world["ann"])
    assert row["status"] == "answered" and row["agent_name"] == "Ann Wanjiru"


# ── Failures speak the same error shape ──────────────────────────────────────

def test_an_accept_failure_is_explained_and_frees_the_call(menv, world):
    from app.services.wa_calling import MetaError
    env = menv
    _m_ring(env, "c_err")
    env.m.accept_error = MetaError('Messenger call accept failed (400): {"error":{"code":2018396}}',
                                   status=400, code=2018396)
    r = _post(env, "/calls/c_err/answer", world["ann"], {"sdp": "v=0"})
    assert r.status_code == 502 and r.json()["code"] == "2018396" and r.json()["action"] == "none"
    assert r.headers["X-Neema-Reason"] == "2018396"
    env.m.accept_error = None
    assert _post(env, "/calls/c_err/answer", world["ben"], {"sdp": "v=0"}).status_code == 200


def test_messenger_error_table():
    from app.services import messenger_calling as mc
    from app.services.wa_calling import MetaError
    assert mc.classify_error(MetaError("x", status=400, code=190))["action"] == "admin"
    assert mc.classify_error(MetaError("x", status=400, code=2018389))["action"] == "admin"
    assert mc.classify_error(MetaError("x", status=0))["code"] == "meta_unavailable"
    out = mc.classify_error(MetaError('{"error":{"code":10,"error_subcode":2018278}}', status=400, code=10,
                                      body={"error": {"code": 10, "error_subcode": 2018278}}))
    assert out["code"] == "outside_window"
    assert mc.classify_error(RuntimeError("Consumer has not given permission to call"))["action"] \
        == "request_permission"
    # Both documented spellings of the accept answer.
    assert mc.session_of({"session": {"sdp_response": "A", "sdp_renegotiation": "B"}}) == \
        {"answer": "A", "renegotiation": "B"}
    assert mc.session_of({"session": {"sdp_response": {"sdp_type": "answer", "sdp": "A"}}}) == \
        {"answer": "A", "renegotiation": None}


# ── The call is part of the Messenger conversation ───────────────────────────

def test_the_call_shows_in_the_messenger_thread(menv, world):
    env = menv
    eng = sa.create_engine(env.db_url)
    conv_id = str(uuid.uuid4())
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO conversations (id, channel, external_id, intercept_mode, status, created_at, updated_at) "
            "VALUES (:id, 'messenger', :p, 'ai', 'open', NOW(), NOW())"), {"id": conv_id, "p": PSID})
    eng.dispose()
    _m_ring(env, "c_thr")
    _post(env, "/calls/c_thr/answer", world["ann"], {"sdp": "v=0"})
    _m_end(env, "c_thr", duration=65)
    assert _get(env, "c_thr", world["ann"])["conversation_id"] == conv_id
    thread = env.client.get(f"/api/admin/conversations/{conv_id}/messages", headers=_as(world["ann"])).json()
    calls = [t for t in thread if t.get("event_kind") == "call"]
    assert len(calls) == 1 and calls[0]["text"] == "Incoming call · 1:05"
    assert calls[0]["call"]["channel"] == "messenger"


# ── Ingestion never depends on the calls tap ─────────────────────────────────

def test_messenger_messages_still_land_when_the_calls_tap_raises(menv, world, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers import meta_webhook as mw
    from app.services import meta_send
    env = menv

    async def boom(payload, redis):
        raise RuntimeError("calls tap exploded")

    async def no_profile(*a, **k):
        return {}
    monkeypatch.setattr(mw, "_handle_messenger_calls", boom)
    monkeypatch.setattr(meta_send, "fetch_profile", no_profile)

    async def _db():
        async with env.maker() as s:
            yield s

    app = FastAPI()
    app.include_router(mw.router, prefix="/api/meta")
    app.dependency_overrides[get_db] = _db
    app.state.redis = env.redis
    payload = {"object": "page", "entry": [{
        "id": PAGE, "time": 1,
        "calls": [{"id": "c_x", "event": "connect", "from": PSID, "to": PAGE}],
        "messaging": [{"sender": {"id": PSID}, "recipient": {"id": PAGE}, "timestamp": 1,
                       "message": {"mid": "m_tap_1", "text": "Habari, do you have cassocks?"}}]}]}
    with TestClient(app) as c:
        r = c.post("/api/meta/webhook", json=payload)
    assert r.status_code == 200
    eng = sa.create_engine(env.db_url)
    with eng.connect() as c:
        n = c.execute(sa.text("SELECT count(*) FROM messages WHERE waba_msg_id = 'm_tap_1' "
                              "AND channel = 'messenger'")).scalar()
    eng.dispose()
    assert n == 1
