"""ONE name for a variant, everywhere (owner, 2026-09-25: "take the variant +
attribute to get the product name and size, and apply it to all variants").

The hub names a variant loosely — "Straight Collar" six times over, "S / GOLD",
"Navy Straight Collar Shirt" — and its attributes ({Size: 8 inch}, {Colour:
Navy}) carry what tells it apart. The label every seam shows is

    <product name> — <what tells it apart>

"Straight Collar — 8 inch", "Straight Collar Shirt — Navy", "Thurible — S /
GOLD". The agent's search rows, the public catalogue, the cart line and the
verifier all read the same label, so a customer who says "the 10 inch" and
the order that follows name the same thing.
"""
from __future__ import annotations

import re


def variant_label(product_name: str | None, v: dict | None) -> str:
    v = v or {}
    pname = " ".join(str(product_name or "").split())
    attrs = v.get("attributes") or {}
    values = ([" ".join(str(x).split()) for x in attrs.values() if str(x).strip()]
              if isinstance(attrs, dict) else [])
    name = " ".join(str(v.get("name") or "").split())
    # The hub's own variant name first — minus the product's name inside it
    # ("Navy Straight Collar Shirt" → "Navy"; "S / GOLD" stays, it carries the
    # colour the attributes may not) — then the attributes ("Straight Collar"
    # six times over, told apart only by {Size: 8 inch}).
    tail = ""
    if name and name.lower() != pname.lower():
        tail = name
        if pname and pname.lower() in name.lower():
            tail = re.sub(re.escape(pname), "", name, flags=re.IGNORECASE)
        tail = " ".join(tail.split()).strip(" -—–/,|")
    if not tail:
        tail = " / ".join(values)
    if not tail or (pname and tail.lower() == pname.lower()):
        return pname or name
    return f"{pname} — {tail}" if pname else tail


def label_variants(items: list[dict]) -> None:
    """Stamp `label` on every variant of every product, in place."""
    for p in items or []:
        for v in (p.get("variants") or []):
            if isinstance(v, dict):
                v["label"] = variant_label(p.get("name"), v)
