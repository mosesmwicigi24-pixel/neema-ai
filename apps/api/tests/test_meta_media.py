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
