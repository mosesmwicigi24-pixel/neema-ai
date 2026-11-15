"""THE PHOTOS A CUSTOMER SENT, REMEMBERED (owner, 2026-11-15 — the Melchizkek
thread).

A customer chose three garments by sending photos: "make these two for me",
"this one is his", "all as in the picture". Neema could not follow, for three
plain reasons found in the code:

  * a burst of photos reached the turn as ONE picture (wa_native._drain);
  * in the history she reads back, a past photo was the bare words
    "[the customer sent a photo]" — nothing of what it showed;
  * a message that points at earlier photos ("these two") arrived with no
    picture at all.

So every photo a customer sends gets a NUMBER that stays with it ("photo 1",
"photo 2" — the same picture sent again keeps its number), and what the
existing photo check already knows about it (services/photo_check: "our own
photo of the Red Apostolic Cassock"). The history line carries both, and a
message that points at photos gets the recent ones put back in front of her.

No new table: the number and the reading ride the message's own `raw_meta`
(`raw_meta["photo"] = {"h", "n", "seen"}`). No new model call: the reading is
the photo check's cached result, when it has one.
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timedelta, timezone

from app.core.config import settings

_log = logging.getLogger("neema.photo_memory")

SAME_PHOTO_MAX = 6          # hamming distance on the 64-bit dhash: the same picture, re-sent
WINDOW_DAYS = 14            # photos older than this are not numbered into the thread


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _hash_of(block: dict | None) -> int | None:
    """The perceptual hash of an image block — the same picture sent twice
    hashes (near enough) the same, whatever WhatsApp did to the bytes."""
    try:
        from app.services.post_catalog import dhash_bytes
        raw = base64.standard_b64decode(((block or {}).get("source") or {}).get("data") or "")
        return dhash_bytes(raw) if raw else None
    except Exception:
        return None


def same_photo(a: int | None, b: int | None) -> bool:
    if a is None or b is None:
        return False
    from app.services.post_catalog import hamming
    return hamming(int(a), int(b)) <= SAME_PHOTO_MAX


def label(n: int) -> str:
    return f"photo {int(n)}"


def seen_words(check: dict | None) -> str:
    """What the photo check knows about a picture, in a few words for the
    history line — or "" when it knows nothing worth saying."""
    c = check or {}
    name = (c.get("product") or "").strip()
    verdict = c.get("verdict")
    if verdict == "ours" and name:
        return f"our own photo of the {name}"
    if verdict == "close" and name:
        return f"looks like our {name}, in another colour or size"
    if verdict == "refer" and name:
        return f"nearest item we sell: {name} — but not the same, a person should confirm"
    if verdict == "refer":
        return "not one of our catalogue items — a person should confirm"
    if verdict == "not_product":
        return "not a product photo"
    return ""


def history_line(meta: dict | None, fallback: str = "[the customer sent a photo]") -> str:
    """The line a past photo reads as in the transcript."""
    p = (meta or {}).get("photo") if isinstance(meta, dict) else None
    if not isinstance(p, dict) or not p.get("n"):
        return fallback
    seen = (p.get("seen") or "").strip()
    return f"[the customer sent {label(p['n'])}" + (f" — {seen}" if seen else "") + "]"


async def _photo_rows(db, *, channel: str, key: str, limit: int = 24) -> list:
    from sqlalchemy import select
    from app.models.message import Message, MsgDirection
    where = (Message.wa_id == key) if channel == "whatsapp" else (
        (Message.channel == channel) & (Message.external_id == key))
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    rows = list((await db.execute(
        select(Message).where(where, Message.direction == MsgDirection.inbound,
                              Message.media_type == "image", Message.media_url.isnot(None),
                              Message.created_at >= since)
        .order_by(Message.created_at.desc()).limit(limit))).scalars().all())
    return list(reversed(rows))


async def index(db, redis, *, channel: str, key: str, report: dict | None = None) -> list[dict]:
    """Number this contact's recent photos (oldest first) and return them:
    [{"n", "label", "url", "at", "seen", "caption"}]. A photo already
    numbered keeps its number; the same picture sent again takes the number
    of the first; a new one takes the next. What the photo check has cached
    for it is attached (and refreshed when it was not there before).
    Best-effort: on any failure the photos it could read are returned and
    nothing is raised."""
    out: list[dict] = []
    try:
        rows = await _photo_rows(db, channel=channel, key=key)
    except Exception as exc:
        _log.info("photo index: rows unreadable for %s: %s", key, exc)
        return out
    known: list[tuple[int, int]] = []          # (hash, number)
    for m in rows:
        p = (m.raw_meta or {}).get("photo") if isinstance(m.raw_meta, dict) else None
        if isinstance(p, dict) and p.get("n") and p.get("h") is not None:
            try:
                known.append((int(p["h"]), int(p["n"])))
            except (TypeError, ValueError):
                pass
    changed = False
    for m in rows:
        meta = dict(m.raw_meta) if isinstance(m.raw_meta, dict) else {}
        p = dict(meta.get("photo")) if isinstance(meta.get("photo"), dict) else {}
        block = None
        if not p.get("n"):
            try:
                import asyncio
                from app.agent.media import load_image_block
                block = await asyncio.to_thread(load_image_block, m.media_url)
            except Exception:
                block = None
            h = _hash_of(block)
            if h is None:
                continue                         # unreadable: stays the plain line
            n = next((num for kh, num in known if same_photo(kh, h)), None)
            if n is None:
                n = max((num for _, num in known), default=0) + 1
            known.append((h, n))
            p.update(h=h, n=n)
        if not p.get("seen") and redis is not None:
            try:
                import json
                from app.services import photo_check as _pc
                if block is None:
                    import asyncio
                    from app.agent.media import load_image_block
                    block = await asyncio.to_thread(load_image_block, m.media_url)
                sha = _pc.image_sha(block)
                cached = await redis.get(_pc._cache_key(sha)) if sha else None
                if cached:
                    words = seen_words(json.loads(cached))
                    if words:
                        p["seen"] = words
            except Exception:
                pass
        if p != (meta.get("photo") or {}):
            meta["photo"] = p
            m.raw_meta = meta
            try:
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(m, "raw_meta")
            except Exception:
                pass
            changed = True
        out.append({"n": int(p["n"]), "label": label(p["n"]), "url": m.media_url,
                    "at": _aware(m.created_at), "seen": p.get("seen") or "",
                    "caption": (m.media_caption or "").strip()})
    if changed:
        if report is not None:
            report["changed"] = True
        try:
            await db.commit()
        except Exception as exc:
            _log.info("photo index: numbers not saved for %s: %s", key, exc)
            try:
                await db.rollback()
            except Exception:
                pass
    return out


# A message that POINTS at a photo instead of naming a thing.
_POINTS_RE = re.compile(
    r"\b(?:th(?:is|ese|at|ose)\s+(?:one|ones|two|tow|three|3|2|set|sets|pic\w*|photo\w*|image\w*|"
    r"design\w*|colou?r\w*|cassock\w*|robe\w*|gown\w*|stole\w*|type|style|kind)|"
    r"(?:the\s+)?(?:same|one|ones)\s+(?:as\s+)?(?:in|on|from|you\s+(?:are\s+)?see\w*)|"
    r"as\s+(?:in|on|per)\s+(?:the\s+)?(?:pic\w*|photo\w*|image\w*)|"
    r"(?:in|on|from|like)\s+(?:the\s+|this\s+|that\s+|these\s+|my\s+)?(?:pic\w*|photo\w*|image\w*)|"
    r"(?:the\s+)?(?:first|second|third|last|other|purple|red|white|black|blue|green|gold)\s+one|"
    r"is\s+(?:mine|his|hers|ours|theirs)|(?:mine|his|hers)\b|both(?:\s+of\s+them)?|all\s+(?:of\s+them|three|two|in\s+set)|"
    r"hii|hizi|hiyo|hizo|kama\s+(?:hii|hiyo|picha)|kwa\s+picha)\b",
    re.IGNORECASE)


def points_at_photos(text: str | None) -> bool:
    """Does this message point at something shown ("these two", "this one is
    his", "all as in the picture", "the purple one") rather than name it?"""
    t = " ".join((text or "").split())
    return bool(t) and bool(_POINTS_RE.search(t))


def to_attach(photos: list[dict], text: str | None, *, have_urls: set[str] | None = None,
              now: datetime | None = None) -> list[dict]:
    """The earlier photos to put back in front of the model for THIS turn:
    the most recent distinct pictures, when the message points at photos (or
    is a few bare words — "Purple", "Yes", "These two") and they were sent
    within `photo_reference_minutes`. Never one already on the turn; newest
    kept, oldest first; capped by `turn_photos_max`."""
    if not photos:
        return []
    t = " ".join((text or "").split())
    short = 0 < len(t.split()) <= 4
    points = points_at_photos(t)
    if not (points or short):
        return []
    now = _aware(now) or datetime.now(timezone.utc)
    within = timedelta(minutes=int(getattr(settings, "photo_reference_minutes", 180) or 180))
    if not points:
        # A few bare words only earn the pictures while the photos are fresh
        # (the answer to "which colour?" right after them) — not an "ok" hours on.
        within = min(within, timedelta(minutes=20))
    have = set(have_urls or ())
    have_n = {p["n"] for p in photos if p.get("url") in have}
    picked: dict[int, dict] = {}
    for p in photos:                               # oldest → newest: the newest copy of a number wins
        if p.get("url") in have or p["n"] in have_n:
            continue
        if p.get("at") is not None and now - p["at"] > within:
            continue
        picked[p["n"]] = p
    cap = max(int(getattr(settings, "turn_photos_max", 4) or 4) - len(have), 0)
    newest = sorted(picked.values(), key=lambda p: p.get("at") or now)[-cap:] if cap else []
    return sorted(newest, key=lambda p: p["n"])
