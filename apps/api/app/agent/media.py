"""Turn a customer's inbound image into a Claude vision block for the Tier 2 agent.

Two sources, one loader:
- WhatsApp: n8n downloads every inbound media file to /var/neema/media/{id}{ext}
  — the same container the agent runs in — so we map the stored URL back to the
  local file and base64 it.
- Messenger/Instagram/Facebook: the webhook hands us a signed Meta CDN URL (the
  re-host to /var/neema/media runs concurrently and may not have finished), and
  comment engagement hands us a post-thumbnail URL — both remote. When the URL
  doesn't resolve to a local file we fetch it over HTTPS with the same size and
  type guards.

Either way the agent SEES the photo natively (Claude vision) — no OCR, no
separate vision service. Voice notes need no handling here: n8n already
transcribes them into the message text the agent reads.

`load_image_block` does blocking I/O (disk or network) — async callers must run
it via `asyncio.to_thread`.
"""
from __future__ import annotations

import base64
import logging
import os
from urllib.parse import urlparse

_log = logging.getLogger("neema.agent")

MEDIA_DIR = "/var/neema/media"
_IMAGE_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
}
_REMOTE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_BYTES = 4_500_000  # keep under Anthropic's per-image limit; skip oversized


def _local_path(media_url: str | None) -> str | None:
    if not media_url:
        return None
    name = os.path.basename(urlparse(media_url).path)
    return os.path.join(MEDIA_DIR, name) if name else None


def _fetch_remote(url: str) -> dict | None:
    """Download a remote image (Meta CDN attachment / post thumbnail) into a
    base64 image block. None on any failure — the turn then runs text-only."""
    import httpx
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True)
        if not resp.is_success:
            _log.warning("remote media fetch failed (%s) for %s", resp.status_code, url[:120])
            return None
        mime = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        if mime not in _REMOTE_MIME:
            return None
        if not resp.content or len(resp.content) > _MAX_BYTES:
            return None
        data = base64.standard_b64encode(resp.content).decode("ascii")
    except Exception as exc:
        _log.warning("remote media fetch failed for %s: %s", url[:120], exc)
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}


def _from_data_url(data_url: str) -> dict | None:
    """Parse a `data:image/…;base64,…` URL (the web chat widget uploads photos
    this way) into a base64 image block. None if it isn't a base64 image data
    URL, has an unsupported type, or is too large."""
    try:
        header, _, payload = data_url.partition(",")
        if not payload or "base64" not in header:
            return None
        mime = header[5:].split(";")[0].strip().lower()   # strip 'data:'
        if mime not in _REMOTE_MIME:
            return None
        raw = base64.b64decode(payload, validate=False)
        if not raw or len(raw) > _MAX_BYTES:
            return None
        data = base64.standard_b64encode(raw).decode("ascii")
    except Exception as exc:
        _log.warning("data-url image decode failed: %s", exc)
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}


def load_image_block(media_url: str | None) -> dict | None:
    """An Anthropic base64 image block for the image at `media_url` — decoded
    inline from a `data:` URL, read from the local media store when the URL maps
    to a file there, or fetched over HTTPS otherwise. None if missing, not an
    image, unreadable, or too large."""
    if media_url and media_url.startswith("data:"):
        return _from_data_url(media_url)
    path = _local_path(media_url)
    if path and os.path.isfile(path):
        mime = _IMAGE_MIME.get(os.path.splitext(path)[1].lower())
        if not mime:
            return None
        try:
            size = os.path.getsize(path)
            if size <= 0 or size > _MAX_BYTES:
                return None
            with open(path, "rb") as f:
                data = base64.standard_b64encode(f.read()).decode("ascii")
        except OSError as exc:
            _log.warning("could not read media %s: %s", path, exc)
            return None
        return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}
    if media_url and media_url.startswith(("http://", "https://")):
        return _fetch_remote(media_url)
    return None
