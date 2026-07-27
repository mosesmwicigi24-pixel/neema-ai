"""WhatsApp Cloud API front door: transparent forward to n8n + calls tap.

The messaging path must be byte-for-byte unaffected (we forward the raw body);
inbound calls must ring the dashboard and dedupe on Meta retries.
"""
import asyncio
import hashlib
import hmac
import json
import types

from app.routers import whatsapp_webhook as ww
from app.core.config import settings


def _sign(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class _FakeRedis:
    def __init__(self):
        self.store, self.published = {}, []
    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return False
        self.store[k] = v
        return True
    async def publish(self, ch, msg):
        self.published.append((ch, msg))


def _req(redis):
    app = types.SimpleNamespace(state=types.SimpleNamespace(redis=redis))
    return types.SimpleNamespace(app=app)


def test_verify_handshake(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_verify_token", "tok", raising=False)
    monkeypatch.setattr(settings, "meta_verify_token", "", raising=False)

    class _P:
        def __init__(self, d): self._d = d
        def get(self, k, default=None): return self._d.get(k, default)
    good = types.SimpleNamespace(query_params=_P(
        {"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "123"}))
    resp = asyncio.run(ww.verify(good))
    assert resp.body == b"123"
    bad = types.SimpleNamespace(query_params=_P(
        {"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "123"}))
    assert asyncio.run(ww.verify(bad)).status_code == 403


def test_incoming_call_rings_and_dedupes(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)   # skip sig in test
    r = _FakeRedis()
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "calls", "value": {
            "metadata": {"phone_number_id": "PNID"},
            "calls": [{"id": "wacid.1", "event": "connect", "from": "254700",
                       "to": "254785", "session": {"sdp_type": "offer", "sdp": "v=0..."}}],
        }}]}],
    }
    asyncio.run(ww._handle_calls(_req(r), payload))
    assert any(t == "ws:channel:calls" and json.loads(m)["type"] == "incoming_call"
               for t, m in r.published)
    assert json.loads(r.store["wa:call:offer:wacid.1"])["sdp"] == "v=0..."   # offer stashed

    # A Meta retry of the SAME connect must NOT ring again.
    r.published.clear()
    asyncio.run(ww._handle_calls(_req(r), payload))
    assert r.published == []


def test_forward_relays_raw_body(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_forward_url", "https://n8n.example/wa", raising=False)
    captured = {}

    class _Resp:
        is_success = True
        status_code = 200
        text = "ok"

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, content=None, headers=None, timeout=None):
            captured.update(url=url, content=content, headers=headers)
            return _Resp()

    monkeypatch.setattr(ww.httpx, "AsyncClient", lambda *a, **k: _Client())
    raw = b'{"object":"whatsapp_business_account","entry":[]}'
    ok = asyncio.run(ww._forward_to_n8n(raw, _sign("s", raw)))
    assert ok is True
    assert captured["content"] == raw                       # byte-for-byte
    assert captured["url"] == "https://n8n.example/wa"
    assert "X-Hub-Signature-256" in captured["headers"]     # signature preserved


# ── Voice-calling accept flow ────────────────────────────────────────────────

def test_ice_servers_builds_from_config(monkeypatch):
    from app.services.wa_calling import ice_servers
    from app.core.config import settings
    monkeypatch.setattr(settings, "turn_url", "turn:turn.bethanyhouse.co.ke:3478", raising=False)
    monkeypatch.setattr(settings, "turn_username", "neema", raising=False)
    monkeypatch.setattr(settings, "turn_credential", "sec", raising=False)
    monkeypatch.setattr(settings, "stun_url", "stun:stun.l.google.com:19302", raising=False)
    s = ice_servers()
    assert s[0] == {"urls": "turn:turn.bethanyhouse.co.ke:3478", "username": "neema", "credential": "sec"}
    assert {"urls": "stun:stun.l.google.com:19302"} in s
    assert any("openrelay" in str(e.get("urls")) for e in s)   # public relay fallback present
    # No TURN configured → STUN + the public relay fallback (never empty).
    monkeypatch.setattr(settings, "turn_url", "", raising=False)
    s2 = ice_servers()
    assert {"urls": "stun:stun.l.google.com:19302"} in s2
    assert any("openrelay" in str(e.get("urls")) for e in s2)


def test_call_action_posts_pre_accept_then_accept(monkeypatch):
    from app.services import wa_calling
    from app.core.config import settings
    monkeypatch.setattr(settings, "waba_token", "T", raising=False)
    monkeypatch.setattr(settings, "waba_phone_number_id", "752950797900067", raising=False)
    sent = []

    class _Resp:
        is_success = True
        status_code = 200
        content = b"{}"
        def json(self): return {}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None, timeout=None):
            sent.append(json)
            return _Resp()

    monkeypatch.setattr(wa_calling.httpx, "AsyncClient", lambda *a, **k: _Client())
    asyncio.run(wa_calling.pre_accept("wacid.1", "v=0 answer"))
    asyncio.run(wa_calling.accept("wacid.1", "v=0 answer"))
    asyncio.run(wa_calling.terminate("wacid.1"))
    assert sent[0]["action"] == "pre_accept" and sent[0]["session"]["sdp_type"] == "answer"
    assert sent[1]["action"] == "accept"
    assert sent[2] == {"messaging_product": "whatsapp", "call_id": "wacid.1", "action": "terminate"}


# ── One front door, wherever Meta delivers ───────────────────────────────────
# The Meta app's WhatsApp callback URL may point at /api/wa/webhook (correct) or
# — as misconfigured deployments do — at /api/meta/webhook. WhatsApp payloads
# must be processed identically from either route, never silently swallowed.

def test_meta_route_delegates_whatsapp_object_to_wa_front_door(monkeypatch):
    from app.routers import meta_webhook as mw
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    seen = {}

    async def fake_process(request, raw, sig):
        seen.update(raw=raw, sig=sig)
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("EVENT_RECEIVED")

    monkeypatch.setattr(ww, "process_payload", fake_process)

    captured_channels = []
    async def fake_capture(db, channel, payload, redis=None):
        captured_channels.append(channel)
    monkeypatch.setattr(mw, "_capture_events", fake_capture)
    monkeypatch.setattr(mw, "_capture_comment_events", fake_capture)

    raw = json.dumps({"object": "whatsapp_business_account",
                      "entry": [{"changes": [{"field": "messages", "value": {}}]}]}).encode()

    class _Req:
        headers = {"x-hub-signature-256": "sha256=irrelevant"}
        app = types.SimpleNamespace(state=types.SimpleNamespace(redis=None))
        async def body(self): return raw
        async def json(self): return json.loads(raw)

    resp = asyncio.run(mw.receive_webhook(_Req(), db=None))
    assert resp.body == b"EVENT_RECEIVED"
    assert seen["raw"] == raw                 # handed to the WhatsApp front door
    assert captured_channels == []            # NOT treated as a Messenger event


def test_meta_route_still_captures_page_and_instagram(monkeypatch):
    from app.routers import meta_webhook as mw
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    captured = []

    async def fake_capture(db, channel, payload, redis=None):
        captured.append(channel)
    monkeypatch.setattr(mw, "_capture_events", fake_capture)
    monkeypatch.setattr(mw, "_capture_comment_events", fake_capture)

    async def fake_process(request, raw, sig):          # must NOT be called
        raise AssertionError("page payload must not hit the WhatsApp door")
    monkeypatch.setattr(ww, "process_payload", fake_process)

    raw = json.dumps({"object": "page", "entry": []}).encode()

    class _Req:
        headers = {}
        app = types.SimpleNamespace(state=types.SimpleNamespace(redis=None))
        async def body(self): return raw
        async def json(self): return json.loads(raw)

    resp = asyncio.run(mw.receive_webhook(_Req(), db=None))
    assert resp.body == b"EVENT_RECEIVED"
    assert captured == ["messenger", "messenger"]


def test_signature_prefers_whatsapp_app_secret(monkeypatch):
    body = b'{"object":"whatsapp_business_account"}'
    # Same app for both products (the common case): meta secret validates.
    monkeypatch.setattr(settings, "whatsapp_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "meta_app_secret", "meta-secret", raising=False)
    assert ww._valid_signature(body, _sign("meta-secret", body))
    # Separate WhatsApp app: ITS secret must win over the Messenger one.
    monkeypatch.setattr(settings, "whatsapp_app_secret", "wa-secret", raising=False)
    assert ww._valid_signature(body, _sign("wa-secret", body))
    assert not ww._valid_signature(body, _sign("meta-secret", body))


def test_native_mode_processes_via_shared_front_door(monkeypatch):
    """POST /api/wa/webhook in native mode must run wa_native, not the forward."""
    from app.services import wa_native
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "whatsapp_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "whatsapp_native", True, raising=False)
    handled, forwarded = [], []

    async def fake_handle(payload, redis):
        handled.append(payload)
        return 1, 0
    monkeypatch.setattr(wa_native, "handle_webhook", fake_handle)

    async def fake_forward(raw, sig):
        forwarded.append(raw)
        return True
    monkeypatch.setattr(ww, "_forward_to_n8n", fake_forward)

    raw = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()

    class _Req:
        headers = {}
        app = types.SimpleNamespace(state=types.SimpleNamespace(redis=None))
        async def body(self): return raw

    resp = asyncio.run(ww.receive(_Req()))
    assert resp.body == b"EVENT_RECEIVED"
    assert len(handled) == 1 and forwarded == []


def test_meta_route_rejects_forged_whatsapp_payload(monkeypatch):
    """META_APP_SECRET unset (its own validator accepts anything) must NOT open
    an unauthenticated side door: the WhatsApp validator gates the delegation."""
    from app.routers import meta_webhook as mw
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "whatsapp_app_secret", "wa-secret", raising=False)

    async def fake_process(request, raw, sig):
        raise AssertionError("forged payload must not reach the WhatsApp door")
    monkeypatch.setattr(ww, "process_payload", fake_process)

    raw = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()

    class _Req:
        headers = {"x-hub-signature-256": _sign("wrong-secret", raw)}
        app = types.SimpleNamespace(state=types.SimpleNamespace(redis=None))
        async def body(self): return raw
        async def json(self): return json.loads(raw)

    assert asyncio.run(mw.receive_webhook(_Req(), db=None)).status_code == 403


def test_meta_route_delegates_split_app_whatsapp_payload(monkeypatch):
    """WhatsApp product in a DIFFERENT Meta app: the payload is signed with the
    WhatsApp app's secret, fails this route's meta-secret check, and must STILL
    be delegated (the WhatsApp validator is the authority for these payloads)."""
    from app.routers import meta_webhook as mw
    monkeypatch.setattr(settings, "meta_app_secret", "messenger-secret", raising=False)
    monkeypatch.setattr(settings, "whatsapp_app_secret", "wa-secret", raising=False)
    seen = {}

    async def fake_process(request, raw, sig):
        seen["raw"] = raw
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("EVENT_RECEIVED")
    monkeypatch.setattr(ww, "process_payload", fake_process)

    raw = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()

    class _Req:
        headers = {"x-hub-signature-256": _sign("wa-secret", raw)}
        app = types.SimpleNamespace(state=types.SimpleNamespace(redis=None))
        async def body(self): return raw
        async def json(self): return json.loads(raw)

    resp = asyncio.run(mw.receive_webhook(_Req(), db=None))
    assert resp.body == b"EVENT_RECEIVED" and seen["raw"] == raw


def test_native_mode_bounces_when_ingest_failed(monkeypatch):
    """A failed ingest must return 502 so Meta redelivers — never acked-and-lost."""
    from app.services import wa_native
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "whatsapp_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "whatsapp_native", True, raising=False)

    async def fake_handle(payload, redis):
        return 0, 1
    monkeypatch.setattr(wa_native, "handle_webhook", fake_handle)

    raw = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()

    class _Req:
        headers = {}
        app = types.SimpleNamespace(state=types.SimpleNamespace(redis=None))
        async def body(self): return raw

    assert asyncio.run(ww.receive(_Req())).status_code == 502


def test_calls_tap_failure_does_not_block_ingestion(monkeypatch):
    """A redis blip in the calls tap must not cost the customer messages riding
    in the same webhook delivery."""
    from app.services import wa_native
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "whatsapp_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "whatsapp_native", True, raising=False)

    async def bad_calls(request, payload):
        raise RuntimeError("redis blip")
    monkeypatch.setattr(ww, "_handle_calls", bad_calls)

    handled = []
    async def fake_handle(payload, redis):
        handled.append(payload)
        return 1, 0
    monkeypatch.setattr(wa_native, "handle_webhook", fake_handle)

    raw = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()

    class _Req:
        headers = {}
        app = types.SimpleNamespace(state=types.SimpleNamespace(redis=None))
        async def body(self): return raw

    resp = asyncio.run(ww.receive(_Req()))
    assert resp.body == b"EVENT_RECEIVED" and len(handled) == 1


def test_ingest_failure_releases_wamid_guard(monkeypatch):
    """The permanent seen-mark burns only after persistence: a DB failure
    releases the guard so Meta's redelivery can reprocess the message."""
    import pytest
    from app.services import wa_native as wn
    import app.database as adb

    class _R:
        def __init__(self): self.store = {}
        async def get(self, k): return self.store.get(k)
        async def set(self, k, v, nx=False, ex=None):
            if nx and k in self.store: return False
            self.store[k] = v
            return True
        async def delete(self, k): self.store.pop(k, None)

    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(adb, "AsyncSessionLocal", boom)

    r = _R()
    event = {"wa_id": "254700000001", "wamid": "wamid.X", "name": None,
             "type": "text", "text": "hi", "media": None, "ts_ms": None}
    with pytest.raises(RuntimeError):
        asyncio.run(wn._ingest_one(event, r))
    assert "wa:native:seen:wamid.X" not in r.store        # not burned
    assert "wa:native:inflight:wamid.X" not in r.store    # guard released

    # And a duplicate delivery of an ALREADY-SEEN wamid is skipped silently.
    r.store["wa:native:seen:wamid.X"] = "1"
    asyncio.run(wn._ingest_one(event, r))                 # boom not reached
