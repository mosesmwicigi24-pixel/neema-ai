"""Unit tests for the outbound channel dispatcher (no network). Requires Python 3.11."""
import asyncio

from app.services import meta_send
from app.core.config import settings


def test_send_to_channel_routes_meta_channels(monkeypatch):
    sent = []

    async def fake_meta(rid, text, page_id=None):
        sent.append((rid, text))

    monkeypatch.setattr(meta_send, "send_meta_message", fake_meta)
    asyncio.run(meta_send.send_to_channel("messenger", "PSID_1", "hi"))
    asyncio.run(meta_send.send_to_channel("instagram", "IGSID_1", "yo"))
    assert sent == [("PSID_1", "hi"), ("IGSID_1", "yo")]


def test_send_to_channel_routes_whatsapp_and_strips_plus(monkeypatch):
    sent = []

    async def fake_waba(num, text, context_wamid=None):
        sent.append((num, text))

    import app.services.n8n_bridge as nb
    monkeypatch.setattr(nb, "_send_waba", fake_waba)
    asyncio.run(meta_send.send_to_channel("whatsapp", "+254712345678", "hello"))
    assert sent == [("254712345678", "hello")]   # '+' stripped for WABA


def test_send_meta_message_requires_page_token(monkeypatch):
    monkeypatch.setattr(settings, "meta_page_token", "", raising=False)
    raised = False
    try:
        asyncio.run(meta_send.send_meta_message("PSID_1", "hi"))
    except RuntimeError:
        raised = True
    assert raised


def _fake_client_returning(payload):
    """An httpx.AsyncClient stand-in whose every GET returns `payload` as JSON."""
    class _R:
        is_success = True
        status_code = 200
        def json(self):
            return payload
    class _C:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, **kw):
            return _R()
    return lambda *a, **k: _C()


def test_fetch_post_context_tags_video_and_photo(monkeypatch):
    """The comment-context card needs to know a reel is a VIDEO (offer inline
    play) vs a photo — so the post's attachment media_type is normalised."""
    import httpx
    monkeypatch.setattr(settings, "meta_page_token", "T", raising=False)

    video = {"message": "New reel!", "permalink_url": "https://fb/reel/1",
             "full_picture": "http://x/thumb.jpg",
             "attachments": {"data": [{"media_type": "video_inline",
                                       "media": {"image": {"src": "http://x/t.jpg"}}}]}}
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client_returning(video))
    ctx = asyncio.run(meta_send.fetch_post_context("POST1"))
    assert ctx["media_type"] == "video" and ctx["has_video"] is True
    assert ctx["thumb"] and ctx["permalink"] == "https://fb/reel/1"

    photo = {"message": "", "permalink_url": "", "full_picture": "http://x/p.jpg",
             "attachments": {"data": [{"media_type": "photo"}]}}
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client_returning(photo))
    ctx2 = asyncio.run(meta_send.fetch_post_context("POST2"))
    assert ctx2["media_type"] == "photo" and ctx2["has_video"] is False


def test_fetch_post_video_url_returns_direct_source(monkeypatch):
    import httpx
    monkeypatch.setattr(settings, "meta_page_token", "T", raising=False)
    payload = {"attachments": {"data": [
        {"media_type": "video", "media": {"source": "https://cdn/reel.mp4"}}]}}
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client_returning(payload))
    url = asyncio.run(meta_send.fetch_post_video_url("POST1"))
    assert url == "https://cdn/reel.mp4"
    # no token → no fetch
    monkeypatch.setattr(settings, "meta_page_token", "", raising=False)
    assert asyncio.run(meta_send.fetch_post_video_url("POST1")) is None
