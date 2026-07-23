"""Hub .webp → WhatsApp/Meta-safe .jpg conversion (app/services/media_convert.py).

Fetch + Pillow are mocked so this runs without network or Pillow installed.
"""
import asyncio

import app.main  # noqa: F401 — registers models / media dir
import app.services.media_convert as mc
from app.core.config import settings


def test_jpg_png_pass_through(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "https://neema.example", raising=False)
    assert asyncio.run(mc.to_sendable_image("https://hub.example/a.jpg")) == "https://hub.example/a.jpg"
    assert asyncio.run(mc.to_sendable_image("https://hub.example/a.PNG")) == "https://hub.example/a.PNG"
    assert asyncio.run(mc.to_sendable_image("https://hub.example/a.jpeg?x=1")) == "https://hub.example/a.jpeg?x=1"
    assert asyncio.run(mc.to_sendable_image(None)) is None


def test_disallowed_host_webp_returns_original(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "https://neema.example", raising=False)
    monkeypatch.setattr(settings, "hub_api_url", "https://hub.bethanyhouse.co.ke", raising=False)
    # A webp from a host that isn't our hub/media is never fetched — returned as-is.
    assert asyncio.run(mc.to_sendable_image("https://evil.example/x.webp")) == "https://evil.example/x.webp"


def test_webp_from_hub_converts_and_returns_jpg_url(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "https://neema.example", raising=False)
    monkeypatch.setattr(settings, "hub_api_url", "https://hub.bethanyhouse.co.ke", raising=False)
    monkeypatch.setattr(mc.os.path, "exists", lambda p: False)   # not cached yet
    monkeypatch.setattr(mc, "_convert_to_jpeg", lambda data, path: None)   # skip Pillow

    class _Resp:
        is_success = True
        content = b"webpbytes"

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _Resp()

    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _Client())
    url = "https://hub.bethanyhouse.co.ke/storage/products/14/abc.webp"
    out = asyncio.run(mc.to_sendable_image(url))
    assert out.startswith("https://neema.example/api/admin/media/img_")
    assert out.endswith(".jpg")
    # deterministic per source URL (so it caches under one name)
    assert asyncio.run(mc.to_sendable_image(url)) == out


def test_cached_conversion_is_reused(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "https://neema.example", raising=False)
    monkeypatch.setattr(settings, "hub_api_url", "https://hub.bethanyhouse.co.ke", raising=False)
    monkeypatch.setattr(mc.os.path, "exists", lambda p: True)    # already converted

    def _boom(*a, **k):
        raise AssertionError("should not fetch when cached")

    monkeypatch.setattr("httpx.AsyncClient", _boom)
    out = asyncio.run(mc.to_sendable_image("https://hub.bethanyhouse.co.ke/x.webp"))
    assert out.startswith("https://neema.example/api/admin/media/img_") and out.endswith(".jpg")


def test_no_media_host_returns_original(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "", raising=False)
    assert asyncio.run(mc.to_sendable_image("https://hub.bethanyhouse.co.ke/x.webp")) == "https://hub.bethanyhouse.co.ke/x.webp"
