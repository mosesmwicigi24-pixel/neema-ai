"""The post catalogue: every page post resolved to its product AHEAD of time.

The reframe that ends comment-time guessing: a Facebook/Instagram page has a
FINITE set of posts, and the business knows what it posted. So instead of
identifying the product per comment (a coin flip repeated for every commenter),
each post is resolved ONCE — deterministically where possible — and the answer
is stored as the post's identity (runtime's postprod record). Comments then
LOOK UP, never identify.

The resolution ladder, strongest ground truth first:
  1. A storefront link in the caption (bethanyhouse.co.ke/product/<slug>) —
     exact, zero inference. (Also simply good marketing to include.)
  2. A catalogue product NAME or ALIAS appearing in the caption/attachment
     text — deterministic string containment against the hub's rich alias
     lists ("mkate wa ushirika", "sinia ya mkate", …), longest match wins.
  3. IMAGE FINGERPRINT: the post photo hashed (dHash, 64-bit) against every
     hub catalogue image. Validated on the live hub images: distinct products
     sit 21–36 bits apart while the same image after Facebook's
     resize/recompression moves 0–8 bits — a <=10 threshold with a clear
     runner-up margin identifies a reposted catalogue photo with certainty.
     No model involved.
  4. Unresolved → left for the model's careful read (features over finish) on
     first contact, and for the team's one-tap override
     (POST /admin/posts/{post_id}/product).

`sweep_page_posts` walks the page's recent posts on a daily tick so posts are
identified BEFORE the first comment ever lands. Everything is best-effort: a
Graph hiccup or an unreadable image never blocks a reply.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re

import httpx

from app.core.config import settings

_log = logging.getLogger("neema.postcat")

# Same-image threshold, validated empirically against the live hub images
# (worst same-image transform: 8 bits; closest distinct pair: 21 bits).
HASH_MATCH_MAX = 10
# The winner must beat the runner-up by this margin, or we call it ambiguous.
HASH_MARGIN_MIN = 5

_SLUG_RE = re.compile(r"bethanyhouse\.co\.ke/product/([a-z0-9\-]+)", re.IGNORECASE)

UNRESOLVED_KEY = "postcat:unresolved"       # redis: count from the last sweep


# ── the deterministic rungs ──────────────────────────────────────────────────


def product_from_caption(text: str, catalog: list[dict]) -> dict | None:
    """Rungs 1+2: a storefront slug link, else a product name/alias contained
    in the caption. Longest match wins so 'Silver Communion Tray' beats
    'Silver Tray' when both appear."""
    t = " ".join((text or "").lower().split())
    if not t:
        return None
    m = _SLUG_RE.search(t)
    if m:
        slug = m.group(1).lower()
        for p in catalog:
            if (p.get("slug") or "").lower() == slug:
                return p
    best, best_len = None, 0
    for p in catalog:
        candidates = [p.get("name") or ""] + list(p.get("aliases") or [])
        for c in candidates:
            c_norm = " ".join(c.lower().split())
            if len(c_norm) >= 6 and c_norm in t and len(c_norm) > best_len:
                best, best_len = p, len(c_norm)
    return best


def dhash_bytes(raw: bytes, size: int = 8) -> int | None:
    """64-bit difference hash of an image. None when the bytes don't decode."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
        px = list(g.getdata())
        bits = 0
        for row in range(size):
            for col in range(size):
                bits = (bits << 1) | (1 if px[row * (size + 1) + col] >
                                      px[row * (size + 1) + col + 1] else 0)
        return bits
    except Exception:
        return None


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


