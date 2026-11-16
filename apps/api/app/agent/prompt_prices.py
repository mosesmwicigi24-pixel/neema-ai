"""THE PRICES IN NEEMA'S INSTRUCTIONS COME FROM THE HUB (owner, 2026-11-16:
"every aspect of this app should get its first-hand information, the truth
from the hub").

The instructions teach by example — "Our Cassock Set is $210, everything
included". Those figures were typed by hand, and six of them had drifted from
the hub by 2026-11-16 (the Cassock Set is $195; the 200-piece wafers KES 400,
not 500; the glass cups KES 100, not 20; the mitre $55; the skull cap $15; the
Ornate Chasuble KES 14,000). An example that disagrees with the catalogue
teaches the wrong number.

So each product price in the instructions is listed here with the hub product
it belongs to, and is replaced with the hub's own figure when the
instructions are built. `agent/prompt.py` is not edited: with no catalogue in
hand the text is exactly as written, and a price the hub does not carry stays
as written. A test (tests/test_prompt_prices.py) fails if a money figure
appears in the instructions that is neither listed here nor named in ALLOWED
as "not a product price".

USD is the house rule: the hub's KES price over `usd_kes_rate`.
"""
from __future__ import annotations

import logging
import re

_log = logging.getLogger("neema.prompt_prices")

# (the sentence fragment as written, [(figure as written, hub slug or slugs, currency, times)])
# A tuple of slugs is their SUM. Whitespace in a fragment matches any run of
# whitespace (the instructions wrap lines).
ROWS: list[tuple[str, list[tuple[str, object, str, float]]]] = [
    ("Eliad Oil at $50", [("$50", "eliad-anointing-oil", "USD", 1)]),
    ("$50 to $45", [("$50", "eliad-anointing-oil", "USD", 1), ("$45", "eliad-anointing-oil", "USD", 0.9)]),
    ("The Round Collar Shirt is ZMW 900", [("ZMW 900", "round-collar-shirt", "ZMW", 1)]),
    ("is ZMW 900. Kindly place your order", [("ZMW 900", "round-collar-shirt", "ZMW", 1)]),
    ("The Silver Communion Tray is KES 18,000", [("KES 18,000", "silver-communion-tray", "KES", 1)]),
    ("That's our Cassock Set — 4,200.", [("4,200", "cassock-set", "BARE", 1)]),
    ("plastic communion cups are KES 10 each and the glass ones KES 20",
     [("KES 10", "plastic-cups", "KES", 1), ("KES 20", "glass-cups", "KES", 1)]),
    ("200pcs at KES 500, or 500pcs at KES 1,000",
     [("KES 500", "communion-wafer-bread-200pcs", "KES", 1),
      ("KES 1,000", "communion-wafer-bread-500pcs", "KES", 1)]),
    ("Our Cassock Set is $210", [("$210", "cassock-set", "USD", 1)]),
    ("$100: the Mitre at $60, the Cincture Rope at $20 and the Skull Cap at $20",
     [("$100", ("mitre", "cincture-rope", "skull-cap"), "USD", 1), ("$60", "mitre", "USD", 1),
      ("$20", "cincture-rope", "USD", 1), ("$20", "skull-cap", "USD", 1)]),
    ("\"the Cassock is $130\"", [("$130", "cassock", "USD", 1)]),
    ("takes $130 for the set", [("$130", "cassock", "USD", 1)]),
    ("$130; the complete set with the stole, belt, shirt and collar is $210",
     [("$130", "cassock", "USD", 1), ("$210", "cassock-set", "USD", 1)]),
    ("$210, everything included\"; \"the cassock alone is $130\"",
     [("$210", "cassock-set", "USD", 1), ("$130", "cassock", "USD", 1)]),
    ("\"$180 with its 40 cups included\"", [("$180", "silver-communion-tray", "USD", 1)]),
    ("gold piping — is KES 13,000", [("KES 13,000", "ornate-chasuble", "KES", 1)]),
    ("The Aluminium Tray is KES 7,000, and the plastic cups are KES 10 each",
     [("KES 7,000", "aluminium-tray", "KES", 1), ("KES 10", "plastic-cups", "KES", 1)]),
    ("Silver Communion Tray at $180", [("$180", "silver-communion-tray", "USD", 1)]),
    ("(\"KES 10 each\")", [("KES 10", "plastic-cups", "KES", 1)]),
    ("The Wooden Tray goes for $50 and the Aluminium Tray for $70; the Silver Communion Tray is $180 "
     "and the Golden Communion Tray $220; then the Aluminium 4-Stack Communion Set at $280",
     [("$50", "wooden-tray", "USD", 1), ("$70", "aluminium-tray", "USD", 1),
      ("$180", "silver-communion-tray", "USD", 1), ("$220", "golden-communion-tray", "USD", 1),
      ("$280", "aluminium-double-stacked-communion-set", "USD", 1)]),
    ("the large gold Thurible is KES 15,000", [("KES 15,000", "incense-burner", "KES", 1)]),
    ("Our cassock is KES 13,000", [("KES 13,000", "cassock", "KES", 1)]),
    ("That's KES 13,000, and we make it to your measurements", [("KES 13,000", "cassock", "KES", 1)]),
    ("Golden Communion Tray — KES 22,000", [("KES 22,000", "golden-communion-tray", "KES", 1)]),
    ("1 Gold Bread Tray, $140", [("$140", "gold-bread-tray", "USD", 1)]),
    ("is $180. How many do you need?", [("$180", "silver-communion-tray", "USD", 1)]),
    ("6 trays, $1,080", [("$1,080", "silver-communion-tray", "USD", 6)]),
    ("The aluminium tray is $70.", [("$70", "aluminium-tray", "USD", 1)]),
    ("(with its 40 cups included) is $70.", [("$70", "aluminium-tray", "USD", 1)]),
    ("- Aluminium Tray – $70", [("$70", "aluminium-tray", "USD", 1)]),
    ("- Silver Communion Tray – $180", [("$180", "silver-communion-tray", "USD", 1)]),
    ("- Golden Communion Tray – $220", [("$220", "golden-communion-tray", "USD", 1)]),
    ("2 Silver Trays, $360 total", [("$360", "silver-communion-tray", "USD", 2)]),
    ("Silver Communion Tray ni KES 18,000", [("KES 18,000", "silver-communion-tray", "KES", 1)]),
]

