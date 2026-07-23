"""Make a hub product image safe to send on WhatsApp / Meta.

The hub stores product photos as .webp, but WhatsApp image messages accept only
JPEG/PNG (webp is a sticker-only format there), so a .webp card image silently
never renders. We fetch the hub image once, convert it to JPEG, cache it in the
served media dir, and hand back the public .jpg URL. jpg/png pass straight
through. Best-effort: on any failure we return the original URL so a send still
attempts. The blocking decode/encode runs off the event loop.
"""
import asyncio
import hashlib
import logging
import os
from urllib.parse import urlparse

from app.core.config import settings

_log = logging.getLogger("neema.media")


def _allowed_host(url: str) -> bool:
    """Only convert images from our own hub / media host (never fetch arbitrary
    URLs). The catalogue's image_url is always the hub, so this is just hygiene."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    allowed = set()
    for u in (settings.hub_api_url, settings.media_public_url):
        h = urlparse(u or "").hostname
        if h:
            allowed.add(h.lower())
    return host in allowed


def _convert_to_jpeg(data: bytes, path: str) -> None:
    from io import BytesIO
    from PIL import Image
    im = Image.open(BytesIO(data))
    if im.mode != "RGB":
        im = im.convert("RGB")
    im.thumbnail((1600, 1600))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, "JPEG", quality=85)


async def to_sendable_image(src_url: str | None) -> str | None:
    """A WhatsApp/Meta-safe (JPEG) public URL for a product image — converting a
    .webp hub image once and caching it; jpg/png returned unchanged."""
    if not src_url:
        return src_url
    low = src_url.split("?")[0].lower()
    if low.endswith((".jpg", ".jpeg", ".png")):
        return src_url
    base = (settings.media_public_url or "").rstrip("/")
    if not base or not _allowed_host(src_url):
        return src_url

    from app.routers.media import MEDIA_DIR
    name = "img_" + hashlib.sha1(src_url.encode("utf-8")).hexdigest()[:24] + ".jpg"
    path = os.path.join(MEDIA_DIR, name)
    public = f"{base}/api/admin/media/{name}"
    if os.path.exists(path):
        return public
    try:
        import httpx
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            resp = await client.get(src_url)
        if not resp.is_success or not resp.content:
            return src_url
        await asyncio.to_thread(_convert_to_jpeg, resp.content, path)
        return public
    except Exception as exc:
        _log.warning("image convert failed for %s: %s", src_url, exc)
        return src_url
