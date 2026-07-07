"""Read a customer's WhatsApp media from local disk for the Tier 2 agent.

n8n downloads every inbound media file to /var/neema/media/{media_id}{ext} — the
same container the agent runs in — and stores a stable URL on the message. We map
that URL back to the local file and base64 it into a Claude image block, so the
agent SEES product photos natively (Claude vision), with no extra download or
separate vision service. Voice notes need no handling here: n8n already
transcribes them into the message text the agent reads.
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
_MAX_BYTES = 4_500_000  # keep under Anthropic's per-image limit; skip oversized


def _local_path(media_url: str | None) -> str | None:
    if not media_url:
        return None
    name = os.path.basename(urlparse(media_url).path)
    return os.path.join(MEDIA_DIR, name) if name else None


def load_image_block(media_url: str | None) -> dict | None:
    """An Anthropic base64 image block for a locally-stored image, or None if the
    file is missing, not an image, unreadable, or too large."""
    path = _local_path(media_url)
    if not path or not os.path.isfile(path):
        return None
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
