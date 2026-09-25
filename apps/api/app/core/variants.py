"""ONE name for a variant, everywhere (owner, 2026-09-25: "take the variant +
attribute to get the product name and size, and apply it to all variants").

The hub names a variant loosely — "Straight Collar" six times over, "S / GOLD",
"Navy Straight Collar Shirt", "+ Black Pleats, Piping and Buttons" — and its
attributes ({Size: 8 inch}, {Colour: Navy}, {Size: M}) carry what the name
leaves out. The label every seam shows is

    <product name> — <what tells it apart>

"Straight Collar — 8 inch", "Straight Collar Shirt — Navy / Size L", "Thurible
— S / GOLD", "Red Apostolic Cassock — Black Pleats, Piping and Buttons / Size
M". The hub's own words come first (minus the product's name inside them, even
misspelt), then every attribute value those words do not already say. The
agent's search rows, the public catalogue, the cart line and the verifier all
read the same label, so a customer who says "the 10 inch" and the order that
follows name the same thing.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_EDGES = " -—–/,|+:;"
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _same_word(a: str, b: str) -> bool:
    """'thurble' is 'thurible' — a typo in a long word, never 'red' for 'rod'."""
    if a == b:
        return True
    return len(a) >= 5 and len(b) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.85


def _says(text: str, phrase: str) -> bool:
    """`phrase` already appears in `text` as whole words (any spacing/case)."""
    words = _words(phrase)
    if not words:
        return True
    pat = r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(re.escape(w) for w in words) + r"(?![a-z0-9])"
    return re.search(pat, (text or "").lower()) is not None


def _minus_product(name: str, pname: str) -> str:
    """The hub's variant name minus the product's name inside it: exact
    ("Navy Straight Collar Shirt" → "Navy"), a misspelt copy of the whole
    name ("INCENSE BURNER/THURBLE" for "Incense Burner / Thurible" → ""),
    or a leading run of its words ("Holy Communion Bread -500PCS…" for
    "Holy Communion Bread 1000 Pcs" → "-500PCS…")."""
    if not name or not pname:
        return name
    whole = re.compile(r"(?<![A-Za-z0-9])" + re.escape(pname) + r"(?![A-Za-z0-9])", re.IGNORECASE)
    if whole.search(name):
        return whole.sub("", name)
    nw, pw = _words(name), _words(pname)
    if not nw or not pw:
        return name
    if SequenceMatcher(None, "".join(nw), "".join(pw)).ratio() >= 0.9:
        return ""
    run = 0
    for a, b in zip(nw, pw):
        if not _same_word(a, b):
            break
        run += 1
    # at least two of its words and at least half of them: "Red Pleats" keeps
    # its "Red" under "Red Apostolic Cassock"
    if run >= 2 and run * 2 >= len(pw):
        spans = list(_WORD_RE.finditer(name))
        return name[spans[run].start():] if len(spans) > run else ""
    return name


def variant_label(product_name: str | None, v: dict | None) -> str:
    v = v or {}
    pname = " ".join(str(product_name or "").split())
    attrs = v.get("attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}
    name = " ".join(str(v.get("name") or "").split())
    # The hub's own variant name first — minus the product's name inside it
    # ("Navy Straight Collar Shirt" → "Navy"; "S / GOLD" stays, it carries the
    # colour the attributes may not) …
    tail = ""
    if name and name.lower() != pname.lower():
        tail = " ".join(_minus_product(name, pname).split()).strip(_EDGES)
    if tail and pname and tail.lower() == pname.lower():
        tail = ""
    # … then every attribute value those words do not already say: the size
    # under a colour the name carries ("Black Pleats…" + {Size: M}), or all of
    # them when the name says nothing ("Straight Collar" six times over, told
    # apart only by {Size: 8 inch}). A bare code rides with its key: "Size M".
    bits: list[str] = []
    for key, val in attrs.items():
        val = " ".join(str(val or "").split())
        if not val or _says(tail, val) or _says(pname, val) or any(_says(b, val) for b in bits):
            continue
        key = " ".join(str(key or "").split())
        if key and (len(val) <= 3 or val.isdigit()) and not _says(val, key):
            val = f"{key[:1].upper()}{key[1:]} {val}"
        bits.append(val)
    parts = ([tail] if tail else []) + bits
    tail = " / ".join(parts)
    if not tail or (pname and tail.lower() == pname.lower()):
        return pname or name
    return f"{pname} — {tail}" if pname else tail


def label_variants(items: list[dict]) -> None:
    """Stamp `label` on every variant of every product, in place."""
    for p in items or []:
        for v in (p.get("variants") or []):
            if isinstance(v, dict):
                v["label"] = variant_label(p.get("name"), v)
