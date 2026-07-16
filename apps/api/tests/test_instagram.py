"""Instagram is NOT Facebook wearing a different name — the Graph shapes differ,
and every place we assumed Facebook's would silently fail on IG:

  - a public comment reply goes on /replies (IG) vs /comments (FB)
  - a private reply goes through the Send API addressing the COMMENT as the
    recipient (IG) vs the comment's /private_replies edge (FB)
  - a post read returns caption/permalink/media_url (IG media) vs
    message/permalink_url/full_picture (FB post) — and Meta 400s the WHOLE call
    on unknown fields, so the wrong shape yields no context card at all
"""
import asyncio

from app.services import meta_send
from app.core.config import settings


def _capture_posts(monkeypatch):
    """Record every _graph_post(path, payload) instead of calling Meta."""
    calls = []

    async def fake_post(path, payload, what, page_id=None):
        calls.append((path, payload))

    monkeypatch.setattr(meta_send, "_graph_post", fake_post)
    return calls


def test_comment_reply_uses_the_right_edge_per_platform(monkeypatch):
    calls = _capture_posts(monkeypatch)
    asyncio.run(meta_send.reply_to_comment("IG_C1", "hi", channel="instagram"))
    asyncio.run(meta_send.reply_to_comment("FB_C1", "hi", channel="facebook"))
    assert calls[0][0] == "IG_C1/replies"      # Instagram: dedicated replies edge
    assert calls[1][0] == "FB_C1/comments"     # Facebook: comment-on-a-comment


def test_private_reply_uses_send_api_for_instagram(monkeypatch):
    calls = _capture_posts(monkeypatch)
    asyncio.run(meta_send.send_private_reply("IG_C1", "hello", channel="instagram"))
    path, payload = calls[0]
    assert path == "me/messages"                              # Send API, not an edge
    assert payload["recipient"] == {"comment_id": "IG_C1"}    # the COMMENT is the recipient

    asyncio.run(meta_send.send_private_reply("FB_C1", "hello", channel="facebook"))
    assert calls[1][0] == "FB_C1/private_replies"             # Facebook keeps its edge


class _Resp:
    is_success = True
    status_code = 200
    def __init__(self, payload): self._p = payload
    def json(self): return self._p


def _fake_get(monkeypatch, payload, seen):
    class _C:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw):
            seen.append(kw.get("params", {}).get("fields", ""))
            return _Resp(payload)
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _C())


def test_post_context_reads_instagram_media_fields(monkeypatch):
    """An IG VIDEO: caption is the title, thumbnail_url is the poster, and it must
    be flagged as playable — asking Facebook's fields here would return nothing."""
    monkeypatch.setattr(settings, "meta_page_token", "T", raising=False)
    seen = []
    _fake_get(monkeypatch, {
        "caption": "Communion trays available",
        "permalink": "https://instagram.com/p/abc",
        "media_type": "VIDEO",
        "media_url": "https://cdn/reel.mp4",
        "thumbnail_url": "https://cdn/poster.jpg",
    }, seen)
    ctx = asyncio.run(meta_send.fetch_post_context("IG_MEDIA_1", channel="instagram"))
    assert ctx["title"] == "Communion trays available"
    assert ctx["permalink"] == "https://instagram.com/p/abc"
    assert ctx["thumb"] == "https://cdn/poster.jpg"      # poster, never the mp4
    assert ctx["media_type"] == "video" and ctx["has_video"] is True
    # it must have asked for IG fields, not Facebook's
    assert "caption" in seen[0] and "permalink_url" not in seen[0]


def test_post_context_instagram_image_has_no_video(monkeypatch):
    monkeypatch.setattr(settings, "meta_page_token", "T", raising=False)
    seen = []
    _fake_get(monkeypatch, {"caption": "", "permalink": "https://instagram.com/p/x",
                            "media_type": "IMAGE", "media_url": "https://cdn/photo.jpg"}, seen)
    ctx = asyncio.run(meta_send.fetch_post_context("IG_MEDIA_2", channel="instagram"))
    assert ctx["has_video"] is False and ctx["media_type"] == "photo"
    assert ctx["thumb"] == "https://cdn/photo.jpg"       # an image IS its own poster
    assert ctx["title"] == "Photo post"                  # no caption → a sane label


def test_post_video_url_uses_instagram_media_url(monkeypatch):
    """IG has no attachments edge — the media object's media_url IS the mp4."""
    monkeypatch.setattr(settings, "meta_page_token", "T", raising=False)
    seen = []
    _fake_get(monkeypatch, {"media_type": "VIDEO", "media_url": "https://cdn/reel.mp4"}, seen)
    url = asyncio.run(meta_send.fetch_post_video_url("IG_MEDIA_1", channel="instagram"))
    assert url == "https://cdn/reel.mp4"
    assert "media_url" in seen[0] and "attachments" not in seen[0]

    # an IG photo has no video to play
    seen2 = []
    _fake_get(monkeypatch, {"media_type": "IMAGE", "media_url": "https://cdn/p.jpg"}, seen2)
    assert asyncio.run(meta_send.fetch_post_video_url("IG_MEDIA_2", channel="instagram")) is None
