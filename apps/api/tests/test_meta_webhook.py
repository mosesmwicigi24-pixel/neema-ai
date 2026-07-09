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
        from app.models.conversation import InterceptMode
        self.id = cid
        self.last_message_at = None
        self.last_message_preview = None
        self.intercept_mode = InterceptMode.ai


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


def test_event_media_extracts_attachments():
    # image via payload.url
    assert mw._event_media({"attachments": [
        {"type": "image", "payload": {"url": "https://scontent.xx/p.jpg"}}]}) == (
        "image", "https://scontent.xx/p.jpg")
    # fallback pointing at a real CDN asset → treated as an image
    assert mw._event_media({"attachments": [
        {"type": "fallback", "payload": None, "url": "https://lookaside.fbsbx.com/x.jpg"}]}) == (
        "image", "https://lookaside.fbsbx.com/x.jpg")
    # fallback pointing at a share redirect → treated as a file/link
    assert mw._event_media({"attachments": [
        {"type": "fallback", "url": "https://l.facebook.com/l.php?u=http://ex.com"}]}) == (
        "file", "https://l.facebook.com/l.php?u=http://ex.com")
    # no attachments
    assert mw._event_media({"text": "hi"}) == (None, None)


def test_capture_stores_media_url_and_type(monkeypatch):
    calls = {}
    _patch(monkeypatch, calls)
    payload = {"object": "page", "entry": [{"messaging": [
        {"sender": {"id": "PSID_1"}, "message": {"mid": "img1", "attachments": [
            {"type": "image", "payload": {"url": "https://scontent.xx/p.jpg"}}]}},
    ]}]}
    db = _FakeDB()
    asyncio.run(mw._capture_events(db, "messenger", payload))
    msg = next(o for o in db.added if isinstance(o, Message))
    assert msg.media_type == "image" and msg.media_url == "https://scontent.xx/p.jpg"
    assert msg.text == "[image]"        # placeholder cleaned from "[fallback]"/none


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


# ── Neema-answers-Messenger (agent auto-reply) ───────────────────────────────

def test_messenger_agent_tool_set_is_read_only():
    """Messenger must NOT expose the phone/hub order tools — it can only answer
    from the catalogue and hand off. Prevents phone-less bad orders."""
    from app.agent.runtime import MESSENGER_TOOLS
    names = {t["name"] for t in MESSENGER_TOOLS}
    assert names == {"search_catalog", "remember", "handoff_to_human"}
    assert "create_order" not in names and "update_cart" not in names


def test_messenger_addendum_currency_and_routes_to_whatsapp():
    from app.agent.runtime import _meta_addendum
    # Messenger/IG default to USD (no phone → not +254); route checkout to WhatsApp.
    usd = _meta_addendum().lower()
    assert "usd" in usd and "whatsapp" in usd and "convert" in usd
    # A Kenyan-context caller (KES) is quoted in shillings instead.
    kes = _meta_addendum("KES").lower()
    assert "kes" in kes and "whatsapp" in kes


def test_capture_schedules_agent_reply_only_when_enabled(monkeypatch):
    calls = []

    async def fake_person(db, channel, external_id, **kw):
        return types.SimpleNamespace(person_id="p")

    async def fake_conv(db, channel, external_id, **kw):
        return _FakeConv()

    async def fake_sched(redis, channel, external_id, text, dedup_id=None):
        calls.append((channel, external_id, text, dedup_id))

    monkeypatch.setattr("app.services.identity.resolve_or_create_person", fake_person)
    monkeypatch.setattr("app.services.channel.get_or_create_conversation", fake_conv)
    import app.agent.runtime as rt
    monkeypatch.setattr(rt, "schedule_meta_reply", fake_sched)

    payload = {"object": "page", "entry": [{"messaging": [
        {"sender": {"id": "PSID_1"}, "message": {"mid": "m1", "text": "how much for a cassock?"}},
        {"sender": {"id": "PSID_2"}, "message": {"mid": "m2", "attachments": [{"type": "image"}]}},  # no text → no reply
    ]}]}

    # disabled (default) → no agent reply
    monkeypatch.setattr(settings, "meta_agent_reply", False, raising=False)
    asyncio.run(mw._capture_events(_FakeDB(), "messenger", payload))
    assert calls == []

    # enabled → replies only to the real-text turn
    monkeypatch.setattr(settings, "meta_agent_reply", True, raising=False)
    asyncio.run(mw._capture_events(_FakeDB(), "messenger", payload))
    assert calls == [("messenger", "PSID_1", "how much for a cassock?", "m1")]


