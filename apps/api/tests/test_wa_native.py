"""Native WhatsApp ingestion (the n8n replacement) — parser, debounce, media,
transcription fallback, and the flag gating that keeps production unchanged
until WHATSAPP_NATIVE is flipped.
"""
import asyncio
import json
import types

import app.main  # noqa: F401 — registers models
import app.services.wa_native as wn
from app.core.config import settings


def _payload(messages, contacts=None):
    return {"entry": [{"changes": [{"field": "messages", "value": {
        "messages": messages,
        "contacts": contacts or [],
    }}]}]}


# ── parsing every message shape Meta sends ───────────────────────────────────

def test_parses_text_with_profile_name():
    events = wn.parse_events(_payload(
        [{"from": "254700000001", "id": "wamid.1", "type": "text",
          "timestamp": "1753600000", "text": {"body": " Hi Bethany House "}}],
        contacts=[{"wa_id": "254700000001", "profile": {"name": "Cynthia Kaffi"}}]))
    assert len(events) == 1
    e = events[0]
    assert e["wa_id"] == "254700000001" and e["wamid"] == "wamid.1"
    assert e["name"] == "Cynthia Kaffi"
    assert e["text"] == "Hi Bethany House"
    assert e["media"] is None
    assert e["ts_ms"] == 1753600000000


def test_parses_interactive_button_and_location_and_contacts():
    events = wn.parse_events(_payload([
        {"from": "254700000001", "id": "w1", "type": "interactive",
         "interactive": {"button_reply": {"id": "b1", "title": "Yes, order it"}}},
        {"from": "254700000001", "id": "w2", "type": "location",
         "location": {"latitude": -1.28, "longitude": 36.82, "name": "Nairobi CBD"}},
        {"from": "254700000001", "id": "w3", "type": "contacts",
         "contacts": [{"name": {"formatted_name": "Rev Grace"}}]},
    ]))
    assert events[0]["text"] == "Yes, order it"
    assert "Nairobi CBD" in events[1]["text"] and "📍" in events[1]["text"]
    assert "Rev Grace" in events[2]["text"]


def test_parses_media_kinds_with_captions():
    events = wn.parse_events(_payload([
        {"from": "254700000001", "id": "w1", "type": "image",
         "image": {"id": "MEDIA1", "mime_type": "image/jpeg", "caption": "this one?"}},
        {"from": "254700000001", "id": "w2", "type": "audio",
         "audio": {"id": "MEDIA2", "mime_type": "audio/ogg"}},
        {"from": "254700000001", "id": "w3", "type": "document",
         "document": {"id": "MEDIA3", "mime_type": "application/pdf", "filename": "sizes.pdf"}},
        {"from": "254700000001", "id": "w4", "type": "sticker",
         "sticker": {"id": "MEDIA4", "mime_type": "image/webp"}},
    ]))
    img, aud, doc, stk = events
    assert img["media"]["kind"] == "image" and img["media"]["caption"] == "this one?"
    assert img["text"] == "this one?"          # caption doubles as the text
    assert aud["media"]["kind"] == "audio"
    assert doc["media"]["filename"] == "sizes.pdf"
    assert stk["media"]["kind"] == "image"      # stickers ride the image path


def test_statuses_and_foreign_fields_are_dropped():
    payload = {"entry": [{"changes": [
        {"field": "messages", "value": {"statuses": [{"id": "s1", "status": "read"}]}},
        {"field": "calls", "value": {"calls": [{"id": "c1"}]}},
    ]}]}
    assert wn.parse_events(payload) == []
    # malformed rows never crash the parser
    assert wn.parse_events(_payload([{"type": "text"}])) == []
    assert wn.parse_events({}) == []


# ── the debounce: rapid-fire messages → ONE combined reply ───────────────────

class _Redis:
    def __init__(self):
        self.kv, self.lists = {}, {}
    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        return True
    async def get(self, k):
        return self.kv.get(k)
    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]
    async def expire(self, k, ttl):
        return True
    async def rpush(self, k, v):
        self.lists.setdefault(k, []).append(v)
    async def lrange(self, k, a, b):
        return list(self.lists.get(k, []))
    async def delete(self, k):
        self.lists.pop(k, None)
        self.kv.pop(k, None)


def test_debounce_supersede_only_the_last_token_flushes():
    r = _Redis()

    async def go():
        t1 = await wn._enqueue(r, "254700", "first message", None)
        t2 = await wn._enqueue(r, "254700", "second message", None)
        stale = await wn._drain(r, "254700", t1)       # superseded → no-op
        assert stale is None
        text, media = await wn._drain(r, "254700", t2)  # the live token gets BOTH
        assert text == "first message\nsecond message"
        assert media is None
        # buffer is consumed — a re-drain of the same token finds nothing
        again = await wn._drain(r, "254700", t2)
        assert again == ("", None)

    asyncio.run(go())


def test_debounce_prefers_the_image_across_the_buffer():
    r = _Redis()

    async def go():
        await wn._enqueue(r, "254700", "look at this", {"type": "image", "url": "u1"})
        t = await wn._enqueue(r, "254700", "do you have it?", None)
        text, media = await wn._drain(r, "254700", t)
        assert "look at this" in text and "do you have it?" in text
        assert media == {"type": "image", "url": "u1"}   # the photo survives

    asyncio.run(go())


