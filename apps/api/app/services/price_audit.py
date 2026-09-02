"""Does the hub's international price agree with its Kenyan one?

2026-09-02: a Messenger customer was told a pack of 50 communion cups was $10,
then "KES 10". Both numbers were read faithfully from the hub — and both were
wrong. Checking every product turned up 39 of 95 whose USD row did not match
their KES row: a hand-set dollar column with a $10 floor rounded to tens (a
KES 10 cup at $10, a KES 400 collar at $10, a KES 36,000 tray set at $600 where
360 was right), and three pack goods priced per single piece.

Nobody noticed for weeks because nothing looked. This looks.

It does NOT change a price — it cannot know the true one. It names the rows
where the two currencies disagree, and the rows where a per-piece figure is
masquerading as a product price, so a person can fix the hub and Neema stops
quoting the wrong number. Reported in the daily self-check and on the Catalog
screen; read by the per-piece guard in the catalogue search.
"""
from __future__ import annotations

import re

# A USD row is "consistent" when it is within this of KES / rate. Tolerance is
# generous on purpose: the rate is a round 100 and prices are rounded to whole
# units, so a shilling or two of drift is noise, not a finding.
TOLERANCE_PCT = 0.15
TOLERANCE_ABS = 1.0            # in the display currency (USD)

# Goods that are sold by the pack but that the hub may price by the piece.
PACK_GOODS = re.compile(r"\b(cups?|hosts?|wafers?|bread)\b", re.IGNORECASE)
# A name that already states its quantity is priced per pack: "Cups (250 pcs)",
# "Communion Hosts — 1,000 pieces", "Aluminium 4-Stack … 160 Cups".
STATES_QUANTITY = re.compile(r"\d[\d,]*\s*(?:pcs|pieces|pack|cups|hosts|wafers)\b",
                             re.IGNORECASE)
PER_PIECE_MAX_KES = 50         # no PACK of communion goods costs this little


def _num(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def looks_per_piece(item: dict) -> bool:
    """A pack good priced like a single piece, with no quantity in its name.

    KES 10 for "Plastic Communion Cups" is the per-cup price; KES 2,500 for
    "Disposable Communion Cups (250 pcs)" is a pack, and says so.
    """
    name = str(item.get("name") or "")
    hay = f"{name} {item.get('category') or ''} {item.get('description') or ''}"
    if not PACK_GOODS.search(hay):
        return False
    if STATES_QUANTITY.search(name):
        return False
    kes = _num(item.get("price_kes", item.get("price")))
    return kes is not None and kes <= PER_PIECE_MAX_KES


def currency_gap(item: dict, rate: float) -> dict | None:
    """The hub's own USD row against KES / rate — None when they agree, or
    when the hub carries no USD row (then the converter derives it, which is
    consistent by construction)."""
    kes = _num(item.get("price_kes", item.get("price")))
    usd = _num((item.get("prices") or {}).get("USD", item.get("price_usd")))
    if kes is None or usd is None or not rate:
        return None
    expect = kes / rate
    if abs(usd - expect) <= max(TOLERANCE_ABS, TOLERANCE_PCT * expect):
        return None
    return {"name": item.get("name"), "category": item.get("category"),
            "kes": kes, "usd": usd, "usd_expected": round(expect, 2),
            "factor": round(usd / expect, 2) if expect else None}


def audit(catalog: list[dict], rate: float) -> dict:
    """Every finding, grouped — the shape both the self-check and the Catalog
    screen read. Variants are checked like products: a size L with its own
    wrong dollar row is a wrong quote waiting to happen."""
    gaps, per_piece = [], []
    for p in catalog or []:
        g = currency_gap(p, rate)
        if g:
            gaps.append(g)
        if looks_per_piece(p):
            per_piece.append({"name": p.get("name"), "category": p.get("category"),
                              "kes": _num(p.get("price_kes", p.get("price")))})
        for v in p.get("variants") or []:
            vg = currency_gap({"name": f"{p.get('name')} — {v.get('name') or v.get('sku')}",
                               "category": p.get("category"),
                               "price_kes": v.get("price_kes"),
                               "prices": v.get("prices"), "price_usd": v.get("price_usd")},
                              rate)
            if vg:
                gaps.append(vg)
    gaps.sort(key=lambda g: -abs(g["usd"] - g["usd_expected"]))
    return {"currency_gaps": gaps, "per_piece": per_piece,
            "checked": len(catalog or []), "rate": rate}


def summary_line(report: dict) -> str:
    """One line for the standup — '' when the catalogue is clean."""
    n_gap, n_pp = len(report.get("currency_gaps") or []), len(report.get("per_piece") or [])
    if not n_gap and not n_pp:
        return ""
    parts = []
    if n_gap:
        worst = report["currency_gaps"][0]
        parts.append(f"{n_gap} product(s) whose hub USD price disagrees with "
                     f"KES/{int(report.get('rate') or 100)} (worst: {worst['name']} "
                     f"KES {worst['kes']:g} → ${worst['usd']:g}, expected ${worst['usd_expected']:g})")
    if n_pp:
        names = ", ".join(x["name"] for x in report["per_piece"][:3])
        parts.append(f"{n_pp} pack good(s) priced per single piece ({names})")
    return "PRICES — " + "; ".join(parts) + ". Fix the hub rows; Neema quotes what it holds."