# ── Facebook/Instagram comment engagement ────────────────────────────────────

def test_parse_comment_feed_and_instagram_and_ignores_noise():
    feed = mw._parse_comment({"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": "c1", "message": "How much?",
        "from": {"id": "U1", "name": "Jane Doe"}, "post_id": "P1"}})
    assert feed["comment_id"] == "c1" and feed["from_id"] == "U1"
    assert feed["post_id"] == "P1" and feed["from_name"] == "Jane Doe"

    ig = mw._parse_comment({"field": "comments", "value": {
        "id": "ig1", "text": "Price?", "from": {"id": "IG1", "username": "jane"},
        "media": {"id": "M1"}}})
    assert ig["comment_id"] == "ig1" and ig["from_id"] == "IG1" and ig["post_id"] == "M1"

    # likes, edits/removes, and non-comment fields are ignored
    assert mw._parse_comment({"field": "feed", "value": {"item": "like", "verb": "add"}}) is None
    assert mw._parse_comment({"field": "feed", "value": {
        "item": "comment", "verb": "remove", "comment_id": "c"}}) is None
    assert mw._parse_comment({"field": "reactions", "value": {}}) is None


def test_comment_capture_is_inert_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "meta_comment_reply", False, raising=False)
    scheduled = []
    import app.agent.runtime as rt
    monkeypatch.setattr(rt, "schedule_comment_engage",
                        lambda *a, **k: scheduled.append(a), raising=False)
    payload = {"entry": [{"changes": [{"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": "c1", "message": "hi",
        "from": {"id": "U1"}}}]}]}
    asyncio.run(mw._capture_comment_events(_FakeDB(), "messenger", payload))
    assert scheduled == []


def test_comment_capture_schedules_and_skips_own_page(monkeypatch):
    calls = {}
    _patch(monkeypatch, calls)
    monkeypatch.setattr(settings, "meta_comment_reply", True, raising=False)
    monkeypatch.setattr(settings, "meta_page_id", "PAGE1", raising=False)
    scheduled = []
    import app.agent.runtime as rt
    monkeypatch.setattr(rt, "schedule_comment_engage",
                        lambda redis, channel, c, own: scheduled.append((channel, c["comment_id"], c["from_id"])),
                        raising=False)
    payload = {"entry": [{"changes": [
        {"field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "c1",
                                    "message": "How much for a cassock?",
                                    "from": {"id": "U1", "name": "Jane"}, "post_id": "P1"}},
        {"field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "c2",
                                    "message": "our own reply", "from": {"id": "PAGE1"},
                                    "post_id": "P1"}},   # our page → must be skipped
    ]}]}
    asyncio.run(mw._capture_comment_events(_FakeDB(), "messenger", payload))
    # Facebook Page comments get their own "facebook" channel (not "messenger").
    assert scheduled == [("facebook", "c1", "U1")]   # only the customer's comment
    assert calls["convs"] == [("facebook", "U1")]
    assert calls["persons"] == [("facebook", "U1", "facebook_comment")]


def test_instagram_comments_stay_on_instagram_channel(monkeypatch):
    calls = {}
    _patch(monkeypatch, calls)
    monkeypatch.setattr(settings, "meta_comment_reply", True, raising=False)
    monkeypatch.setattr(settings, "meta_page_id", "PAGE1", raising=False)
    scheduled = []
    import app.agent.runtime as rt
    monkeypatch.setattr(rt, "schedule_comment_engage",
                        lambda redis, channel, c, own: scheduled.append((channel, c["comment_id"])),
                        raising=False)
    payload = {"entry": [{"changes": [
        {"field": "comments", "value": {"id": "ig1", "text": "how much?",
                                        "from": {"id": "IG1", "username": "jo"},
                                        "media": {"id": "M1"}}},
    ]}]}
    asyncio.run(mw._capture_comment_events(_FakeDB(), "instagram", payload))
    assert scheduled == [("instagram", "ig1")]
    assert calls["convs"] == [("instagram", "IG1")]
