"""The transcriber's vocabulary hint, built from the LIVE catalogue.

A voice note is only as sellable as its product words are heard: "ciborium",
"aspergillum", "tallit", "zucchetto", "chasuble", "kasoki", "sinia" are not
words a general speech model expects, and a misheard one is a lost item
("a train for a sacrament", "thoughts" for tots — both real). The static
list in services/transcribe was written once; the catalogue changes. This
builds the hint from what we sell today — the product kinds in the hub's own
names, the customers' Swahili/Sheng and French words for them
(core/vernacular, every one mapped to a stocked kind) and the payment words —
as a plain comma-separated list: no greeting, no sentence (a sentence in the
hint is what the model handed back as 30 customers' "speech"; see
transcribe.prompt_echo, which also guards this list).

Bounded (HINT_MAX_CHARS ≈ 200 tokens — inside whisper-1's 224-token prompt
window and short for gpt-4o-transcribe), de-duplicated by word, cached per
catalogue for an hour, and read only from the catalogue already cached in
redis (never a hub call on the transcription path). Any problem → None, and
the engine falls back to the static list.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time

_log = logging.getLogger("neema.transcribe")

HINT_MAX_CHARS = 900
_TTL = 3600.0
_cache: dict = {}            # {"key": catalogue fingerprint, "hint": str, "at": monotonic}

# Words a speech model already spells — they carry no teaching, so a phrase
# made only of them is not worth the hint's room.
_COMMON = frozenset("""
a an and the of for with to in on by set sets piece pieces pcs ml size sized small medium large
big normal white black red gold golden silver blue green purple brass plated coated stainless
steel double single sided side self print classic custom designed complete full new good news
ladies women men children childrens kids carry along day days favorite favourite stories for
brave boys girls with paten tray trays cup cups bread container containers bottle oil wine bag
ring bell shirt dress belt bible horn basket chain touch water executive gift gifts books cap
rope cord straight round offering
""".split())

# Kinds whose hub name is a brand or a size line, given the word customers use.
_PAYMENT = ("M-Pesa", "Paybill", "KES", "shilingi")


def _parts(name: str) -> list[str]:
    """The phrases one hub name offers: "Staff / Crozier / Shepherd Rod" →
    staff, crozier, shepherd rod; "Sprinkler (Aspergillum)" → sprinkler,
    aspergillum; "Ciborium — Gold Coated, Medium" → ciborium."""
    n = (name or "").strip()
    if not n:
        return []
    n = re.split(r"\s+[—–-]\s+|,", n)[0]
    out = []
    for piece in re.split(r"\s*/\s*|\(|\)", n):
        words = [w for w in re.findall(r"[A-Za-zÀ-ÿ'’]+", piece)]
        words = [w.lower() for w in words if len(w) > 1]
        # sizes and finishes are not what is heard wrongly
        words = [w for w in words if w not in ("pcs", "ml", "size", "sized", "medium", "small",
                                               "large", "normal", "coated", "the", "for", "with")]
        if 1 <= len(words) <= 3:
            out.append(" ".join(words))
    return out


def build_hint(catalog: list[dict], max_chars: int = HINT_MAX_CHARS) -> str:
    """The hint for this catalogue: distinctive product words first (the ones
    a speech model gets wrong), then how customers say them in Swahili and
    French, then the payment words — comma-separated, each word once, within
    `max_chars`."""
    from app.core.vernacular import SPOKEN_FRENCH, SPOKEN_SWAHILI

    def distinct(ph: str) -> int:
        return sum(w not in _COMMON for w in ph.split())

    # Tiers: (0) a one-word kind from a hub name — "chasuble", "ciborium",
    # "aspergillum", the words a speech model gets wrong; (1) a short name
    # phrase that is mostly such words — "pectoral cross", "communion tray";
    # (2) a one-word hub alias — "zucchetto", "censer", "shofar"; (3) the
    # rest. Books and Bibles go last: their titles are heard right.
    tiers: dict = {}
    for p in catalog or []:
        cat = (p.get("category") or "").lower()
        late = "bible" in cat or "book" in cat
        for ph in _parts(p.get("name") or ""):
            n = len(ph.split())
            d = distinct(ph)
            if not d:
                continue
            tier = 3 if late else (0 if n == 1 else (1 if d * 2 >= n else 3))
            tiers.setdefault(ph, tier)
            tiers[ph] = min(tiers[ph], tier)
        for a in p.get("aliases") or []:
            a = str(a).strip().lower()
            if re.fullmatch(r"[a-zà-ÿ]{5,}", a) and distinct(a):
                tiers.setdefault(a, 3 if late else 2)
    # The owner's own names for kinds (core/synonyms — "communion tray",
    # "pectoral cross", "communion cups"), when the catalogue sells them.
    from app.core.synonyms import hub_terms
    names = " ".join((p.get("name") or "").lower() for p in catalog or [])
    for term in hub_terms():
        if all(w in names for w in term.split()):
            tiers[term] = min(tiers.get(term, 1), 1)
    ranked = sorted(tiers, key=lambda ph: (tiers[ph], len(ph.split()), ph))
    tail = [*SPOKEN_SWAHILI, *SPOKEN_FRENCH, *_PAYMENT]
    room = max_chars - len(", ".join(tail)) - 2
    seen: set = set()
    chosen: list[str] = []
    used = 0
    for ph in ranked:
        words = set(ph.split())
        key_words = {w for w in words if w not in _COMMON}
        if not key_words or key_words <= seen:
            continue
        add = len(ph) + (2 if chosen else 0)
        if used + add > room:
            continue
        chosen.append(ph)
        seen |= words
        used += add
    for t in tail:
        if t.lower() in seen:
            continue
        add = len(t) + (2 if chosen else 0)
        if used + add > max_chars:
            break
        chosen.append(t)
        seen.add(t.lower())
        used += add
    return ", ".join(chosen)


async def _catalogue(redis) -> list[dict] | None:
    from app.core import hub_client
    for key in (hub_client._CACHE_KEY, hub_client._LAST_GOOD_KEY):
        try:
            raw = await redis.get(key)
        except Exception:
            return None
        if raw:
            try:
                items = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                if isinstance(items, list) and items:
                    return items
            except Exception:
                continue
    return None


async def live_hint(redis) -> str | None:
    """The hint for the catalogue cached right now, or None (no redis, no
    cached catalogue, any error) — the engine then uses the static list."""
    if redis is None:
        return None
    try:
        items = await _catalogue(redis)
        if not items:
            return None
        names = sorted(str(p.get("name") or "") for p in items if isinstance(p, dict))
        key = hashlib.sha256("\n".join(names).encode()).hexdigest()
        now = time.monotonic()
        if _cache.get("key") == key and now - _cache.get("at", 0) < _TTL:
            return _cache["hint"]
        hint = build_hint(items)
        _cache.update(key=key, hint=hint, at=now)
        return hint or None
    except Exception as exc:                      # noqa: BLE001 — a hint is never worth a failure
        _log.warning("transcribe: live vocabulary unavailable (%s) — static list", exc)
        return None
