"""Cycle 3 on a real Postgres: every call with a customer reaches their thread
with everything the dashboard's call card reads — direction, outcome, who took
it, when, how long, recording / transcript / summary state, whether a call
back is owed, which app — and the recording's URL is NOT in that payload (it
is fetched from the authorised per-call endpoint when someone presses play).

Skips cleanly without a database (the Docker harness / CI migrations job has one).
"""
import json
import types
import uuid

import pytest
import sqlalchemy as sa

from tests.test_security_db import _as, _reachable, _sync_url, fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = pytest.mark.skipif(
    not _sync_url() or not _reachable(_sync_url()),
    reason="needs a reachable Postgres (CI migrations job / Docker harness)")

WA = "254700666001"
PSID = "6123456789012345"


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

    ids = {"ann": str(uuid.uuid4()), "ben": str(uuid.uuid4()),
           "conv": str(uuid.uuid4()), "mconv": str(uuid.uuid4())}
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE calls, messages, conversations, users, persons, agents CASCADE"))
        for key, name in (("ann", "Ann Wanjiru"), ("ben", "Ben Otieno")):
            c.execute(sa.text(
                "INSERT INTO agents (id, name, email, password_hash, role, is_available, "
                "is_superuser, active_convs, created_at) VALUES "
                "(:id, :n, :e, 'x', 'agent', TRUE, FALSE, 0, NOW())"),
                {"id": ids[key], "n": name, "e": f"{key}@x.ke"})
        c.execute(sa.text(
            "INSERT INTO conversations (id, wa_id, channel, external_id, intercept_mode, status, created_at, updated_at) "
            "VALUES (:id, :wa, 'whatsapp', :wa, 'ai', 'open', NOW(), NOW())"), {"id": ids["conv"], "wa": WA})
        c.execute(sa.text(
            "INSERT INTO conversations (id, wa_id, channel, external_id, intercept_mode, status, created_at, updated_at) "
            "VALUES (:id, NULL, 'messenger', :p, 'ai', 'open', NOW(), NOW())"), {"id": ids["mconv"], "p": PSID})
        c.execute(sa.text(
            "INSERT INTO messages (id, wa_id, channel, external_id, conversation_id, direction, sender, text, created_at) "
            "VALUES (:id, :wa, 'whatsapp', :wa, :c, 'inbound', 'user', 'hi', NOW() - interval '3 hours')"),
            {"id": str(uuid.uuid4()), "wa": WA, "c": ids["conv"]})
    eng.dispose()

    async def _db():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app = FastAPI()
    app.include_router(admin.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = _db
    app.state.redis = None
    with TestClient(app) as cl:
        yield types.SimpleNamespace(client=cl, db_url=fresh_db, ids=ids)


def _call(env, cid, *, status, direction="inbound", agent=None, duration=None, minutes_ago=60,
          channel="whatsapp", recording=None, transcript_status="none", summary=None, insights=None,
          follow_up_done=False, voicemail=None):
    eng = sa.create_engine(env.db_url)
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO calls (id, call_id, wa_id, channel, external_id, direction, status, agent_id, duration, "
            "started_at, answered_at, ended_at, recording_url, transcript_status, summary, insights, "
            "follow_up_done_at, voicemail_message_id) VALUES (:id, :cid, :wa, :ch, :ext, :dir, :st, :ag, :dur, "
            "NOW() - make_interval(mins => :m), CASE WHEN :dur IS NULL THEN NULL ELSE NOW() - make_interval(mins => :m) END, "
            "NOW() - make_interval(mins => :m), :rec, :ts, :sum, CAST(:ins AS JSONB), "
            "CASE WHEN :fud THEN NOW() ELSE NULL END, :vm)"),
            {"id": str(uuid.uuid4()), "cid": cid, "wa": WA if channel == "whatsapp" else None, "ch": channel,
             "ext": PSID if channel == "messenger" else None, "dir": direction, "st": status,
             "ag": env.ids[agent] if agent else None, "dur": duration, "m": minutes_ago, "rec": recording,
             "ts": transcript_status, "sum": summary, "ins": json.dumps(insights) if insights else None,
             "fud": follow_up_done, "vm": voicemail})
    eng.dispose()


def _calls_in_thread(env, conv="conv"):
    r = env.client.get(f"/api/admin/conversations/{env.ids[conv]}/messages", headers=_as(env.ids["ann"]))
    assert r.status_code == 200, r.text
    return {i["call"]["call_id"]: i for i in r.json() if i.get("event_kind") == "call"}, r.content