# Money figures in the instructions that are NOT a product's price: a rule
# about how to write money, a story, a fee the owner set. Each with why.
ALLOWED: list[tuple[str, str]] = [
    ("KES 2,500 to our", "a customer's M-Pesa story"),
    ("mostly KES 350 within Kenya", "the delivery fee — Neema's own copy until the hub provides it"),
    ("\"KES 0\"", "how never to write a missing price"),
    ("\"KES 1,000 or 1,500\"", "how never to write two prices"),
    ("\"KES 1,000 au 1,500\"", "the same, in Swahili"),
    ("\"from $60 for the medium\"", "the shape of a 'from' price"),
    ("\"$10 each\"", "the shape of a per-piece price"),
    ("\"from $3.50 by size\"", "the shape of a 'from' price"),
    ("the 10-inch collar is $4", "a variant example"),
    ("from $3.50 by size — which size", "a variant example"),
    ("$3.50 and the 10-inch $4", "a variant example"),
    ("a 50-pack cost KES 10", "the mistake the rule exists for"),
    ("4.5 is $4.50, 12.75 is $12.75, 117.5 is $117.50", "how to write cents"),
    ("Say \"$170\", never \"$170 USD\"; \"KES 12,000\", never \"KES 12,000", "how to write a currency"),
    ("that is $250, not $25,000", "how to own a mistake"),
    ("read across 2,668 of their replies", "a count, not money"),
    ("KES 1,200\")", "a colleague's correction, as an example"),
]

MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|(?:KES|ZMW|USD)\s?\d[\d,]*(?:\.\d+)?|\b\d{1,3},\d{3}\b")

_PRICES: dict = {"by_slug": {}, "mark": None}


def _rx(fragment: str) -> re.Pattern:
    return re.compile(r"\s+".join(re.escape(w) for w in fragment.split()))


def remember(catalog: list | None) -> None:
    """Note the hub's prices from a catalogue that was just read: slug → the
    row's KES price and its per-currency map. Recomputed only when the
    catalogue changed. Never raises."""
    try:
        if not catalog:
            return
        mark = (len(catalog), hash(tuple((p.get("slug"), p.get("price")) for p in catalog if isinstance(p, dict))))
        if mark == _PRICES["mark"]:
            return
        by: dict = {}
        for p in catalog:
            if isinstance(p, dict) and p.get("slug"):
                by[str(p["slug"])] = {"KES": p.get("price"), "prices": p.get("prices") or {}}
        if by:
            _PRICES.update(by_slug=by, mark=mark)
    except Exception as exc:
        _log.info("prompt prices not remembered: %s", exc)


def _amount(slug, ccy: str, usd_rate: float) -> float | None:
    slugs = slug if isinstance(slug, tuple) else (slug,)
    total = 0.0
    for s in slugs:
        row = _PRICES["by_slug"].get(s)
        if not row:
            return None
        try:
            kes = float(row.get("KES") or 0)
        except (TypeError, ValueError):
            return None
        if kes <= 0:
            return None
        if ccy in ("KES", "BARE"):
            total += kes
        elif ccy == "USD":
            total += kes / float(usd_rate or 100)
        else:
            try:
                own = float((row.get("prices") or {}).get(ccy) or 0)
            except (TypeError, ValueError):
                own = 0.0
            if own <= 0:
                return None
            total += own
    return total


def _show(v: float, ccy: str) -> str:
    whole = abs(v - round(v)) < 0.005
    num = f"{round(v):,}" if whole else f"{v:,.2f}"
    return {"USD": f"${num}", "BARE": num}.get(ccy, f"{ccy} {num}")


def fill(text: str, usd_rate: float = 100) -> str:
    """The instructions with every listed example price set to the hub's
    figure. A row whose product the hub does not carry is left as written —
    whole, so a sentence never mixes a fresh figure with a stale one."""
    if not text or not _PRICES["by_slug"]:
        return text
    for fragment, figures in ROWS:
        m = _rx(fragment).search(text)
        if not m:
            continue
        new = m.group(0)
        at = 0
        ok = True
        for literal, slug, ccy, times in figures:
            v = _amount(slug, ccy, usd_rate)
            i = new.find(literal, at)
            if v is None or i < 0:
                ok = False
                break
            shown = _show(v * times, ccy)
            new = new[:i] + shown + new[i + len(literal):]
            at = i + len(shown)
        if ok and new != m.group(0):
            text = text[:m.start()] + new + text[m.end():]
    return text


def unlisted(text: str) -> list[str]:
    """Money figures in the instructions that no ROW and no ALLOWED entry
    accounts for — a price somebody typed in. [] is the passing answer."""
    rest = text
    for fragment, _ in ROWS:
        rest = _rx(fragment).sub(" ", rest)
    for fragment, _ in ALLOWED:
        rest = _rx(fragment).sub(" ", rest)
    return [m.group(0) for m in MONEY_RE.finditer(rest)]


def status() -> dict:
    """For /api/health: how many example prices the hub is feeding."""
    fed = sum(1 for _, figs in ROWS if all(_amount(s, c, 100) is not None for _, s, c, _ in figs))
    return {"examples": len(ROWS), "from_hub": fed, "as_written": len(ROWS) - fed,
            "catalogue_seen": bool(_PRICES["by_slug"])}
