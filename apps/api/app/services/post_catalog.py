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
from app.core.synonyms import canonical as _canonical

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
    t = " ".join(_canonical(text or "").lower().split())
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


# ── provenance: how sure we are, and why ────────────────────────────────────
# Every identity carries the rung that produced it and a confidence. The
# canned (no-model) reply may PRICE a post's product only on a trusted rung:
# the team's word, a storefront link, the hub's own name in the caption, the
# hub's own photo reposted, or a vision read CONFIRMED against the product's
# catalogue photo. A model's guess in a reply is never enough to sell blind
# (owner, 2026-09-21: a tallit post sold anointing oil, a dress design sold
# a bell, a cope post sold a ring — each a guess that reached a canned line).
SOURCE_CONFIDENCE = {
    "team": 1.0, "link": 1.0, "caption": 0.95, "image": 0.95,
    "vision": 0.9, "vision-name": 0.7, "model": 0.6, "legacy": 0.5,
}
TRUSTED_SOURCES = ("team", "link", "caption", "image", "vision")
TRUST_MIN = 0.8


def with_provenance(row: dict | None, source: str, confidence: float | None = None) -> dict | None:
    """A copy of the hub row stamped with how it was identified."""
    if row is None:
        return None
    out = dict(row)
    out["_identity_source"] = source
    out["_identity_confidence"] = float(SOURCE_CONFIDENCE.get(source, 0.5)
                                        if confidence is None else confidence)
    return out


