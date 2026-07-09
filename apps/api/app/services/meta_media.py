"""Re-host inbound Meta (Messenger / Instagram / Facebook) attachments.

Meta serves attachment URLs as short-lived signed CDN links, so an image that
displays today can 404 a few days later. To make the inbox durable we download
the file once and re-serve it from our own store — the SAME `/var/neema/media`
directory + `/api/admin/media/...` path WhatsApp media already uses.

This runs in the background off the webhook ack (Meta wants a fast 200): the
Message row is first saved with the CDN URL (so it shows immediately, live),
then this rewrites `media_url` to the stable served URL once the download
succeeds. On any failure — download error, or `MEDIA_PUBLIC_URL` unset — the
row keeps the CDN URL, so nothing regresses versus not re-hosting at all.
"""
import asyncio
import logging
import os

import httpx
from sqlalchemy import update

from app.core.config import settings
from app.models.message import Message

_log = logging.getLogger("neema.meta")

# Same on-disk store + public path as the WhatsApp media path (routers/media.py).
MEDIA_DIR = "/var/neema/media"
os.makedirs(MEDIA_DIR, exist_ok=True)

_CT_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/gif": ".gif", "video/mp4": ".mp4", "video/3gpp": ".3gp",
    "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/ogg": ".ogg",
    "audio/aac": ".aac", "application/pdf": ".pdf",
}
_TYPE_EXT = {"image": ".jpg", "video": ".mp4", "audio": ".ogg", "file": ".bin"}

_bg_tasks: set = set()


def _ext(content_type: str, media_type: str) -> str:
    """Prefer the response Content-Type, fall back to the resolved media_type."""
    ct = (content_type or "").split(";")[0].strip().lower()
    return _CT_EXT.get(ct) or _TYPE_EXT.get(media_type, ".bin")


async def _rehost(channel: str, mid: str, cdn_url: str, media_type: str) -> None:
    if not settings.media_public_url:
        return  # can't build a stable URL — keep the CDN link
    from app.database import AsyncSessionLocal
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(cdn_url)   # Meta attachment URLs are pre-signed
            if not resp.is_success:
                _log.warning("meta media fetch %s failed (%s) for mid=%s",
                             media_type, resp.status_code, mid)
                return
            ext = _ext(resp.headers.get("content-type", ""), media_type)
            safe = "".join(c for c in str(mid) if c.isalnum() or c in "-_") or "media"
            filename = f"meta_{channel}_{safe}{ext}"
            filepath = os.path.join(MEDIA_DIR, filename)
            if not os.path.exists(filepath):        # idempotent on redelivery
                with open(filepath, "wb") as f:
                    f.write(resp.content)
        stable = f"{settings.media_public_url.rstrip('/')}/api/admin/media/{filename}"
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Message)
                .where(Message.channel == channel, Message.waba_msg_id == mid)
                .values(media_url=stable)
            )
            await db.commit()
        _log.info("meta media rehosted mid=%s -> %s", mid, filename)
    except Exception:
        _log.exception("meta media rehost failed for mid=%s", mid)


def schedule_media_rehost(channel: str, mid: str | None, cdn_url: str | None,
                          media_type: str | None) -> None:
    """Fire-and-forget: download a Meta attachment and rewrite the message's
    media_url to a stable served URL. No-op without a message id (needed to
    locate the row) or URL."""
    if not mid or not cdn_url or not media_type:
        return
    task = asyncio.create_task(_rehost(channel, mid, cdn_url, media_type))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
