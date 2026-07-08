"""Unit tests for the Meta webhook — signature verification (security-critical)
and inbound identity capture — without booting the app or a DB. Requires Python
3.11.
"""
import asyncio
import hashlib
import hmac
import types

from app.routers import meta_webhook as mw
from app.core.config import settings


# ── X-Hub-Signature-256 verification ─────────────────────────────────────────

def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_valid_and_invalid(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_secret", "s3cr3t", raising=False)
    body = b'{"object":"page","entry":[]}'
    assert mw._valid_signature(body, _sign("s3cr3t", body)) is True
    assert mw._valid_signature(body, _sign("wrong", body)) is False
    assert mw._valid_signature(body, None) is False
    assert mw._valid_signature(body, "garbage") is False
    # tampered body → signature no longer matches
    assert mw._valid_signature(body + b"x", _sign("s3cr3t", body)) is False


def test_signature_skipped_when_no_secret(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    assert mw._valid_signature(b"anything", None) is True   # dev mode: skip


# ── Inbound identity capture ─────────────────────────────────────────────────

class _FakeDB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def test_capture_events_resolves_each_sender(monkeypatch):
    calls = []

    async def fake_resolve(db, channel, external_id, **kw):
        calls.append((channel, external_id, kw.get("source")))
        return types.SimpleNamespace(person_id="p")

    monkeypatch.setattr("app.services.identity.resolve_or_create_person", fake_resolve)

    payload = {
        "object": "page",
        "entry": [
            {"messaging": [
                {"sender": {"id": "PSID_1"}, "message": {"text": "hi"}},
                {"sender": {"id": "PSID_2"}, "message": {"text": "how much?"}},
                {"sender": {"id": "PAGE"}, "message": {"is_echo": True, "text": "our reply"}},  # skipped
                {"delivery": {"mids": ["m1"]}},                                                 # no sender → skipped
            ]},
        ],
    }
    db = _FakeDB()
    asyncio.run(mw._capture_events(db, "messenger", payload))

    assert [c[1] for c in calls] == ["PSID_1", "PSID_2"]         # echo + sender-less skipped
    assert all(c[0] == "messenger" and c[2] == "messenger_inbound" for c in calls)
    assert db.commits == 1


def test_capture_events_no_senders_does_not_commit(monkeypatch):
    async def fake_resolve(*a, **k):
        raise AssertionError("should not be called")

    monkeypatch.setattr("app.services.identity.resolve_or_create_person", fake_resolve)
    db = _FakeDB()
    asyncio.run(mw._capture_events(db, "instagram", {"object": "instagram", "entry": []}))
    assert db.commits == 0
