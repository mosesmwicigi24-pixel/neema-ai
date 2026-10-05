"""Cycles 2-5 joined (integration, 2026-10-05), on a real Postgres: what the
call card and the voice-note bubble read, end to end through the thread
endpoint.

- A call row carries its transcript lifecycle FOLDED (transcript_state), the
  failure in words, the language, and whether words exist — for every state
  cycle 5 produces (queued / processing / done / silent / failed:<reason> /
  recorded / legacy pending + bare failed).
- A voice note carries transcript_status / transcript_note / translation on
  the thread page (the web client used to drop them on reload).
- A voicemail is an audio row that is ALSO a voice note: its transcript rides
  the same fields, so the card's voicemail shows the words.
- The live new_message event (native WhatsApp path) carries id, direction,
  created_at, meta and transcriptStatus together.
"""
import json
import uuid

import sqlalchemy as sa

from tests import test_call_cards_db as cards
from tests.test_security_db import _as, fresh_db  # noqa: F401 — the throwaway-database fixture

# The call-card module's fixture and helpers (bound, not imported by name, so
# a test's `env` parameter doesn't read as a redefinition).
env = cards.env
_call, _calls_in_thread, WA = cards._call, cards._calls_in_thread, cards.WA
pytestmark = cards.pytestmark


def _msg(env, *, text="", media_type=None, media_url=None, raw_meta=None, transcript_status=None,
         transcript_lang=None, translated_text=None, translated_from=None, minutes_ago=5):
    mid = str(uuid.uuid4())
    eng = sa.create_engine(env.db_url)
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO messages (id, wa_id, channel, external_id, conversation_id, direction, sender, text, "
            "media_type, media_url, raw_meta, transcript_status, transcript_lang, translated_text, translated_from, "
            "created_at) VALUES (:id, :wa, 'whatsapp', :wa, :c, 'inbound', 'user', :t, :mt, :mu, CAST(:m AS JSONB), "
            ":ts, :tl, :tt, :tf, NOW() - make_interval(mins => :ago))"),
            {"id": mid, "wa": WA, "c": env.ids["conv"], "t": text, "mt": media_type, "mu": media_url,
             "m": json.dumps(raw_meta) if raw_meta else None, "ts": transcript_status, "tl": transcript_lang,
             "tt": translated_text, "tf": translated_from, "ago": minutes_ago})
    eng.dispose()
    return mid


def _thread(env):
    r = env.client.get(f"/api/admin/conversations/{env.ids['conv']}/messages", headers=_as(env.ids["ann"]))
    assert r.status_code == 200, r.text
    return r.json()


def test_every_transcript_state_reaches_the_card_folded_with_its_reason(env):
    rec = "https://neema.test/api/admin/media/call_x.webm"
    _call(env, "wacid.Q", status="completed", duration=40, recording=rec, transcript_status="queued", minutes_ago=90)
    _call(env, "wacid.P", status="completed", duration=40, recording=rec, transcript_status="processing", minutes_ago=80)
    _call(env, "wacid.L", status="completed", duration=40, recording=rec, transcript_status="pending", minutes_ago=70)
    _call(env, "wacid.F", status="completed", duration=40, recording=rec,
          transcript_status="failed:over_budget", minutes_ago=60)
    _call(env, "wacid.F0", status="completed", duration=40, recording=rec, transcript_status="failed", minutes_ago=55)
    _call(env, "wacid.FA", status="completed", duration=40, recording=rec,
          transcript_status="failed:analysis", minutes_ago=52)
    _call(env, "wacid.R", status="completed", duration=40, recording=rec, transcript_status="recorded", minutes_ago=50)
    _call(env, "wacid.S", status="completed", duration=40, recording=rec, transcript_status="done",
          summary="No speech was captured on the recording.", minutes_ago=40)
    _call(env, "wacid.D", status="completed", duration=40, recording=rec, transcript_status="done",
          summary="Fr. Otieno wants 2 black clergy shirts, size 16, at KES 4,500 each.",
          insights={"prices": ["KES 4,500 per shirt"], "language": "Swahili"}, minutes_ago=30)
    eng = sa.create_engine(env.db_url)
    with eng.begin() as c:
        c.execute(sa.text("UPDATE calls SET transcript = 'Agent: Habari\nCustomer: Nataka shati', "
                          "transcript_lang = 'sw' WHERE call_id = 'wacid.D'"))
    eng.dispose()

    calls, _ = _calls_in_thread(env)
    st = {k: calls[k]["call"]["transcript_state"] for k in calls}
    assert st == {"wacid.Q": "queued", "wacid.P": "processing", "wacid.L": "queued",
                  "wacid.F": "failed", "wacid.F0": "failed", "wacid.FA": "failed",
                  "wacid.R": "recorded", "wacid.S": "done", "wacid.D": "done"}
    assert calls["wacid.F"]["call"]["transcript_failure"] == "today's transcription budget is used up"
    assert calls["wacid.F0"]["call"]["transcript_failure"] == "failed"   # legacy: no reason recorded
    assert "transcript is kept" in calls["wacid.FA"]["call"]["transcript_failure"]
    assert calls["wacid.Q"]["call"]["transcript_failure"] is None
    d = calls["wacid.D"]["call"]
    assert d["has_transcript"] is True and d["transcript_lang"] == "sw"
    assert d["insights"]["prices"] == ["KES 4,500 per shirt"]
    assert calls["wacid.S"]["call"]["has_transcript"] is False         # silent → nothing to open
    # The transcript words themselves never ride the thread payload.
    assert all("transcript" not in calls[k]["call"] for k in calls)

    r = env.client.get("/api/admin/calls/wacid.F/transcript", headers=_as(env.ids["ann"]))
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "failed" and body["failure"] == "today's transcription budget is used up"


