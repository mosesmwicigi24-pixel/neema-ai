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
     A caption that ENUMERATES several items as one outfit ("complete
     cassock set: cassock, shirt, collar, cincture belt and stole") is a
     SET, never one of its pieces: the hub's own set row that covers every
     listed item, else the listed rows totalled (owner, 2026-09-21 — see
     product_set_from_caption / bundle_from_caption).
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


# ── a SET is priced as its total (owner, 2026-09-21) ─────────────────────────
# "This explanation of the pricing for this cassock should include all the
# items listed there — the shirt and the collar, the cassock, the signature
# belt and the stole — so that you give the accurate figure from the hub. If
# the description describes a product that has different combinations of
# items, we should always do the total and give that. Because if we give just
# one item, people will misunderstand it to mean that that is the total amount
# of the entire set."
#
# Live, the caption ladder read exactly such a caption and picked ONE row by
# name containment — "Cassock" ($120), or the CINCTURE BELT ($30) when the
# belt's two-word name was the longest match — and stamped it "caption",
# trusted. The rules below: a caption that ENUMERATES several catalogue items
# (a run of list pieces each naming one kind of item — "cassock, shirt,
# collar, cincture belt and stole") never resolves to one of them. It is the
# hub's own SET row whose contents cover every listed item (the hub prices
# the set as ONE figure — "Cassock Set", $200, "comes with cassock, stole,
# belt, straight collar shirt and a 12 inch clergy collar"), or, with no such
# row, the listed rows TOTALLED when each resolves to exactly one hub row;
# anything less is nothing — the model reads the caption with the same rule.

_SET_WORDS = frozenset({"set", "kit", "outfit", "package", "bundle", "combo"})
# Words a caption uses when several items are ONE product (a set, an outfit,
# a person robed in it) — a plain listing ("we have restocked cassocks, stoles
# and shirts") carries none of them and stays a listing.
_SET_CUE_RE = re.compile(
    r"\b(?:complete|full|whole|entire|sets?|outfits?|attire|regalia|kit|package|"
    r"bundle|combo|pieces?|comes?\s+with|comes?\s+complete|includes?|including|"
    r"included|inclusive|together|all[\s-]in[\s-]one|everything|wearing|wears?|"
    r"dressed|robed|congratulations?|ordination|consecration|installation|"
    r"seti|kamili|nzima)\b|\+|&",
    re.IGNORECASE)
# The pieces of a list: commas, "and", "&", "+", "with", Swahili "na", a
# colon or a dash. A slash is NOT a separator ("Tallits / Prayer shawls" is
# one item with two names).
_LIST_SEP_RE = re.compile(r"\s*(?:,|;|\n|\band\b|&|\+|\bplus\b|\bwith\b|\bna\b|—|–|:)\s*",
                          re.IGNORECASE)
_PACK_WORDS = frozenset({"pc", "pcs", "piece", "pack"})
_ARTICLES = ("a ", "an ", "the ")


def _name_tokens(text: str) -> list[str]:
    """Runtime's caption stemming (plural 's' off, 1–2 letter fragments out),
    on a size-stripped name — imported lazily: runtime imports this module."""
    from app.agent.runtime import _caption_token_seq, _strip_size
    return _caption_token_seq(_strip_size(text or ""))


def is_set_row(row: dict | None) -> bool:
    """A hub row that IS a set — its name says so ("Cassock Set", "Cope —
    Complete Set", "Double Stacked Silver Tray Set")."""
    if not row:
        return False
    return bool(_SET_WORDS & set(_name_tokens(row.get("name") or "")))


def product_kind(row: dict | None) -> str:
    """What KIND of item a hub row is — the head noun of its name ("Straight
    Collar Shirt" → shirt, "Straight Collar" → collar, "CINCTURE BELT" → belt,
    "Round Collar Clergy Shirt" → shirt, "Tallit (Prayer Shawl) - Medium" →
    tallit); "set" for a set row. Read on the name's first segment (before a
    dash, colon or bracket — "Aluminium 4-Stack Communion Set — 160 Cups" is
    a set, not cups), digits and pack words skipped. "" when there is none."""
    if not row:
        return ""
    if is_set_row(row):
        return "set"
    from app.agent.runtime import _strip_size
    name = _strip_size(row.get("name") or "")
    head = re.split(r"\s+[—–-]\s+|:|\(", name, maxsplit=1)[0]
    toks = [t for t in _name_tokens(head) if not any(ch.isdigit() for ch in t)
            and t not in _PACK_WORDS]
    return toks[-1] if toks else ""


def _kinds_of(catalog: list[dict]) -> dict[str, list[dict]]:
    """kind → the non-set rows of that kind."""
    out: dict[str, list[dict]] = {}
    for p in catalog:
        if not p.get("name") or is_set_row(p):
            continue
        k = product_kind(p)
        if k:
            out.setdefault(k, []).append(p)
    return out


def _piece_tokens(text: str) -> list[str]:
    """Runtime's caption stemming, with NUMBERS kept as tokens ("40 cups" must
    still show the 40 that makes the cups a capacity, not an item)."""
    from app.agent.runtime import _CAPTION_NORM
    out = []
    for t in re.findall(r"[a-z0-9']+", (text or "").lower()):
        t = _CAPTION_NORM.get(t, t)
        if t.isdigit():
            out.append(t)
        elif len(t) > 2:
            out.append(t[:-1] if t.endswith("s") and len(t) > 3 else t)
    return out


def _piece_kind(piece: str, kinds: dict) -> str:
    """The item a list piece names: the LAST kind word in it ("straight collar
    shirt" → shirt, "12 inch clergy collar" → collar). A kind word right after
    a number is a capacity or a count, not an item ("holds 40 cups")."""
    toks = _piece_tokens(piece)
    found = ""
    for i, t in enumerate(toks):
        if t in kinds and not (i > 0 and toks[i - 1].isdigit()):
            found = t
    return found


def caption_item_kinds(caption: str, catalog: list[dict]) -> list[str]:
    """The kinds of item a caption ENUMERATES as a list — two or more list
    pieces in a row, each naming one kind ("cassock, shirt, collar, cincture
    belt and stole" → [cassock, shirt, collar, belt, stole]). [] for a caption
    that names one item, or none, or mentions a second kind only in passing
    ("Silver Communion Trays in stock. Each holds 40 cups")."""
    text = _canonical(caption or "")
    if not text.strip():
        return []
    kinds = _kinds_of(catalog)
    if not kinds:
        return []
    pieces = [p for p in _LIST_SEP_RE.split(text) if p and p.strip()]
    per_piece = [_piece_kind(p, kinds) for p in pieces]
    best: list[str] = []
    run: list[str] = []
    for k in per_piece + [""]:
        if k:
            run.append(k)
            continue
        if len(run) > len(best):
            best = run
        run = []
    if len(best) < 2:
        return []
    out: list[str] = []
    for k in best:
        if k not in out:
            out.append(k)
    return out


# The parts a set's description may list that are not hub rows of their own
# ("comes with lid, holder and basin").
_PART_WORDS = frozenset({
    "lid", "holder", "basin", "stand", "base", "cover", "paten", "cup", "tray",
    "plate", "bowl", "chain", "cord", "tassel", "bag", "box", "case", "spoon",
    "boat", "stopper", "insert", "collar", "belt", "stole", "shirt", "cassock",
    "rope", "cincture", "cap", "mitre", "ring", "cross",
})


def set_components(row: dict | None, catalog: list[dict] | None = None) -> list[str]:
    """What a SET row comes with, from the hub's own description — the
    enumerated segment of it ("Complete cassock outfit in one order — cassock,
    stole, belt, straight collar shirt and a 12 inch clergy collar." →
    [cassock, stole, belt, straight collar shirt, 12 inch clergy collar]).
    Every item must BE a part — a kind the hub sells as a row (with the
    catalogue in hand) or a known part word — so a description's flourishes
    ("light and dignified carry") never come out as contents. [] when the
    description enumerates nothing ("supplied as a complete coordinated
    set"): then the set is priced as one and its contents are the model's to
    read, never a canned line's to invent."""
    if not row or not is_set_row(row):
        return []
    desc = " ".join(str(row.get("description") or "").split())
    if not desc:
        return []
    kinds: dict = {k: None for k in _PART_WORDS}
    if catalog:
        kinds.update(_kinds_of(catalog))
    segments = re.split(r"\s+[—–]\s+|:\s+|\bcomes?\s+with\b|\bincludes?\b|\bincluding\b",
                        desc, flags=re.IGNORECASE)
    best: list[str] = []
    for seg in segments:
        items = [it.strip(" .;!") for it in re.split(r",|\band\b|&|\+", seg, flags=re.IGNORECASE)]
        items = [it for it in items if it and re.search(r"[a-z]", it, re.IGNORECASE)]
        cleaned = []
        for it in items:
            low = it.lower()
            for art in _ARTICLES:
                if low.startswith(art):
                    it, low = it[len(art):], low[len(art):]
                    break
            it = it.strip()
            if 0 < len(it.split()) <= 5 and _piece_kind(it, kinds):
                cleaned.append(it)
        if len(cleaned) >= 2 and len(cleaned) >= len(items) - 1 and len(cleaned) > len(best):
            best = cleaned
    return best[:8]


def _phrase_in(hay_seq: list[str], needle_seq: list[str]) -> bool:
    n = len(needle_seq)
    return n > 0 and any(hay_seq[i:i + n] == needle_seq for i in range(len(hay_seq) - n + 1))


def caption_record_stale(known: dict | None, caption: str, catalog: list[dict]) -> bool:
    """A recorded identity the caption ladder would no longer produce: stamped
    "caption" while the caption ENUMERATES several items and the record is one
    of the pieces — not a set row, not a bundle. Live, a five-piece outfit's
    post carried "Cassock" that way, trusted for thirty days (owner,
    2026-09-21); the ladder re-reads such a post."""
    if not known or not known.get("name") or str(known.get("source") or "") != "caption":
        return False
    if known.get("bundle"):
        return False
    if len(caption_item_kinds(caption or "", catalog)) < 2:
        return False
    slug = (known.get("slug") or "").lower()
    row = next((p for p in catalog if slug and (p.get("slug") or "").lower() == slug), None)
    if row is None:
        row = next((p for p in catalog if (p.get("name") or "").lower() == str(known["name"]).lower()), None)
    return not is_set_row(row)


def product_set_from_caption(caption: str, catalog: list[dict],
                             kinds: list[str] | None = None) -> dict | None:
    """The hub SET row a caption is about, when it enumerates several items as
    ONE outfit: the caption carries a set cue ("complete", "set", "comes
    with", a person "robed in"…) and one set row's contents cover every
    listed kind — or the caption spells out a set row's full name. Scored by
    how much of the row's NAME the caption carries (the phrase "cassock set"
    in order is decisive), then by how many of its contents were listed; a
    tie between two set rows is None — never a guess. The row comes back
    with `components` (what it comes with) and `set: True`."""
    text = _canonical(caption or "")
    if not text.strip():
        return None
    kinds = list(kinds) if kinds is not None else caption_item_kinds(text, catalog)
    if len(kinds) < 2 or not _SET_CUE_RE.search(text):
        return None
    from app.agent.runtime import _caption_token_seq
    cap_seq = _caption_token_seq(text)
    cap_toks = set(cap_seq)
    want = set(kinds)
    by_kind = _kinds_of(catalog)
    scored = []
    for p in catalog:
        if not p.get("name") or not is_set_row(p):
            continue
        comps = set_components(p, catalog)
        comp_kinds = {k for k in (_piece_kind(c, by_kind) for c in comps) if k}
        name_seq = _name_tokens(p.get("name") or "")
        named = _phrase_in(cap_seq, name_seq) and len(name_seq) >= 2
        # The caption lists (nearly) the whole set — every listed kind is a
        # part of it, and at most one part went unlisted. "Complete set:
        # cassock and stole" is not the five-piece Cassock Set.
        covers = bool(comp_kinds) and want <= comp_kinds and len(comp_kinds - want) <= 1
        if not (covers or named):
            continue
        ntoks = set(name_seq)
        coverage = len(ntoks & cap_toks) / len(ntoks) if ntoks else 0.0
        score = (round(coverage, 3), 1 if named else 0, len(ntoks & cap_toks),
                 len(comp_kinds & want), -len(comp_kinds - want))
        scored.append((score, p))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None                       # two sets fit equally — the model decides
    best = dict(scored[0][1])
    best["set"] = True
    best["components"] = set_components(best, catalog)
    return best


def bundle_from_caption(caption: str, catalog: list[dict],
                        kinds: list[str] | None = None) -> dict | None:
    """With no hub set row to cover them, the listed items TOTALLED — only when
    every listed kind resolves to exactly ONE hub row (its full name in the
    caption, or the only row of that kind). A kind the hub sells in several
    rows ("stole": single-sided, double-sided, self-print) with nothing in the
    caption to pick one is ambiguous, and an ambiguous bundle is None. The
    result is a synthetic row: the items' names joined with " + ", the KES and
    USD totals (USD only when every item carries the hub's own USD), the
    dearest item's slug for the link, and `bundle` = the items."""
    text = _canonical(caption or "")
    if not text.strip():
        return None
    kinds = list(kinds) if kinds is not None else caption_item_kinds(text, catalog)
    if len(kinds) < 2 or not _SET_CUE_RE.search(text):
        return None
    from app.agent.runtime import _caption_token_seq
    cap_seq = _caption_token_seq(text)
    by_kind = _kinds_of(catalog)
    items: list[dict] = []
    for k in kinds:
        rows = by_kind.get(k) or []
        named = [r for r in rows if _phrase_in(cap_seq, _name_tokens(r.get("name") or ""))]
        if named:
            named.sort(key=lambda r: -len(_name_tokens(r.get("name") or "")))
            if len(named) > 1 and len(_name_tokens(named[0].get("name") or "")) == \
                    len(_name_tokens(named[1].get("name") or "")):
                return None               # two rows spelled out for one kind
            items.append(named[0])
        elif len(rows) == 1:
            items.append(rows[0])
        else:
            return None                   # several rows of this kind — no guess
    return bundle_row(items)


def bundle_row(items: list[dict]) -> dict | None:
    """ONE synthetic row for several hub rows sold together: the names joined
    with " + ", the KES total, the USD total when every item carries the
    hub's own USD (else None, and the public price converts the KES total),
    the dearest item's slug for the link, and `bundle` = the items. None
    with fewer than two items or an unpriced one — no total to give."""
    items = [r for r in (items or []) if r and r.get("name")]
    if len(items) < 2:
        return None

    def _num(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None

    kes = [_num(r.get("price")) for r in items]
    if any(v is None for v in kes):
        return None                       # an unpriced piece — no total to give
    usd = [_num(r.get("price_usd")) for r in items]
    dearest = max(items, key=lambda r: _num(r.get("price")) or 0.0)
    # Tailored when any piece is: the colour is then the customer's to say.
    mto = any(r.get("product_type") == "variable" and bool(r.get("is_producible")) for r in items)
    return {
        "name": " + ".join(str(r.get("name")) for r in items),
        "slug": dearest.get("slug") or "",
        "hub_product_id": None,
        "category": dearest.get("category") or "",
        "price": float(sum(kes)),
        "price_usd": float(sum(usd)) if all(v is not None for v in usd) else None,
        "product_type": "variable" if mto else "simple", "is_producible": mto,
        "description": "", "images": [],
        "bundle": [{"name": str(r.get("name")), "slug": r.get("slug") or ""} for r in items],
        "bundle_rows": [dict(r) for r in items],
    }


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
        llm = build_llm(model=settings.tier2_model_light, purpose="vision", cache=False)
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
    m = _SLUG_RE.search(title) if title else None
    if m:
        slug = m.group(1).lower()
        for p in catalog:
            if (p.get("slug") or "").lower() == slug:
                return with_provenance(p, "link")
    kinds = caption_item_kinds(title, catalog) if title else []
    if len(kinds) >= 2:
        # Several items listed as one outfit: the set row that covers them,
        # else their total — and NEVER one of the pieces by name (owner,
        # 2026-09-21: "Cassock" was sold under a five-piece set).
        hit = product_set_from_caption(title, catalog, kinds=kinds) \
            or bundle_from_caption(title, catalog, kinds=kinds)
        if hit is not None:
            return with_provenance(hit, "caption")
    else:
        hit = product_from_caption(title, catalog)
        if hit is None and title:
            # The hub's names SCORED against the whole caption (runtime's
            # scorer: coverage, the phrase in order, an alias, size families,
            # a near-tie is None). It used to run only as the comment
            # resolver's fallback — after the model had already read the
            # post; so a caption saying "Premium Bishop's Ring" (the hub's
            # "Ring", too short a name for containment) went to the model,
            # which picked the Apostolic Ring off a photo the two rows share
            # (owner, 2026-09-23). Deterministic first.
            from app.agent.runtime import _hub_caption_match
            hit = _hub_caption_match(catalog, title)
        if hit is not None:
            return with_provenance(hit, "caption")
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
