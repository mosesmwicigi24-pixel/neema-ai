"""Cycle 2 on Messenger / Instagram / TikTok / page comments: the residual
messages that used to land as "⚠️ Sent a message we can't display here — ask
them to resend as text.", "[story_mention]", "[unsupported message]" or an
EMPTY comment row now carry words a person understands and a record."""
import asyncio

import app.models.agent  # noqa: F401
import app.models.conversation  # noqa: F401
import app.models.intercept  # noqa: F401
import app.models.person  # noqa: F401
import app.models.user  # noqa: F401
from app.models.message import Message
from app.routers import meta_webhook as mw
from app.services.inbound_kinds import describe_meta_dm, unsupported_social
from tests.test_meta_webhook import _FakeDB, _patch


def _capture(monkeypatch, message: dict, channel: str = "instagram") -> Message:
    calls: dict = {}
    _patch(monkeypatch, calls)
    payload = {"object": "instagram" if channel == "instagram" else "page",
               "entry": [{"id": "PAGE1", "messaging": [
                   {"sender": {"id": "IGSID_1"}, "message": {"mid": "mid.1", **message}}]}]}
    db = _FakeDB()
    asyncio.run(mw._capture_events(db, channel, payload))
    return next(o for o in db.added if isinstance(o, Message))


def test_instagram_is_unsupported_is_calm_and_recorded(monkeypatch):
    m = _capture(monkeypatch, {"is_unsupported": True})
    assert m.text == "Sent something Instagram doesn't let us show here. You can ask them to send it as a photo or text."
    assert m.raw_meta["kind"] == "unsupported" and m.raw_meta["payload"]["is_unsupported"] is True
    assert "⚠️" not in m.text


def test_unsent_message_says_so(monkeypatch):
    m = _capture(monkeypatch, {"is_deleted": True})
    assert m.text == "🗑️ Unsent a message" and m.raw_meta["kind"] == "deleted"


def test_story_mention_keeps_the_story_image_and_reads_in_words(monkeypatch):
    m = _capture(monkeypatch, {"attachments": [
        {"type": "story_mention", "payload": {"url": "https://lookaside.fbsbx.com/ig_story.jpg"}}]})
    assert m.text == "📸 Mentioned us in their story"
    assert m.media_url == "https://lookaside.fbsbx.com/ig_story.jpg"
    assert m.raw_meta["kind"] == "story_mention"


def test_share_without_a_link_is_words_not_a_bracket(monkeypatch):
    m = _capture(monkeypatch, {"attachments": [{"type": "share", "payload": {}}]}, channel="messenger")
    assert m.text == "🔗 Shared a post"


def test_legacy_location_pin_becomes_a_location(monkeypatch):
    m = _capture(monkeypatch, {"attachments": [{"type": "location", "title": "Kenyatta Ave",
                                                "payload": {"coordinates": {"lat": -1.28, "long": 36.82}}}]},
                 channel="messenger")
    assert m.text == "📍 Location: Kenyatta Ave (-1.28,36.82)"
    assert m.raw_meta["lat"] == -1.28


def test_an_empty_message_is_never_the_old_warning(monkeypatch):
    m = _capture(monkeypatch, {}, channel="messenger")
    assert m.text.startswith("Sent something Messenger doesn't let us show here")
    assert m.raw_meta["kind"] == "unsupported"


def test_messenger_sticker_gets_a_sticker_record_and_keeps_its_text(monkeypatch):
    m = _capture(monkeypatch, {"attachments": [
        {"type": "image", "payload": {"sticker_id": 369239263222822,
                                      "url": "https://scontent.xx/like.png"}}]}, channel="messenger")
    assert m.text == "👍"                    # the closer gate's word, unchanged
    assert m.raw_meta == {"v": 1, "type": "sticker", "kind": "sticker", "emoji": "👍"}


def test_text_messages_are_untouched(monkeypatch):
    m = _capture(monkeypatch, {"text": "how much is the cope?"}, channel="messenger")
    assert m.text == "how much is the cope?" and m.raw_meta is None
    assert describe_meta_dm({"text": "hi"}, "messenger") == (None, None)


def test_tiktok_residual_names_tiktoks_type():
    text, meta = unsupported_social("tiktok", "sticker", {"type": "sticker", "sticker": {"id": "s1"}})
    assert text == "Sent something TikTok doesn't let us show here — a sticker. You can ask them to send it as a photo or text."
    assert meta["type"] == "sticker" and meta["payload"]["sticker"]["id"] == "<str:2>"


def test_photo_comment_is_parsed_with_its_photo():
    c = mw._parse_comment({"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": "c1", "post_id": "p1",
        "from": {"id": "U1", "name": "Mary"}, "message": "", "photo": "https://scontent.xx/c.jpg"}})
    assert c["text"] == "" and c["photo"] == "https://scontent.xx/c.jpg"


def test_wordless_comment_is_stored_with_words_and_engage_keeps_the_empty_text(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_comment_reply", True, raising=False)
    monkeypatch.setattr(settings, "meta_page_id", "PAGE1", raising=False)
    calls: dict = {}
    _patch(monkeypatch, calls)

    async def no_ctx(post_id, redis=None, channel="facebook"):
        return {}
    monkeypatch.setattr(mw, "_post_context", no_ctx)

    async def not_live(redis):
        return set()
    monkeypatch.setattr("app.services.meta_send.live_video_ids", not_live)
    engaged = []
    monkeypatch.setattr("app.agent.runtime.schedule_comment_engage",
                        lambda redis, ch, c, own: engaged.append(c))
    payload = {"object": "page", "entry": [{"id": "PAGE1", "changes": [{"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": "c9", "post_id": "p9",
        "from": {"id": "U9", "name": "Mary"}, "photo": "https://scontent.xx/c9.jpg"}}]}]}
    db = _FakeDB()
    asyncio.run(mw._capture_comment_events(db, "messenger", payload))
    m = next(o for o in db.added if isinstance(o, Message))
    assert m.text == "📷 Commented with a photo or sticker"
    assert m.raw_meta == {"v": 1, "type": "comment", "kind": "comment_media",
                          "photo": "https://scontent.xx/c9.jpg"}
    assert engaged and engaged[0]["text"] == ""      # the public-reply path is unchanged
