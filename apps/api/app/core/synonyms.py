"""The customer's words for a product the hub names differently.

The hub's own names and aliases are the intelligence for nearly every item.
This is the short, owner-declared list of everyday words that are ONE item in
the hub — applied at every seam that turns a customer's words into a hub row
(the catalogue search, the product-card matcher, the order-line resolver, the
post-caption ladders and the live-comment vocabulary), so a person asking for
a "cross and chain" or a "pendant" is guided straight to the Pectoral Cross
instead of being told we will check. The same rule that has always made a
"stainless steel tray" the Silver Communion Tray, now held in one table.

Owner, 2026-09-06: "Cross and chain, Pendant, Pectoral Cross, Pastors /
Bishops cross are all the same item. When someone enquires, you should guide
the person to the product which is in the hub."

`canonical(text)` rewrites the customer's phrases to the hub's term and leaves
everything else untouched; the seams call it on their input and match as they
always did.
"""
from __future__ import annotations

import re

# One family per hub product: the term the hub uses, then the customer's words
# for it as regular expressions (whole words; possessives, plurals and the odd
# misspelling allowed). Longer phrases first inside each family so "cross and
# chain" is read as one phrase before "chain" could be considered on its own —
# a bare "chain" is NOT a cross (the thurible swings on one).
FAMILIES: tuple[dict, ...] = (
    {
        "hub": "pectoral cross",
        "said": (
            r"cross(?:es)?\s*(?:and|&|\+|with|na|on)\s*(?:a\s+|the\s+)?chains?",
            r"chains?\s*(?:and|&|\+|with)?\s*cross(?:es)?",
            r"cross(?:es)?\s+pendants?",
            r"pendants?\s+cross(?:es)?",
            r"neck\s+cross(?:es)?",
            r"clergy\s+cross(?:es)?",
            r"pastors?['’]?s?\s+cross(?:es)?",
            r"bishops?['’]?s?\s+cross(?:es)?",
            r"cross(?:es)?\s+for\s+(?:a\s+|the\s+)?(?:pastors?|bishops?|clergy)",
            r"pendants?",
            r"pedants?",                 # how "pendant" arrives on a phone keyboard
        ),
    },
)

_COMPILED: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(r"\b(?:" + "|".join(f["said"]) + r")\b", re.IGNORECASE), f["hub"])
    for f in FAMILIES
)


def canonical(text: str | None) -> str:
    """The text with every owner-declared synonym rewritten to the hub's term.

    "Do you have cross and chain?"  -> "Do you have pectoral cross?"
    "How much is the pendant?"      -> "How much is the pectoral cross?"
    "Incense burner with chain"     -> unchanged (a chain alone is no cross)
    """
    out = text or ""
    for pattern, hub in _COMPILED:
        out = pattern.sub(hub, out)
    return out


def hub_terms() -> tuple[str, ...]:
    """The hub terms the table guides to — for tests that keep the prompt honest."""
    return tuple(f["hub"] for f in FAMILIES)