def identity_trusted(record: dict | None) -> bool:
    """May this recorded identity feed a PRICE into a reply no model reads?"""
    if not record or not record.get("name"):
        return False
    src = str(record.get("source") or "")
    try:
        conf = float(record.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return src in TRUSTED_SOURCES and conf >= TRUST_MIN


_STOP = {
    "the", "and", "for", "with", "our", "your", "you", "this", "that", "these",
    "those", "from", "have", "has", "are", "was", "were", "new", "now", "today",
    "order", "orders", "make", "call", "calling", "bethany", "house", "shop",
    "available", "restocked", "restock", "stock", "stay", "tuned", "client",
    "clients", "design", "designs", "finished", "work", "show", "going", "gave",
    "share", "more", "please", "kindly", "all", "any", "one", "how", "much",
    "what", "where", "when", "which", "who", "why", "can", "get", "buy",
    "need", "want", "like", "just", "here", "there", "only", "also", "very",
    "south", "africa", "kenya", "nairobi", "world", "worldwide", "ship",
    "shipping", "delivery", "deliver", "price", "prices", "bei", "gani", "ngapi",
    "na", "ya", "wa", "za", "kwa", "sasa", "leo",
}


def _sig_tokens(text: str) -> set[str]:
    """Product-bearing words of a caption (no stop-words, no digits, stemmed of a
    plural 's') — the words that can point at a hub row."""
    out = set()
    for t in re.findall(r"[a-z]+", (text or "").lower()):
        if len(t) < 3 or t in _STOP:
            continue
        out.add(t[:-1] if t.endswith("s") and len(t) > 3 else t)
    return out


def vision_candidates(catalog: list[dict], caption: str = "", cap: int = 120) -> list[dict]:
    """The rows to show the vision read: those sharing a product word with the
    caption when it has any ("tallit", "cope"), else the whole shelf."""
    toks = _sig_tokens(caption)
    if toks:
        narrowed = []
        for p in catalog:
            words = _sig_tokens(" ".join([p.get("name") or ""] + [str(a) for a in (p.get("aliases") or [])]))
            if words & toks:
                narrowed.append(p)
        if narrowed:
            return narrowed[:cap]
    return [p for p in catalog if p.get("name")][:cap]


_NAME_RE = re.compile(r"NAME\s*=\s*(.+?)\s*(?:\||CONF|$)", re.IGNORECASE | re.DOTALL)
_CONF_RE = re.compile(r"CONF\s*=\s*(high|medium|low)", re.IGNORECASE)


def parse_vision_pick(text: str, candidates: list[dict]) -> tuple[dict | None, str]:
    """(row, confidence word) from the model's 'NAME=… CONF=…' line; (None, "")
    for NONE, an unlisted name, or anything else. The name must be one of the
    candidates EXACTLY (case-insensitive) — a paraphrase is not a row."""
    t = " ".join((text or "").split())
    if not t or t.strip().upper().startswith("NONE"):
        return None, ""
    m = _NAME_RE.search(t)
    if not m:
        return None, ""
    name = m.group(1).strip().strip("\"'`.")
    conf = (_CONF_RE.search(t).group(1).lower() if _CONF_RE.search(t) else "")
    for p in candidates:
        if (p.get("name") or "").strip().lower() == name.lower():
            return p, conf
    return None, ""


async def product_from_vision(redis, thumb_url: str, catalog: list[dict],
                              caption: str = "") -> dict | None:
    """Rung 3.5 — SEE the post photo and COMPARE it to the catalogue (owner,
    2026-09-21: "make the agent see the image, compare the image and give
    the correct prices").

    Two reads by the light model, no free text:
      1. the post photo beside the catalogue NAMES (narrowed by the caption's
         product words) — "which ONE listed item is the main item for sale?
         NAME=<exact name> CONF=high|medium|low, or NONE". Only an exact
         listed name at CONF=high goes on;
      2. the post photo beside THAT product's own catalogue photo — "SAME
         product or DIFFERENT?". Only SAME makes it a trusted identity
         (source "vision", 0.9). A pick with no catalogue photo to compare
         against is kept as "vision-name" (0.7): enough to steer the model's
         careful read, never enough to price a canned reply.
    A NONE / low / DIFFERENT result is remembered for a day per image so an
    unidentifiable post costs one pair of reads, not one per comment. Any
    failure → None; never blocks a reply."""
    if not thumb_url or not settings.tier2_vision:
        return None
    none_key = "postcat:vision-none:" + hashlib.sha1(thumb_url.encode()).hexdigest()[:16]
    if redis is not None:
        try:
            if await redis.get(none_key):
                return None
        except Exception:
            pass
    try:
        import asyncio
        from app.agent.runtime import build_llm      # lazy: runtime imports this module
        from app.agent.media import load_image_block
        post_block = await asyncio.to_thread(load_image_block, thumb_url)
        if not post_block:
            return None
        cands = vision_candidates(catalog, caption)
        if not cands:
            return None
        listing = "\n".join(f"{i + 1}. {p.get('name')}" for i, p in enumerate(cands))
        llm = build_llm(model=settings.tier2_model_light)
        resp = await llm.complete(
            system=("You identify which catalogue item a shop's post photo shows. You "
                    "answer only in the exact format asked, and you say NONE whenever "
                    "you are not sure. Never invent a name that is not in the list."),
            messages=[{"role": "user", "content": [
                post_block,
                {"type": "text", "text": (
                    "Catalogue items (name only):\n" + listing + "\n\n"
                    "Which ONE listed item is the main item for sale in this photo? "
                    "Judge the object itself — its type, shape, finish and colour — not the "
                    "caption. If it is a design drawing, a person, several items, or an item "
                    "not in the list, answer NONE.\n"
                    "Reply with exactly one line: NAME=<exact name from the list> | "
                    "CONF=<high|medium|low>   or   NONE")}]}],
            tools=[])
        row, conf = parse_vision_pick(resp.text or "", cands)
        result = None
        if row is not None and conf == "high":
            cat_url = ""
            for im in (row.get("images") or [])[:1]:
                cat_url = im.get("url") or im.get("image_url") or ""
            cat_url = cat_url or row.get("image_url") or ""
            if cat_url:
                cat_block = await asyncio.to_thread(load_image_block, cat_url)
                if cat_block:
                    resp2 = await llm.complete(
                        system=("You compare two product photos for a shop. Answer with one "
                                "word only: SAME or DIFFERENT."),
                        messages=[{"role": "user", "content": [
                            {"type": "text", "text": "Photo A (a post):"}, post_block,
                            {"type": "text", "text": f"Photo B (our catalogue photo of '{row.get('name')}'):"},
                            cat_block,
                            {"type": "text", "text": (
                                "Is the main item in Photo A the SAME product as Photo B — the "
                                "same kind of item, the same finish and colour? Lighting, angle "
                                "and background may differ. Answer SAME or DIFFERENT.")}]}],
                        tools=[])
                    verdict = (resp2.text or "").strip().upper()
                    if verdict.startswith("SAME"):
                        result = with_provenance(row, "vision")
                else:
                    result = with_provenance(row, "vision-name")
            else:
                result = with_provenance(row, "vision-name")
        if result is None and redis is not None:
            try:
                await redis.set(none_key, "1", ex=24 * 3600)
            except Exception:
                pass
        return result
    except Exception as exc:
        _log.info("vision identification skipped: %s", exc)
        return None


# ── the resolver + the sweep ─────────────────────────────────────────────────


async def resolve_post(redis, pctx: dict, catalog: list[dict]) -> dict | None:
    """One post → its product, by the ladder, each hit stamped with its rung
    (`_identity_source`, `_identity_confidence` — see with_provenance). None =
    leave it to the model's careful read and the team override."""
    title = (pctx.get("title") or "").strip()
    hit = product_from_caption(title, catalog)
    if hit is not None:
        src = "link" if _SLUG_RE.search(title) else "caption"
        return with_provenance(hit, src)
    thumb = (pctx.get("thumb") or "").strip()
    hit = await product_from_image(redis, thumb, catalog)
    if hit is not None:
        return with_provenance(hit, "image")
    return await product_from_vision(redis, thumb, catalog, caption=title)


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