def test_reply_respects_human_intercept(monkeypatch):
    """Parity with /profile: a human-handled conversation gets NO AI reply."""
    from app.models.conversation import InterceptMode

    scheduled = {"n": 0}

    async def fake_schedule(redis, wa_id, text, dedup, media=None):
        scheduled["n"] += 1
        return True

    conv = types.SimpleNamespace(intercept_mode=InterceptMode.human)

    class _DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, *a, **k):
            return types.SimpleNamespace(scalar_one_or_none=lambda: conv)

    monkeypatch.setattr("app.agent.runtime.schedule_reply", fake_schedule)
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _DB())
    asyncio.run(wn._reply_after_debounce(None, "254700", None, "hi", None))
    assert scheduled["n"] == 0


def test_reply_schedules_for_ai_mode(monkeypatch):
    from app.models.conversation import InterceptMode

    captured = {}

    async def fake_schedule(redis, wa_id, text, dedup, media=None):
        captured.update(wa_id=wa_id, text=text, dedup=dedup, media=media)
        return True

    async def fake_reconcile(db, redis, wa_id, text):
        captured["reconciled"] = True

    conv = types.SimpleNamespace(intercept_mode=InterceptMode.ai)

    class _DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, *a, **k):
            return types.SimpleNamespace(scalar_one_or_none=lambda: conv)

    monkeypatch.setattr("app.agent.runtime.schedule_reply", fake_schedule)
    monkeypatch.setattr("app.services.identity.reconcile_waref", fake_reconcile)
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _DB())
    asyncio.run(wn._reply_after_debounce(None, "254700", None, "I want bread", None))
    assert captured["wa_id"] == "254700" and captured["text"] == "I want bread"
    assert captured["reconciled"] is True      # the wa.me ref bridge still runs


# ── transcription falls back, never blocks ───────────────────────────────────

def test_transcription_falls_back_to_openai(monkeypatch):
    from app.services import call_transcribe as ct

    def boom(path):
        raise RuntimeError("faster-whisper not installed")

    monkeypatch.setattr(ct, "_transcribe_sync", boom)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(ct, "_transcribe_openai",
                        lambda p: ("Nataka mkate wa komunio", "sw"))
    assert wn._transcribe_path_sync("/x.ogg") == "Nataka mkate wa komunio"


def test_transcription_returns_none_when_nothing_works(monkeypatch):
    from app.services import call_transcribe as ct

    def boom(path):
        raise RuntimeError("no")

    monkeypatch.setattr(ct, "_transcribe_sync", boom)
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    assert wn._transcribe_path_sync("/x.ogg") is None


# ── native is the ONLY pipeline (n8n retired 2026-07-30, code 2026-08-11) ────

def test_front_door_is_native_only():
    import inspect
    from app.routers import whatsapp_webhook as ww
    # process_payload is shared by /api/wa/webhook and the /api/meta/webhook
    # delegation, so behaviour is identical from either door.
    src = inspect.getsource(ww.process_payload)
    assert "wa_native" in src                     # in-process pipeline
    # the retired forward machinery must be GONE, not merely off
    module_src = inspect.getsource(ww)
    assert "_forward_to_n8n" not in module_src
    assert "whatsapp_native" not in module_src    # no flag — native unconditionally
    # and the route itself must route through the shared front door
    assert "process_payload" in inspect.getsource(ww.receive)


def test_retired_flags_are_gone_and_debounce_stays():
    from app.core.config import Settings
    for retired in ("whatsapp_native", "whatsapp_forward_url",
                    "tier2_all", "tier2_enabled_wa_ids"):
        assert retired not in Settings.model_fields, retired
    assert Settings.model_fields["whatsapp_debounce_seconds"].default == 15


# ── inventory-driven parity: doc requests, first contact, 15s window ─────────

def test_doc_requests_go_to_a_human_photo_requests_do_not():
    assert wn._is_doc_request("can you send me the price list pdf") is True
    assert wn._is_doc_request("nitumie katalogi") is True
    assert wn._is_doc_request("I need the brochure please") is True
    # photos are Neema's job now — never escalated
    assert wn._is_doc_request("send me a photo of the cassock") is False
    assert wn._is_doc_request("do you have bread images?") is False
    # mentioning a word without asking is not a request
    assert wn._is_doc_request("the pdf was helpful") is False
    assert wn._is_doc_request("") is False and wn._is_doc_request(None) is False


def test_doc_request_escalates_instead_of_scheduling(monkeypatch):
    from app.models.conversation import InterceptMode

    scheduled = {"n": 0}
    escalated = {"n": 0}

    async def fake_schedule(*a, **k):
        scheduled["n"] += 1
        return True

    async def fake_escalate(redis, wa_id, text):
        escalated["n"] += 1

    monkeypatch.setattr("app.agent.runtime.schedule_reply", fake_schedule)
    monkeypatch.setattr(wn, "_escalate_doc_request", fake_escalate)
    asyncio.run(wn._reply_after_debounce(None, "254700", None,
                                         "please send the price list pdf", None))
    assert escalated["n"] == 1 and scheduled["n"] == 0


def test_debounce_default_is_the_value_n8n_actually_ran():
    from app.core.config import Settings
    assert Settings.model_fields["whatsapp_debounce_seconds"].default == 15