async def _fetch_bytes(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(url, timeout=20.0)
        return r.content if r.is_success else None
    except Exception:
        return None


async def _catalog_fingerprints(redis, catalog: list[dict]) -> list[tuple[dict, int]]:
    """(product, dhash) for every catalogue image, cached per image URL so the
    fleet computes each fingerprint once a month, not once a comment."""
    out: list[tuple[dict, int]] = []
    for p in catalog:
        for im in (p.get("images") or [])[:3]:
            url = im.get("url") or im.get("image_url") or ""
            if not url:
                continue
            key = "imghash:" + hashlib.sha1(url.encode()).hexdigest()[:16]
            h = None
            if redis is not None:
                try:
                    cached = await redis.get(key)
                    if cached is not None:
                        h = int(cached)
                except Exception:
                    pass
            if h is None:
                raw = await _fetch_bytes(url)
                h = dhash_bytes(raw) if raw else None
                if h is not None and redis is not None:
                    try:
                        await redis.set(key, str(h), ex=30 * 24 * 3600)
                    except Exception:
                        pass
            if h is not None:
                out.append((p, h))
    return out


async def product_from_image(redis, thumb_url: str, catalog: list[dict]) -> dict | None:
    """Rung 3: fingerprint the post image and find the catalogue image it IS.
    Only a confident, unambiguous winner counts — a near-tie is None."""
    if not thumb_url:
        return None
    raw = await _fetch_bytes(thumb_url)
    h = dhash_bytes(raw) if raw else None
    if h is None:
        return None
    scored = sorted(((hamming(h, ph), p) for p, ph in
                     await _catalog_fingerprints(redis, catalog)),
                    key=lambda x: x[0])
    if not scored or scored[0][0] > HASH_MATCH_MAX:
        return None
    if len(scored) > 1:
        runner = next((d for d, p in scored[1:]
                       if p.get("slug") != scored[0][1].get("slug")), 64)
        if runner - scored[0][0] < HASH_MARGIN_MIN:
            return None                    # two products this close = ambiguous
    return scored[0][1]


# ── the resolver + the sweep ─────────────────────────────────────────────────


async def resolve_post(redis, pctx: dict, catalog: list[dict]) -> dict | None:
    """One post → its product, by the ladder. None = leave it to the model's
    careful read and the team override."""
    title = (pctx.get("title") or "").strip()
    hit = product_from_caption(title, catalog)
    if hit is None:
        hit = await product_from_image(redis, (pctx.get("thumb") or "").strip(), catalog)
    return hit


async def sweep_page_posts(db, redis, limit: int = 25) -> dict:
    """Resolve the page's recent posts BEFORE anyone comments. Daily tick.
    Returns {checked, resolved, unresolved} and stores the unresolved count."""
    from app.agent.runtime import _recall_post_product, _remember_post_product
    from app.routers.meta_webhook import _post_context
    from app.services import n8n_bridge as svc

    page_id = (settings.meta_page_id or "").split(",")[0].strip()
    if not page_id or not settings.meta_page_token:
        return {"checked": 0, "resolved": 0, "unresolved": 0}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"https://graph.facebook.com/{settings.meta_graph_version}/{page_id}/posts",
                params={"fields": "id", "limit": limit},
                headers={"Authorization": f"Bearer {settings.meta_page_token}"},
                timeout=20.0)
        posts = [p.get("id") for p in (r.json().get("data") or []) if p.get("id")] \
            if r.is_success else []
    except Exception as exc:
        _log.info("post sweep: page listing failed: %s", exc)
        return {"checked": 0, "resolved": 0, "unresolved": 0}

    catalog = await svc.catalog_items(db, redis)
    checked = resolved = unresolved = 0
    for pid in posts:
        try:
            if (await _recall_post_product(redis, "facebook", pid)).get("name"):
                continue                          # already identified
            checked += 1
            pctx = await _post_context(pid, redis=redis, channel="facebook") or {}
            hit = await resolve_post(redis, pctx, catalog)
            if hit is not None:
                await _remember_post_product(redis, "facebook", pid, hit,
                                             thumb=(pctx.get("thumb") or "").strip())
                resolved += 1
                _log.info("post %s identified ahead of contact: %s", pid, hit.get("name"))
            else:
                unresolved += 1
        except Exception as exc:
            _log.info("post sweep: %s failed: %s", pid, exc)
    if redis is not None:
        try:
            await redis.set(UNRESOLVED_KEY, str(unresolved), ex=2 * 24 * 3600)
        except Exception:
            pass
    if unresolved:
        _log.warning("post sweep: %d recent post(s) unidentified — the team can "
                     "set them via POST /admin/posts/{post_id}/product", unresolved)
    return {"checked": checked, "resolved": resolved, "unresolved": unresolved}
