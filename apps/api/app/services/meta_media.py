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

# Same on-disk store + public path as the WhatsApp media path (routers/media.py):
# both derive from the single Settings definition. Created at write time and at
# startup — never at import time (see routers/media.py for why).
MEDIA_DIR = settings.media_dir

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


def _stable_url(filename: str) -> str:
    """The durable URL for a stored file.

    MEDIA_PUBLIC_URL gives an absolute link (needed when we hand the file back
    to Meta/WhatsApp). Without it we still return a same-origin relative path
    rather than giving up — the dashboard renders it fine, and a relative link
    that works beats a signed CDN link that expires in days."""
    if settings.media_public_url:
        return f"{settings.media_public_url.rstrip('/')}/api/admin/media/{filename}"
    return f"/api/admin/media/{filename}"


def is_ephemeral(url: str | None) -> bool:
    """True for Meta's signed CDN links — they 404 after a few days, so any row
    still holding one is media we are about to lose."""
    u = (url or "").lower()
    if not u.startswith("http"):
        return False
    return any(h in u for h in ("fbcdn.net", "cdninstagram.com", "lookaside.",
                                "fbsbx.com", "scontent."))


async def _store(content: bytes, content_type: str, channel: str, mid: str,
                 media_type: str) -> str:
    """Write bytes into the media store and return their stable URL."""
    ext = _ext(content_type, media_type)
    safe = "".join(c for c in str(mid) if c.isalnum() or c in "-_") or "media"
    filename = f"meta_{channel}_{safe}{ext}"
    filepath = os.path.join(MEDIA_DIR, filename)
    if not os.path.exists(filepath):            # idempotent on redelivery
        os.makedirs(MEDIA_DIR, exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(content)
    return _stable_url(filename)


def _graph_urls(att: dict) -> list[str]:
    """Every candidate download URL in a Graph attachment node — the shape
    differs per media kind (image_data / video_data / file_url) and between the
    webhook payload and the Graph read."""
    out: list[str] = []
    for holder in (att.get("image_data"), att.get("video_data"), att.get("payload")):
        if isinstance(holder, dict):
            out += [holder.get("url"), holder.get("src"), holder.get("preview_url")]
    out += [att.get("file_url"), att.get("url")]
    return [u for u in out if isinstance(u, str) and u.startswith("http")]


async def fetch_from_graph(mid: str) -> tuple[bytes, str, str] | None:
    """Re-fetch a message's attachment straight from Meta by message id.

    This is the ONLY way back once the webhook's CDN link has expired: the
    message node still exposes a freshly-signed attachment URL. Returns
    (content, content_type, media_type) or None when nothing is recoverable."""
    from app.services.meta_send import token_for_page
    token = token_for_page(None)
    if not token or not mid:
        return None
    base = f"https://graph.facebook.com/{settings.meta_graph_version}"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                f"{base}/{mid}",
                params={"fields": "attachments"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if not resp.is_success:
                _log.warning("graph attachment read failed (%s) for mid=%s",
                             resp.status_code, mid)
                return None
            for att in ((resp.json().get("attachments") or {}).get("data") or []):
                mime = (att.get("mime_type") or "").lower()
                kind = ("image" if mime.startswith("image") else
                        "video" if mime.startswith("video") else
                        "audio" if mime.startswith("audio") else
                        "image" if att.get("image_data") else
                        "video" if att.get("video_data") else "file")
                for url in _graph_urls(att):
                    got = await client.get(url)
                    if got.is_success and got.content:
                        return got.content, got.headers.get("content-type", mime), kind
    except Exception:
        _log.exception("graph attachment recovery failed for mid=%s", mid)
    return None


async def _rehost(channel: str, mid: str, cdn_url: str, media_type: str) -> None:
    from app.database import AsyncSessionLocal
    try:
        stable = None
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(cdn_url)   # Meta attachment URLs are pre-signed
            if resp.is_success and resp.content:
                stable = await _store(resp.content, resp.headers.get("content-type", ""),
                                      channel, mid, media_type)
            else:
                _log.warning("meta media fetch %s failed (%s) for mid=%s — "
                             "trying Graph", media_type, resp.status_code, mid)
        if stable is None:
            # The link died before we got to it; ask Meta for a fresh one.
            got = await fetch_from_graph(mid)
            if got is None:
                return
            content, ctype, kind = got
            stable = await _store(content, ctype, channel, mid, media_type or kind)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Message)
                .where(Message.channel == channel, Message.waba_msg_id == mid)
                .values(media_url=stable)
            )
            await db.commit()
        _log.info("meta media rehosted mid=%s -> %s", mid, stable)
    except Exception:
        _log.exception("meta media rehost failed for mid=%s", mid)


async def repair_pending(db, *, limit: int = 25) -> int:
    """Heal rows still pointing at Meta's CDN.

    Anything the webhook's fire-and-forget re-host missed (a crash, a restart,
    an unwritable media dir) keeps an expiring link. This sweep re-hosts them
    while they are still alive, and falls back to a Graph re-fetch when they
    are not. Runs on the actions heartbeat, newest first — recent media is both
    the most recoverable and the most likely to be on screen."""
    from sqlalchemy import select
    from app.services.meta_send import META_CHANNELS

    rows = (await db.execute(
        select(Message)
        .where(Message.channel.in_(META_CHANNELS),
               Message.media_type.isnot(None),
               Message.media_type != "note",
               Message.waba_msg_id.isnot(None))
        .order_by(Message.created_at.desc())
        .limit(400)
    )).scalars().all()

    healed = 0
    for m in rows:
        if not is_ephemeral(m.media_url):
            continue
        await _rehost(m.channel, m.waba_msg_id, m.media_url, m.media_type or "image")
        healed += 1
        if healed >= limit:
            break
    if healed:
        _log.info("meta media repair pass: %d attempted", healed)
    return healed


async def recover_one(db, message) -> str | None:
    """On-demand recovery for a single message (the inbox's 'Recover' button).
    Returns the new media_url, or None when Meta has nothing left to give."""
    if message.media_url and not is_ephemeral(message.media_url):
        return message.media_url          # already durable
    mid = message.waba_msg_id
    if not mid:
        return None
    if message.media_url:
        await _rehost(message.channel, mid, message.media_url,
                      message.media_type or "image")
    else:
        got = await fetch_from_graph(mid)
        if got is None:
            return None
        content, ctype, kind = got
        stable = await _store(content, ctype, message.channel, mid, kind)
        await db.execute(update(Message).where(Message.id == message.id)
                         .values(media_url=stable, media_type=message.media_type or kind))
        await db.commit()
        return stable
    await db.refresh(message)
    return message.media_url if not is_ephemeral(message.media_url) else None


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
