"""Unit tests for the Meta webhook — signature verification (security-critical)
and inbound identity capture — without booting the app or a DB. Requires Python
3.11.
"""
import asyncio
import hashlib
import hmac
import types

# Full ORM registry so Message() (built inside _capture_events) configures.
import app.models.agent, app.models.conversation, app.models.intercept  # noqa: F401
import app.models.person, app.models.user  # noqa: F401
from app.models.message import Message
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
    def __init__(self, existing_mid=None):
        self._existing_mid = existing_mid   # a mid already stored → dedup path
        self.commits = 0
        self.added = []

    async def execute(self, stmt):          # the dedup SELECT
        return types.SimpleNamespace(scalar_one_or_none=lambda: self._existing_mid)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


class _FakeConv:
    def __init__(self, cid="c1"):
        self.id = cid
        self.last_message_at = None
        self.last_message_preview = None


def _patch(monkeypatch, calls):
    async def fake_person(db, channel, external_id, **kw):
        calls.setdefault("persons", []).append((channel, external_id, kw.get("source")))
        return types.SimpleNamespace(person_id="p-" + external_id)

    async def fake_conv(db, channel, external_id, **kw):
        calls.setdefault("convs", []).append((channel, external_id))
        return _FakeConv()

    monkeypatch.setattr("app.services.identity.resolve_or_create_person", fake_person)
    monkeypatch.setattr("app.services.channel.get_or_create_conversation", fake_conv)


def test_capture_creates_person_conversation_and_message(monkeypatch):
    calls = {}
    _patch(monkeypatch, calls)
    payload = {
        "object": "page",
        "entry": [{"messaging": [
            {"sender": {"id": "PSID_1"}, "message": {"mid": "m1", "text": "hi"}},
            {"sender": {"id": "PSID_2"}, "message": {"mid": "m2", "text": "how much?"}},
            {"sender": {"id": "PAGE"}, "message": {"is_echo": True, "text": "reply"}},   # skipped
            {"delivery": {"mids": ["x"]}},                                              # no sender → skipped
        ]}],
    }
    db = _FakeDB()
    asyncio.run(mw._capture_events(db, "messenger", payload))

    assert [p[1] for p in calls["persons"]] == ["PSID_1", "PSID_2"]   # echo + sender-less skipped
    assert calls["convs"] == [("messenger", "PSID_1"), ("messenger", "PSID_2")]
    msgs = [o for o in db.added if isinstance(o, Message)]
    assert len(msgs) == 2 and all(m.channel == "messenger" and m.wa_id is None for m in msgs)
    assert db.commits == 1


def test_capture_dedupes_on_message_id(monkeypatch):
    calls = {}
    _patch(monkeypatch, calls)
    payload = {"object": "page", "entry": [{"messaging": [
        {"sender": {"id": "PSID_1"}, "message": {"mid": "already-seen", "text": "hi"}},
    ]}]}
    db = _FakeDB(existing_mid="already-seen")   # the dedup SELECT finds it
    asyncio.run(mw._capture_events(db, "messenger", payload))
    assert calls.get("persons", []) == []       # skipped before resolving
    assert db.commits == 0


def test_capture_no_senders_does_not_commit(monkeypatch):
    _patch(monkeypatch, {})
    db = _FakeDB()
    asyncio.run(mw._capture_events(db, "instagram", {"object": "instagram", "entry": []}))
    assert db.commits == 0
