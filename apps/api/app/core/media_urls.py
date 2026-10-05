"""Signed, expiring links to the media store (/api/admin/media/{filename}).

Why: the route cannot take a bearer token (<audio>/<img> tags can't send one,
and Meta fetches our outbound media itself), so until now any URL was a
permanent pass — and an inbound WhatsApp file is named wa_<Meta media id>,
which is not a secret. Now every URL the API hands out carries
`?exp=<unix seconds>&sig=<hex HMAC-SHA256 over "filename\\nexp">`.

Rules this module keeps:
  * The database stores the UNSIGNED canonical URL (or a bare file name).
    Signing happens at read time — in the serializer, on the live socket, at
    the moment of a send to Meta — so old rows keep working and nothing
    stored ever expires.
  * Only our own media URLs are touched: a path of exactly
    /api/admin/media/<name> (absolute on any host, or rooted), or a bare
    stored file name. Meta CDN links, hub product photos, storefront links
    pass through unchanged.
  * `exp` is rounded UP to a bucket (a quarter of the lifetime, ≥ 60 s), so
    every signing inside one bucket yields the identical URL: a thread poll
    every 20 s does not change every <img src> (no re-download, no flicker),
    and a live event and the next poll agree on the same string.
  * The key is derived from SECRET_KEY unless MEDIA_URL_SECRET is set — no new
    required secret. Rotating either invalidates outstanding links (they are
    re-signed on the next read).
"""
import hashlib
import hmac
import json
import logging
import re
import time
from urllib.parse import urlsplit

from app.core.config import settings

_log = logging.getLogger("neema.media")

MEDIA_PATH = "/api/admin/media/"
_PATH_RE = re.compile(r"^/api/admin/media/([^/]+)$")
_BARE_RE = re.compile(r"^[\w][\w.-]*$")          # a stored file name, never hidden
_SIG_RE = re.compile(r"^[0-9a-f]{64}$")
_EXP_RE = re.compile(r"^[0-9]{1,12}$")

# The keys that carry a media URL in API payloads and live socket events.
MEDIA_KEYS = frozenset({"media_url", "mediaUrl", "recording_url", "recordingUrl"})


def _key() -> bytes:
    base = (settings.media_url_secret or settings.secret_key or "").encode()
    if not base:
        # SECRET_KEY is a required setting, so this is a misconfiguration —
        # refuse to sign with an empty key rather than mint forgeable links.
        raise RuntimeError("no SECRET_KEY / MEDIA_URL_SECRET to sign media links with")
    return hmac.new(base, b"neema-media-url-v1", hashlib.sha256).digest()


def signature(filename: str, exp: int) -> str:
    return hmac.new(_key(), f"{filename}\n{int(exp)}".encode(), hashlib.sha256).hexdigest()


def media_filename(url: str | None) -> str | None:
    """The stored file name when `url` points into our media store, else None."""
    u = (url or "").strip()
    if not u:
        return None
    if _BARE_RE.match(u):
        return u
    try:
        parts = urlsplit(u)
    except ValueError:
        return None
    if parts.scheme in ("http", "https") or (not parts.scheme and not parts.netloc
                                             and parts.path.startswith("/")):
        m = _PATH_RE.match(parts.path)
        if m and not m.group(1).startswith("."):
            return m.group(1)
    return None


def canonical_media_url(url: str | None) -> str | None:
    """Our media URL without any query/fragment (what the database stores);
    anything else unchanged. Used where a client hands a URL back to us."""
    if not media_filename(url):
        return url
    u = url.strip()
    return u.split("#", 1)[0].split("?", 1)[0]


def _expiry(ttl: int, now: float | None = None) -> int:
    ttl = max(60, int(ttl))
    bucket = max(60, ttl // 4)
    t = int(now if now is not None else time.time()) + ttl
    return -(-t // bucket) * bucket                # ceil to the bucket boundary


def sign_media_url(url: str | None, ttl: int | None = None, *, now: float | None = None) -> str | None:
    """`url` with a fresh ?exp=&sig= when it points into our media store;
    unchanged otherwise (None stays None)."""
    name = media_filename(url)
    if not name:
        return url
    exp = _expiry(settings.media_url_ttl_seconds if ttl is None else ttl, now)
    return f"{canonical_media_url(url)}?exp={exp}&sig={signature(name, exp)}"


def sign_for_meta(url: str | None) -> str | None:
    """A link handed to Meta (WhatsApp Cloud API `link`, Messenger attachment
    `url`, carousel `image_url`). Meta fetches it when the send is processed
    (the Cloud API docs: it then caches the asset for 10 minutes); 24 h
    covers its retries with a wide margin. UNVERIFIED: whether Messenger
    re-fetches a generic-template image after the first render — if it does,
    an old carousel photo can go blank after a day once signing is required."""
    return sign_media_url(url, settings.media_url_meta_ttl_seconds)


def verify(filename: str, exp, sig, *, now: float | None = None) -> bool:
    """True only for an untampered, unexpired signature over this file name.
    Constant-time compare; any malformed input is simply False."""
    exp_s, sig_s = str(exp or ""), str(sig or "").lower()
    if not _EXP_RE.match(exp_s) or not _SIG_RE.match(sig_s):
        return False
    if int(exp_s) < int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(signature(filename, int(exp_s)), sig_s)


def sign_media_fields(obj, ttl: int | None = None):
    """A copy of `obj` (dict / list / scalars) with every MEDIA_KEYS string
    value signed — nested anywhere (a quoted message's media_url included)."""
    if isinstance(obj, dict):
        return {k: (sign_media_url(v, ttl) if k in MEDIA_KEYS and isinstance(v, str)
                    else sign_media_fields(v, ttl))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [sign_media_fields(x, ttl) for x in obj]
    return obj


def sign_ws_text(text):
    """A live-socket frame (JSON text) with its media URLs signed at delivery
    time. Every publisher goes through the one relay in routers/websocket.py,
    so no publisher can forget. A frame that is not JSON, or carries no media
    key, is relayed exactly as before."""
    if not isinstance(text, str) or not any(k in text for k in MEDIA_KEYS):
        return text
    try:
        event = json.loads(text)
    except ValueError:
        _log.debug("ws frame with a media key is not JSON — relayed as is")
        return text
    signed = sign_media_fields(event)
    return text if signed == event else json.dumps(signed)
