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
    assert any(t == "ws:calls" and json.loads(m)["type"] == "incoming_call"
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
    # No TURN configured → just STUN (same-network fallback).
    monkeypatch.setattr(settings, "turn_url", "", raising=False)
    assert ice_servers() == [{"urls": "stun:stun.l.google.com:19302"}]


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
