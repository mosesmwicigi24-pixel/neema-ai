"""Cycle 2 on Messenger / Instagram / TikTok / page comments: the residual
messages that used to land as "⚠️ Sent a message we can't display here — ask
them to resend as text.", "[story_mention]", "[unsupported message]" or an
EMPTY comment row now carry words a person understands and a record."""
import asyncio
import types

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


def test_a_redelivered_comment_is_not_answered_twice_without_redis(monkeypatch):
    """Verification 1.6: a 502 on the DM capture makes Meta redeliver the whole
    payload, comments included, and the redis mark is best-effort. The comment
    row's own id is the durable dedupe — with no redis at all, a comment whose
    row exists is neither stored again nor engaged."""
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
        "from": {"id": "U9", "name": "Mary"}, "message": "how much?"}}]}]}

    class _RowDB(_FakeDB):
        """Answers the dedupe SELECT from the statement itself (verification
        pass 2: a fake that ignores the statement cannot tell a correct
        predicate from a wrong one). `rows` holds (channel, comment id)."""
        def __init__(self, rows):
            super().__init__()
            self.rows, self.sql = rows, []

        async def execute(self, stmt):
            import types
            from sqlalchemy.dialects import postgresql
            sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            self.sql.append(sql)
            hit = any(f"messages.channel = '{ch}'" in sql and f"messages.waba_msg_id = '{cid}'" in sql
                      for ch, cid in self.rows)
            return types.SimpleNamespace(scalar_one_or_none=lambda: ("row" if hit else None))

    db = _RowDB({("facebook", "c9")})          # the row for c9 exists on the comment channel
    asyncio.run(mw._capture_comment_events(db, "messenger", payload, redis=None))
    assert not engaged and not any(isinstance(o, Message) for o in db.added)
    assert db.commits == 0
    assert "messages.channel = 'facebook'" in db.sql[0] and "messages.waba_msg_id = 'c9'" in db.sql[0]
    # the same id on the DM channel is a different message: no dedupe
    db2 = _RowDB({("messenger", "c9")})
    asyncio.run(mw._capture_comment_events(db2, "messenger", payload, redis=None))
    assert engaged and any(isinstance(o, Message) for o in db2.added)
    # and an Instagram comment is looked up on "instagram"
    engaged.clear()
    ig = {"object": "instagram", "entry": [{"id": "PAGE1", "changes": [{"field": "comments", "value": {
        "id": "ig9", "media": {"id": "m9"}, "from": {"id": "U9", "username": "mary"}, "text": "price?"}}]}]}
    db3 = _RowDB({("instagram", "ig9")})
    asyncio.run(mw._capture_comment_events(db3, "instagram", ig, redis=None))
    assert db3.sql and "messages.channel = 'instagram'" in db3.sql[0] and not engaged


def test_a_meta_delivery_receipt_stamps_the_outbound_rows_it_covers(monkeypatch):
    """Investigation 1.10: Meta's receipts carry a watermark, not our ids.
    Every outbound row to that contact up to the watermark is stamped
    delivered / read; a later row is not; a higher status is never lowered."""
    from datetime import datetime, timezone
    from app.services import messaging as svc

    t = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)  # noqa: E731
    rows = [
        types.SimpleNamespace(created_at=t("2026-11-06T10:00:00"), raw_meta=None),                      # before: stamped
        types.SimpleNamespace(created_at=t("2026-11-06T10:05:00"), raw_meta={"delivery": {"status": "read"}}),  # higher: kept
        types.SimpleNamespace(created_at=t("2026-11-06T10:20:00"), raw_meta=None),                      # after the watermark
    ]
    watermark = int(t("2026-11-06T10:10:00").timestamp() * 1000)

    class _DB:
        def __init__(self): self.commits, self.sql = 0, []
        async def execute(self, stmt):
            from sqlalchemy.dialects import postgresql
            sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            self.sql.append(sql)
            until = datetime.fromtimestamp(watermark / 1000, tz=timezone.utc)
            hit = [r for r in rows if r.created_at <= until]
            return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: hit))
        async def commit(self): self.commits += 1
        async def rollback(self): pass

    db = _DB()
    n = asyncio.run(svc.record_meta_receipt(db, "messenger", "PSID_1", "delivered", watermark))
    assert n == 1 and db.commits == 1
    assert rows[0].raw_meta["delivery"]["status"] == "delivered"
    assert rows[1].raw_meta["delivery"]["status"] == "read"                 # never lowered
    assert rows[2].raw_meta is None
    assert "messages.channel = 'messenger'" in db.sql[0] and "messages.external_id = 'PSID_1'" in db.sql[0]
    assert "direction" in db.sql[0] and "created_at <=" in db.sql[0]
    # no watermark, unknown status: nothing happens
    assert asyncio.run(svc.record_meta_receipt(db, "messenger", "PSID_1", "delivered", None)) == 0
    assert asyncio.run(svc.record_meta_receipt(db, "messenger", "PSID_1", "seen", watermark)) == 0

    # and the webhook routes a read receipt there, with the sender's PSID
    seen = []
    async def fake_receipt(db, channel, ext, status, wm):
        seen.append((channel, ext, status, wm)); return 1
    monkeypatch.setattr(svc, "record_meta_receipt", fake_receipt)
    payload = {"object": "page", "entry": [{"messaging": [
        {"sender": {"id": "PSID_1"}, "recipient": {"id": "PAGE"}, "read": {"watermark": watermark}}]}]}
    asyncio.run(mw._capture_events(_FakeDB(), "messenger", payload))
    assert seen == [("messenger", "PSID_1", "read", watermark)]