def test_voice_note_state_and_translation_ride_the_thread_page(env):
    url = "https://neema.test/api/admin/media/wa_1.ogg"
    q = _msg(env, media_type="audio", media_url=url, transcript_status="queued", minutes_ago=9)
    d = _msg(env, text="Nataka shati mbili za kasisi", media_type="audio", media_url=url,
             transcript_status="done", transcript_lang="sw",
             translated_text="I want two clergy shirts", translated_from="Swahili", minutes_ago=8)
    f = _msg(env, media_type="audio", media_url=url, transcript_status="failed:over_budget", minutes_ago=7)
    s = _msg(env, media_type="audio", media_url=url, transcript_status="silent", minutes_ago=6)
    items = {i["id"]: i for i in _thread(env)}
    assert items[q]["transcript_status"] == "queued" and items[q]["transcript_note"] is None
    assert items[d]["text"] == "Nataka shati mbili za kasisi"
    assert items[d]["translation"] == "I want two clergy shirts"
    assert items[d]["translated_from"] == "Swahili" and items[d]["transcript_lang"] == "sw"
    assert items[f]["transcript_note"] == "today's transcription budget is used up"
    assert "no speech" in items[s]["transcript_note"]


def test_voicemail_carries_its_transcript_into_the_card(env):
    _call(env, "wacid.VMT", status="missed", minutes_ago=30, voicemail="wacid.VMT")
    vm = _msg(env, text="Hi, it's Fr. Otieno — call me back about the cassock.", media_type="audio",
              media_url="https://neema.test/api/admin/media/wa_vm.ogg", transcript_status="done",
              transcript_lang="en", raw_meta={"v": 1, "type": "audio", "kind": "voicemail", "call_id": "wacid.VMT"},
              minutes_ago=29)
    items = {i["id"]: i for i in _thread(env)}
    row = items[vm]
    assert row["meta"]["kind"] == "voicemail" and row["meta"]["call_id"] == "wacid.VMT"
    assert row["transcript_status"] == "done"
    assert row["text"].startswith("Hi, it's Fr. Otieno")


def test_native_live_event_carries_every_field_the_bubble_needs(env, monkeypatch):
    """The native WhatsApp path's new_message: id + direction + created_at +
    meta + transcriptStatus in ONE event (the two halves each added some)."""
    import asyncio
    from app.schemas.n8n import MessageDto
    from app.services import n8n_bridge as svc
    import app.database as database

    sent = []

    async def _cap(redis, channel, payload):
        sent.append((channel, payload))
    monkeypatch.setattr(svc, "_broadcast", _cap)

    async def go():
        async with database.AsyncSessionLocal() as db:
            mid = uuid.uuid4()
            dto = MessageDto(wa_id=WA, name="Fr. Otieno", direction="inbound", text="",
                             ts_ms=None, docid="wamid.LIVE1", media_type="audio",
                             media_url="https://neema.test/api/admin/media/wa_live.ogg",
                             media_id="m1", mime_type="audio/ogg",
                             raw_meta={"v": 1, "type": "audio", "kind": "voicemail", "call_id": "wacid.LIVE",
                                       "payload": {"secret": "x"}})
            await svc.upsert_message(db, None, dto, message_id=mid, transcript_status="queued")
            return mid
    mid = asyncio.run(go())
    ev = [p for _, p in sent if p.get("type") == "new_message"]
    assert ev, sent
    e = ev[-1]
    assert e["id"] == str(mid) and e["direction"] == "inbound" and e["created_at"]
    assert e["transcriptStatus"] == "queued"
    assert e["meta"]["kind"] == "voicemail" and "payload" not in e["meta"]   # redacted copy stays in the DB
