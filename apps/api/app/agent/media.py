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

from app.core.config import settings

_log = logging.getLogger("neema.agent")

MEDIA_DIR = settings.media_dir   # one definition, in Settings — see media_dir
_IMAGE_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
}
_REMOTE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_BYTES = 4_500_000  # keep under Anthropic's per-image limit; skip oversized


# Vision is billed by AREA (~ width x height / 750 after Anthropic's own 1568px
# server-side cap), and customers send phone photos at full resolution: a
# 4000x3000 original bills ~2,459 tokens even after the server downscale, while
# the same photo at 1092px on the long edge — Anthropic's documented sweet spot
# — bills ~1,192. Nothing a sales agent reads (which garment, which colour,
# which tray) needs more than 1092px, so every image is shrunk before it is
# base64'd: roughly HALF the vision tokens on every media turn, plus a much
# smaller request body over the wire. Best-effort by construction — a resize
# failure must never cost the customer their turn, so any error returns the
# original bytes untouched.
_MAX_EDGE = 1092


def _shrink(raw: bytes, mime: str) -> tuple[bytes, str]:
    """(bytes, mime) with the long edge capped at _MAX_EDGE — original on any
    failure or when the image is already small enough."""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        if max(img.size) <= _MAX_EDGE:
            return raw, mime
        img.thumbnail((_MAX_EDGE, _MAX_EDGE))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")          # drops alpha; JPEG needs it gone
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=82)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return raw, mime


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
        raw, mime = _shrink(resp.content, mime)
        data = base64.standard_b64encode(raw).decode("ascii")
    except Exception as exc:
        _log.warning("remote media fetch failed for %s: %s", url[:120], exc)
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}


def load_image_block(media_url: str | None) -> dict | None:
    """An Anthropic base64 image block for the image at `media_url` — read from
    the local media store when the URL maps to a file there, fetched over HTTPS
    otherwise. None if missing, not an image, unreadable, or too large."""
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
                raw = f.read()
        except OSError as exc:
            _log.warning("could not read media %s: %s", path, exc)
            return None
        raw, mime = _shrink(raw, mime)
        data = base64.standard_b64encode(raw).decode("ascii")
        return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}
    if media_url and media_url.startswith(("http://", "https://")):
        return _fetch_remote(media_url)
    return None
