"""Money is quoted as the hub holds it.

One rule, applied at every seam a price crosses on its way to a customer —
the agent's tool results, the product cards, the quotation, a comment reply,
the public catalogue, an order total in a follow-up: the figure is the hub's
figure. Nothing here rounds a price to a whole unit, a tidy number or a ten
(owner rule, 2026-09-03: "give the price as it is in the hub").

Two things that are NOT rounding a price the hub set:
  · money has no sub-cent — a DERIVED figure (KES ÷ rate) is kept to the
    cent, and a positive amount never collapses to 0 (a KES 0.40 item is
    $0.01, not free);
  · a whole amount comes back as an int, so 130.0 reads "130", not "130.0".
"""
from __future__ import annotations


def exact(v, *, floor_cent: bool = False):
    """The amount as a number: an int when whole, otherwise to the cent.
    None for nothing or nonsense. Never rounds to a unit or a ten —
    4.5 stays 4.5, 12.75 stays 12.75, 117.5 stays 117.5."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:                                   # NaN
        return None
    r = round(f, 2)
    if floor_cent and f > 0 and r < 0.01:
        r = 0.01
    return int(r) if r == int(r) else r


def num(v) -> str:
    """'1,250' · '12.50' · '0.30' — decimals only when the amount has them."""
    x = exact(v)
    if x is None:
        return ""
    return f"{x:,}" if isinstance(x, int) else f"{x:,.2f}"


def fmt(v, currency: str) -> str:
    """'KES 4,000' · '$40' · '$4.50' · 'ZMW 1,260' — the figure, untouched."""
    s = num(v)
    if not s:
        return ""
    cur = (currency or "").upper()
    if cur == "USD":
        return f"${s}"
    return f"{cur} {s}" if cur else s