def test_every_outcome_reaches_the_thread_with_what_the_card_reads(env):
    _call(env, "wacid.ANS", status="completed", agent="ann", duration=76, minutes_ago=300)
    _call(env, "wacid.MIS", status="missed", minutes_ago=200)
    _call(env, "wacid.DEC", status="declined", agent="ben", minutes_ago=180)
    _call(env, "wacid.CBK", status="callback", agent="ann", minutes_ago=170)
    _call(env, "wacid.OUT", status="completed", direction="outbound", agent="ben", duration=182, minutes_ago=150)
    _call(env, "wacid.NOA", status="no_answer", direction="outbound", agent="ben", minutes_ago=140)
    _call(env, "wacid.REJ", status="rejected", direction="outbound", agent="ben", minutes_ago=130)
    _call(env, "wacid.OLD", status="ended", agent="ann", duration=30, minutes_ago=120)
    calls, _ = _calls_in_thread(env)
    assert set(calls) == {"wacid.ANS", "wacid.MIS", "wacid.DEC", "wacid.CBK", "wacid.OUT",
                          "wacid.NOA", "wacid.REJ", "wacid.OLD"}
    ans = calls["wacid.ANS"]["call"]
    assert (ans["direction"], ans["status"], ans["agent_name"], ans["duration"]) == \
        ("inbound", "completed", "Ann Wanjiru", 76)
    assert calls["wacid.ANS"]["text"] == "Incoming call · 1:16"
    assert calls["wacid.MIS"]["text"] == "Missed call"
    assert calls["wacid.DEC"]["call"]["agent_name"] == "Ben Otieno"
    assert calls["wacid.CBK"]["text"] == "Missed call · call back"
    assert calls["wacid.OUT"]["text"] == "Outgoing call · 3:02"
    assert calls["wacid.NOA"]["text"] == "Outgoing call · no answer"
    assert calls["wacid.REJ"]["text"] == "Outgoing call · declined"
    assert calls["wacid.OLD"]["call"]["status"] == "completed"       # legacy "ended"
    for item in calls.values():
        c = item["call"]
        for k in ("direction", "status", "agent_name", "started_at", "duration", "channel",
                  "has_recording", "transcript_status", "follow_up_open", "summary", "insights",
                  "wa_id", "external_id", "has_voicemail"):
            assert k in c, (k, c)


def test_missed_call_is_owed_until_a_later_call_connects(env):
    _call(env, "wacid.M1", status="missed", minutes_ago=200)
    _call(env, "wacid.M2", status="missed", minutes_ago=100, follow_up_done=True)
    calls, _ = _calls_in_thread(env)
    assert calls["wacid.M1"]["call"]["follow_up_open"] is True
    assert calls["wacid.M2"]["call"]["follow_up_open"] is False
    _call(env, "wacid.LATER", status="completed", direction="outbound", agent="ann", duration=40, minutes_ago=50)
    calls, _ = _calls_in_thread(env)
    assert calls["wacid.M1"]["call"]["follow_up_open"] is False      # called back → returned


def test_recording_url_never_ships_in_the_thread_only_from_the_authorised_endpoint(env):
    _call(env, "wacid.REC", status="completed", agent="ann", duration=60,
          recording="https://neema.test/api/admin/media/call_0123abcd.webm", transcript_status="done",
          summary="Wants a red cope for Sunday", insights={"next_action": "Send the price",
                                                           "commitments": ["Deliver Friday"]})
    calls, raw = _calls_in_thread(env)
    c = calls["wacid.REC"]["call"]
    assert c["has_recording"] is True and c["transcript_status"] == "done"
    assert c["summary"] == "Wants a red cope for Sunday"
    assert c["insights"]["commitments"] == ["Deliver Friday"]
    assert b"call_0123abcd" not in raw                                 # not in the thread payload
    r = env.client.get("/api/admin/calls/wacid.REC/transcript", headers=_as(env.ids["ann"]))
    assert r.status_code == 200 and r.json()["recording_url"].endswith("call_0123abcd.webm")
    assert env.client.get("/api/admin/calls/wacid.REC/transcript").status_code in (401, 403)


def test_voicemail_call_is_flagged_and_its_audio_row_is_linked(env):
    _call(env, "wacid.VM", status="missed", minutes_ago=30, voicemail="wacid.VM")
    eng = sa.create_engine(env.db_url)
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO messages (id, wa_id, channel, external_id, conversation_id, direction, sender, text, "
            "media_type, media_url, raw_meta, created_at) VALUES (:id, :wa, 'whatsapp', :wa, :c, 'inbound', 'user', "
            "'', 'audio', 'https://neema.test/api/admin/media/wa_VM1.ogg', CAST(:m AS JSONB), NOW() - interval '29 minutes')"),
            {"id": str(uuid.uuid4()), "wa": WA, "c": env.ids["conv"],
             "m": json.dumps({"v": 1, "type": "audio", "kind": "voicemail", "call_id": "wacid.VM"})})
    eng.dispose()
    calls, _ = _calls_in_thread(env)
    assert calls["wacid.VM"]["call"]["has_voicemail"] is True
    assert calls["wacid.VM"]["text"] == "Missed call · voicemail"
    r = env.client.get(f"/api/admin/conversations/{env.ids['conv']}/messages", headers=_as(env.ids["ann"]))
    vm = [i for i in r.json() if (i.get("meta") or {}).get("kind") == "voicemail"]
    assert vm and vm[0]["meta"]["call_id"] == "wacid.VM"              # the card folds this in


def test_messenger_call_lands_in_the_messenger_thread(env):
    _call(env, "mcall.1", status="missed", channel="messenger", minutes_ago=20)
    calls, _ = _calls_in_thread(env, "mconv")
    c = calls["mcall.1"]["call"]
    assert c["channel"] == "messenger" and c["external_id"] == PSID and c["wa_id"] is None
    assert c["follow_up_open"] is True
    wa_calls, _ = _calls_in_thread(env, "conv")
    assert "mcall.1" not in wa_calls                                   # never in the WhatsApp thread


def test_thread_payload_cost_of_calls_is_bounded(env):
    """Measured, not assumed: 50 calls (the item cap) on one thread."""
    for i in range(55):
        _call(env, f"wacid.N{i}", status="missed" if i % 3 else "completed", agent="ann" if i % 3 == 0 else None,
              duration=60 if i % 3 == 0 else None, minutes_ago=10 + i)
    calls, raw = _calls_in_thread(env)
    assert len(calls) == 50                                            # the existing cap holds
    per_call = len(raw) / 51                                           # 50 calls + 1 message
    print(f"\n[measure] thread bytes={len(raw)} ≈{per_call:.0f} B per item")
    assert per_call < 2000
