"""THE ORDER, AS A RECORD THE MODEL CANNOT QUIETLY REWRITE (owner, 2026-11-15
— the Melchizkek thread).

A customer asked for three garments for two people, each chosen from a photo.
The order ended as two standard sets: one garment was dropped and the style
was swapped, and nothing in the system objected. Found in the code:

  * a cart line was a product and a number — nowhere to keep WHO it is for,
    WHICH photo it is, what colour, or that it is "as pictured";
  * the cart was shown to the model only when it asked (`get_cart`), so each
    turn rebuilt the order from the chat;
  * `remove` and `clear` ran on the model's say-so;
  * an item with no hub price had nowhere to live, so the nearest priced
    product took its place.

This module is the pure part of the fix (agent/tools.py calls it):

  * `clean_units`   — the per-piece facts a line may carry;
  * `clean_pending` — an item the customer wants that has NO hub price: it is
                      kept on the order as "awaiting a colleague's price" and
                      handed to a person; it is never replaced by a product;
  * `quote_found`   — a removal must QUOTE the words that asked for it, and
                      the quote must be in the record (the customer's own
                      messages, or a human colleague's);
  * `sheet_note`    — the order so far, put in front of the model every turn;
  * `for_order`     — the same facts, written onto the order for the workshop.

Prices never come from here: every figure is the hub's (tools._cart_display).
"""
from __future__ import annotations

import re
import unicodedata

UNIT_KEYS = ("for", "colour", "photo", "note")
MAX_UNITS = 12
MAX_PENDING = 8
_MAX_LEN = 120
MIN_QUOTE = 4                 # characters, once normalised: "no", "ok" justify nothing


def _s(v, limit: int = _MAX_LEN) -> str:
    return " ".join(str(v or "").split())[:limit]


def _clean_one(d) -> dict:
    if not isinstance(d, dict):
        return {}
    out = {k: _s(d.get(k)) for k in UNIT_KEYS if _s(d.get(k))}
    # "color" is the same field, however the model spells it
    if "colour" not in out and _s(d.get("color")):
        out["colour"] = _s(d.get("color"))
    if d.get("as_pictured") in (True, "true", "True", 1, "yes"):
        out["as_pictured"] = True
    status = _s(d.get("status")).lower()
    if out or status:
        out["status"] = "confirmed" if status == "confirmed" else "tentative"
    return out


def clean_units(details) -> list[dict]:
    """The per-piece facts for one cart line: who each piece is for, its
    colour, the photo it was chosen from, whether it is to be made as
    pictured, and whether the customer has CONFIRMED it or only raised it."""
    if isinstance(details, dict):
        details = [details]
    if not isinstance(details, list):
        return []
    out = [u for u in (_clean_one(d) for d in details[:MAX_UNITS]) if u]
    return out


def clean_pending(description, details=None) -> dict | None:
    """An item with no hub price, kept on the order until a person prices it."""
    desc = _s(description, 160)
    if not desc:
        return None
    row = {"description": desc}
    row.update({k: v for k, v in _clean_one(details if isinstance(details, dict) else
                                            (details or [{}])[0] if isinstance(details, list) and details
                                            else {}).items() if k != "status"})
    return row


def pending_of(cart: dict | None) -> list[dict]:
    p = (cart or {}).get("pending")
    return [x for x in p if isinstance(x, dict) and x.get("description")] if isinstance(p, list) else []


def _norm(text) -> str:
    t = unicodedata.normalize("NFKC", str(text or "")).casefold()
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def quote_found(quote, said: list[str] | tuple[str, ...]) -> bool:
    """Is `quote` really in the record? Compared without case, punctuation or
    spacing differences. A quote too short to mean anything is not one."""
    q = _norm(quote)
    if len(q) < MIN_QUOTE:
        return False
    return any(q in _norm(s) for s in (said or ()) if s)


def unit_words(u: dict) -> str:
    bits = []
    if u.get("for"):
        bits.append(f"for {u['for']}")
    if u.get("colour"):
        bits.append(u["colour"])
    if u.get("photo"):
        bits.append(("as in " if u.get("as_pictured") else "see ") + u["photo"])
    elif u.get("as_pictured"):
        bits.append("as pictured")
    if u.get("note"):
        bits.append(u["note"])
    words = " — ".join(bits)
    if u.get("status"):
        words += f" [{u['status']}]"
    return words


def pending_words(p: dict) -> str:
    return p["description"] + ("" if not unit_words(p) else f" ({unit_words(p)})")


def _money(v, currency: str) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return f"{currency} ?"
    return f"{currency} {f:,.0f}" if f == int(f) else f"{currency} {f:,.2f}"


def sheet_note(items: list, total, currency: str, pending: list[dict]) -> str:
    """The order so far, for the model, every turn — "" when there is none.
    `items` and `total` are tools._cart_display's (the hub's prices, in this
    customer's currency)."""
    if not items and not pending:
        return ""
    lines = ["(THE ORDER SO FAR — the system's own record. It changes ONLY through "
             "update_cart; what you write in a reply does not change it:"]
    for n, i in enumerate(items, 1):
        qty = int(i.get("qty") or 1)
        lines.append(f"  {n}. {i.get('name')} ×{qty} — {_money(i.get('unit_price'), currency)} each")
        units = [u for u in (i.get("units") or []) if isinstance(u, dict)]
        for u in units:
            lines.append(f"       • {unit_words(u)}")
        if units and len(units) != qty:
            lines.append(f"       ! {qty} on the line but {len(units)} described — "
                         "put this right with update_cart (set, with details)")
    if items:
        lines.append(f"  Total of the priced lines: {_money(total, currency)}")
    for p in pending:
        lines.append(f"  AWAITING A COLLEAGUE'S PRICE (not in the total, still part of the order): "
                     f"{pending_words(p)}")
    if pending:
        lines.append("While a piece awaits its price: do NOT offer to start or place the order, and "
                     "never give the total as the whole order.")
    lines.append("A correction changes only the piece it names — every other piece above stands. "
                 "Count the pieces the customer asked for against this record before you "
                 "quote a total or offer to place the order.)")
    return "\n\n" + "\n".join(lines)


def for_order(cart: dict | None) -> str:
    """The per-piece facts as one line for the order note — what the workshop
    must not have to rediscover from the chat."""
    bits = []
    for i in (cart or {}).get("items") or []:
        units = [unit_words(u) for u in (i.get("units") or []) if isinstance(u, dict)]
        units = [u for u in units if u]
        if units:
            bits.append(f"{i.get('name')}: " + " | ".join(units))
    return "; ".join(bits)
