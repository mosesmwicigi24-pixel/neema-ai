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
    {
        # Owner, 2026-09-21, describing the cassock outfit: "the shirt and the
        # collar, the cassock, the signature belt and the stole" — the belt
        # worn at the waist with a cassock is the hub's CINCTURE BELT.
        "hub": "cincture belt",
        "said": (
            r"signature\s+belts?",
            r"cassock\s+belts?",
        ),
    },
    {
        # Owner, 2026-09-25: "gold trays with holes to place tot glasses" is
        # a communion tray — the tray with the holes that hold the small
        # cups. The finish word stays in front of it ("gold communion tray").
        "hub": "communion tray",
        "said": (
            r"trays?\s+with\s+(?:the\s+)?holes(?:\s+(?:to|for|that|which)\s+"
            r"(?:place|hold|carry|put|fit|holds|placing|holding)?\s*(?:the\s+)?"
            r"(?:tot\s+|small\s+|little\s+|communion\s+)?(?:glasses|cups?))?",
            r"trays?\s+(?:to|that|which)\s+(?:hold|place|carry)s?\s+(?:the\s+)?"
            r"(?:tot\s+|small\s+|little\s+|communion\s+)?(?:glasses|cups?)",
            r"trays?\s+(?:for|of)\s+(?:the\s+)?(?:tot\s+|small\s+|little\s+)?(?:glasses|cups?)",
            r"(?:communion\s+)?cups?\s+trays?",
            r"trei\s+(?:ya|za)\s+vikombe",     # Swahili: tray of cups
        ),
    },
    {
        # Owner, 2026-09-25: "when someone asks for Holy Communion Cups
        # without specifying chalice, give the plastic, stainless and glass
        # cups, not chalice cups." Tot glasses, wine cups, the small cups —
        # all the hub's communion cups. (A misspaced "holycommunion" too.)
        "hub": "communion cups",
        "said": (
            # (not a compound: a "communion cup filler" is the Refiller, a
            # "communion cup tray" a tray — the tray family, above, ran first)
            r"(?:holy\s*)?communion\s+(?:tot\s+|small\s+|little\s+)?(?:glasses|cups?)"
            r"(?!\s+(?:re)?fillers?\b|\s+trays?\b|\s+holders?\b|\s+racks?\b|\s+sets?\b)",
            r"(?:small|little|tiny)\s+cups?\s+(?:for|of)\s+(?:the\s+)?(?:holy\s+)?"
            r"(?:communion|wine|lord'?s\s+supper|ushirika)",
            r"tots?\s+glasses",
            r"tots?\s+cups?",
            r"wine\s+cups?",
            r"vikombe\s+vya\s+ushirika",       # Swahili: communion cups
        ),
    },
    {
        # The owner's words for the metal cups: stainless, steel, metal —
        # the hub's Silver Communion Cups (the same rule that makes a
        # "stainless steel tray" the Silver Communion Tray).
        "hub": "silver communion cups",
        "said": (
            r"(?:stainless(?:\s+steel)?|steel|metal(?:lic)?)\s+(?:communion\s+)?cups?",
            r"silver\s+cups?",
        ),
    },
    {
        # "Kasoki 2 na saples" (Messenger, 2026-09-25): a surplice, as Kenyans
        # say and spell it — never a guess at something else.
        "hub": "surplice",
        "said": (
            r"surplic(?:e|es|ess)",
            r"surplis(?:e|es|i)?",
            r"saplic(?:e|es)",
            r"saplis(?:e|es|i)?",
            r"saple(?:s|ss)?",
            r"sapulis(?:i|e|es)?",
            r"sapuris(?:i|e)?",
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


# ── A KIND of thing, priced from the cheapest up (owner, 2026-09-16) ─────────
# "How much is that Holy Communion set?" is not one hub row — it is a RANGE,
# and the owner sells a range from the humblest piece upward: "We have our
# wooden tray or aluminium tray at KES 7,000 … the Silver Communion Tray at
# KES 18,000 … the Golden Communion Tray at $220 … then the Aluminium 4-Stack
# set, then the Double Stacked Silver set." People say "I need the cheapest"
# and then climb. The live miss: three dear sets and a chalice, dearest last,
# nothing under $280. Each range says which hub rows belong to it (by the
# hub's own names), which neighbours do NOT (a chalice is a chalice), and the
# words that mean ONE member rather than the range ("silver tray" is a row).
RANGES: tuple[dict, ...] = (
    {
        "name": "communion trays and sets",
        # The customer's words for the range itself (whole words, plurals).
        "asked": (
            r"(?:holy\s+)?communion\s+(?:tray|set|service)s?",
            r"(?:tray|set)s?\s+(?:for|of)\s+(?:the\s+)?(?:holy\s+)?communion",
            r"(?:holy\s+)?communion\s+(?:tray\s+)?sets?",
            r"meza\s+ya\s+bwana",          # Swahili: the Lord's table
            r"ushirika\s+mtakatifu",        # Swahili: holy communion
            r"trei\s+(?:ya|za)\s+ushirika",
        ),
        # A hub row is IN the range when its name says so …
        "include": r"communion\s+(?:tray|set)|tray\s+set|stack(?:ed)?\b.*\b(?:communion|tray|set)|^\s*(?:wooden|aluminium|aluminum)\s+tray\s*$",
        # … and OUT when it is a neighbour sold on its own: cups, wafers,
        # bread, wine, hosts and every chalice. ("160 Cups" inside a SET's
        # name is the set's capacity, not a cup row — the include wins there.)
        "exclude": r"chalice|paten|wafer|bread|wine|\bhosts?\b|^\s*(?:silver|plastic|pre-?packed)\s+communion\s+cups",
        # Words that pick ONE member, so the ordinary search answers instead.
        "specific": r"\b(?:silver|gold(?:en)?|aluminium|aluminum|wooden|wood|stack(?:ed|able)?|double|four|4)\b",
        "stay": ("these are the trays and sets only; chalices, cups, wafers, bread "
                 "and wine are other things — mention one only if THEY ask for it"),
    },
    {
        # Owner, 2026-09-25: "Holy Communion Cups" without the word chalice
        # are the SMALL cups the tray holds — plastic, silver (stainless),
        # glass, pre-packed — cheapest first, and never a chalice.
        "name": "communion cups",
        "asked": (
            r"(?:holy\s*)?communion\s+cups?",
            r"cups?\s+(?:for|of)\s+(?:the\s+)?(?:holy\s+)?communion",
            r"vikombe\s+vya\s+ushirika",
        ),
        "include": r"^\s*(?:silver|plastic|pre-?packed|glass)\s+(?:communion\s+)?cups\s*$",
        "exclude": r"chalice|paten|tray|set|stack",
        "specific": r"\b(?:silver|plastic|glass|pre-?packed|prepacked|sealed|stainless|steel|metal)\b",
        "stay": ("these are the small communion cups only — the cups a tray holds; a "
                 "chalice, a tray and a set are other things — mention one only if "
                 "THEY ask for it (a chalice only when they SAY chalice)"),
    },
)

_RANGE_ASKED = tuple(
    (re.compile(r"\b(?:" + "|".join(r["asked"]) + r")\b", re.IGNORECASE), r)
    for r in RANGES
)


def range_for(query: str | None) -> dict | None:
    """The RANGE a customer's words ask about, or None when they name one
    member (or nothing in the table).

    "how much is that holy communion set"  -> the trays-and-sets range
    "communion trays"                       -> the range
    "silver communion tray"                 -> None (one hub row: search it)
    "chalice"                               -> None
    """
    text = query or ""
    for pattern, rng in _RANGE_ASKED:
        if pattern.search(text) and not re.search(rng["specific"], text, re.IGNORECASE):
            return rng
    return None


def range_members(rng: dict, catalog: list[dict]) -> list[dict]:
    """The hub rows in this range, CHEAPEST FIRST by the hub's KES price
    (unpriced rows last, in catalogue order) — the order the owner sells in."""
    inc = re.compile(rng["include"], re.IGNORECASE)
    exc = re.compile(rng["exclude"], re.IGNORECASE)
    rows = []
    for p in catalog:
        name = (p.get("name") or "")
        if inc.search(name) and not exc.search(name):
            rows.append(p)

    def _price(p: dict) -> tuple[int, float]:
        try:
            v = float(p.get("price") or 0)
        except (TypeError, ValueError):
            v = 0.0
        return (0, v) if v > 0 else (1, 0.0)

    return sorted(rows, key=_price)
