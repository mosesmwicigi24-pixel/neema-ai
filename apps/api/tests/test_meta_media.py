"""Unit tests for re-hosting Meta attachments (services/meta_media.py) — the
extension mapping, the fire-and-forget guards, and the download→rewrite path
with httpx + the DB session mocked. Requires Python 3.11.
"""
import asyncio
import types

import app.models.agent, app.models.conversation, app.models.person  # noqa: F401
import app.models.user  # noqa: F401
from app.services import meta_media as mm
from app.core.config import settings


def test_ext_prefers_content_type_then_media_type():
    assert mm._ext("image/png", "image") == ".png"
    assert mm._ext("image/jpeg; charset=x", "image") == ".jpg"
    assert mm._ext("", "video") == ".mp4"          # no content-type → media_type
    assert mm._ext("application/octet-stream", "image") == ".jpg"  # unknown CT → media_type
    assert mm._ext("", "weird") == ".bin"          # unknown everything


def test_schedule_is_noop_without_id_or_url(monkeypatch):
    # Must not raise or spawn a task when it can't locate/download the row.
    created = []
    monkeypatch.setattr(mm.asyncio, "create_task", lambda coro: created.append(coro))
    mm.schedule_media_rehost("facebook", None, "https://x/y.jpg", "image")
    mm.schedule_media_rehost("facebook", "mid1", None, "image")
    mm.schedule_media_rehost("facebook", "mid1", "https://x/y.jpg", None)
    assert created == []


def test_rehost_downloads_and_rewrites_media_url(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "media_public_url", "https://neema.test", raising=False)
    monkeypatch.setattr(mm, "MEDIA_DIR", str(tmp_path))

    class _Resp:
        is_success = True
        status_code = 200
        content = b"\xff\xd8\xff-jpeg-bytes"
        headers = {"content-type": "image/jpeg"}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _Resp()

    monkeypatch.setattr(mm.httpx, "AsyncClient", _Client)

    updates = {}

    class _DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, stmt):
            # capture the compiled UPDATE's bound values
            updates["values"] = stmt.compile().params
        async def commit(self): updates["committed"] = True

    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _DB())

    asyncio.run(mm._rehost("facebook", "mid-42", "https://cdn.meta/x", "image"))

    # File written under the resolved name, DB row rewritten to the served URL.
    saved = tmp_path / "meta_facebook_mid-42.jpg"
    assert saved.exists() and saved.read_bytes() == _Resp.content
    assert updates.get("committed") is True
    assert any(v == "https://neema.test/api/admin/media/meta_facebook_mid-42.jpg"
               for v in updates["values"].values())


# ── Durability: expired CDN links must never mean a lost photo ────────────────


def test_is_ephemeral_flags_meta_cdn_only():
    assert mm.is_ephemeral("https://scontent.xx.fbcdn.net/v/t1/x.jpg")
    assert mm.is_ephemeral("https://lookaside.fbsbx.com/x")
    assert mm.is_ephemeral("https://cdn.cdninstagram.com/x.jpg")
    # Our own served copies (absolute or relative) are durable.
    assert not mm.is_ephemeral("https://neema.test/api/admin/media/x.jpg")
    assert not mm.is_ephemeral("/api/admin/media/x.jpg")
    assert not mm.is_ephemeral(None)


def test_stable_url_falls_back_to_relative_without_public_url(monkeypatch):
    """Without MEDIA_PUBLIC_URL we still re-host — a same-origin relative link
    renders in the dashboard, where the old code kept a link doomed to expire."""
    monkeypatch.setattr(settings, "media_public_url", "", raising=False)
    assert mm._stable_url("a.jpg") == "/api/admin/media/a.jpg"
    monkeypatch.setattr(settings, "media_public_url", "https://neema.test/", raising=False)
    assert mm._stable_url("a.jpg") == "https://neema.test/api/admin/media/a.jpg"


def test_rehost_recovers_via_graph_when_the_cdn_link_is_dead(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "media_public_url", "https://neema.test", raising=False)
    monkeypatch.setattr(mm, "MEDIA_DIR", str(tmp_path))

    class _Dead:
        is_success = False
        status_code = 404
        content = b""
        headers: dict = {}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **k): return _Dead()

    monkeypatch.setattr(mm.httpx, "AsyncClient", _Client)

    async def _fake_graph(mid):
        return b"recovered-bytes", "image/png", "image"
    monkeypatch.setattr(mm, "fetch_from_graph", _fake_graph)

    updates = {}

    class _DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, stmt): updates["values"] = stmt.compile().params
        async def commit(self): updates["committed"] = True

    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _DB())

    asyncio.run(mm._rehost("messenger", "mid-99", "https://scontent.fbcdn.net/dead", "image"))

    saved = tmp_path / "meta_messenger_mid-99.png"
    assert saved.exists() and saved.read_bytes() == b"recovered-bytes"
    assert updates.get("committed") is True


def test_fetch_from_graph_returns_none_without_a_token(monkeypatch):
    monkeypatch.setattr(settings, "meta_page_token", "", raising=False)
    monkeypatch.setattr(settings, "meta_page_tokens", "", raising=False)
    assert asyncio.run(mm.fetch_from_graph("mid-1")) is None


def test_graph_urls_covers_every_attachment_shape():
    assert mm._graph_urls({"image_data": {"url": "https://a/1.jpg"}}) == ["https://a/1.jpg"]
    assert mm._graph_urls({"video_data": {"src": "https://a/2.mp4"}}) == ["https://a/2.mp4"]
    assert mm._graph_urls({"file_url": "https://a/3.pdf"}) == ["https://a/3.pdf"]
    assert mm._graph_urls({"payload": {"url": "https://a/4.jpg"}}) == ["https://a/4.jpg"]
    assert mm._graph_urls({"image_data": {"url": "not-a-url"}}) == []


def test_repair_pending_only_touches_expiring_rows(monkeypatch):
    """Rows already served from our own store must not be re-downloaded."""
    rows = [
        types.SimpleNamespace(channel="messenger", waba_msg_id="m1", media_type="image",
                              media_url="https://scontent.fbcdn.net/a.jpg"),
        types.SimpleNamespace(channel="messenger", waba_msg_id="m2", media_type="image",
                              media_url="https://neema.test/api/admin/media/b.jpg"),
        types.SimpleNamespace(channel="instagram", waba_msg_id="m3", media_type="video",
                              media_url="https://cdn.cdninstagram.com/c.mp4"),
    ]

    class _Result:
        def scalars(self): return self
        def all(self): return rows

    class _DB:
        async def execute(self, stmt): return _Result()

    called = []

    async def _fake_rehost(channel, mid, url, mtype):
        called.append(mid)
    monkeypatch.setattr(mm, "_rehost", _fake_rehost)

    healed = asyncio.run(mm.repair_pending(_DB()))
    assert healed == 2
    assert called == ["m1", "m3"]        # the durable row was skipped
