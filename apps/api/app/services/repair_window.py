"""The repair and alteration window, read from the record (decision D5).

The rule: our own items, within 14 days of delivery, said plainly; a
colleague decides exceptions. Until now the writer had the rule and no date
to apply it to. The hub tells us when an order is delivered (the
`order.delivered` event): that moment is kept on the order
(`state["delivered_at"]`, set once), and this module turns it into a fact
the writer is handed when a customer raises a repair.

An order delivered before the date was kept has only the hub's last status
time. That time is on or after the delivery, so it proves "outside" when it
is itself more than 14 days old, and proves nothing otherwise — and nothing
is what the writer is then told.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

REPAIR_DAYS = 14

# Words that are about a repair whoever says them, and words that only are
# when the customer already has a delivered order ("too tight" is a sizing
# question before a sale and a fit complaint after one).
_STRONG_RE = re.compile(
    r"\b(?:repair\w*|alter(?:ation|ations|ed|ing)?|mend\w*|resiz\w*|re-?stitch\w*|"
    r"torn|ripped|came apart|take it in|let it out|"
    r"\w*rekebish\w*|shona tena|imechanika|imeraruka)\b", re.IGNORECASE)
_WEAK_RE = re.compile(
    r"\b(?:adjust\w*|seam|hem(?:ming|med)?|doesn'?t fit|does not fit|didn'?t fit|not fitting|"
    r"too (?:big|small|tight|loose|long|short|wide|narrow)|"
    r"haitoshi|hainitoshi|kubwa sana|ndogo sana)\b", re.IGNORECASE)

_DELIVERED = {"delivered", "completed", "fulfilled"}


def asks_about_repair(text: str | None) -> str:
    """"strong" (a repair whoever says it), "weak" (a repair only for someone
    holding a delivered order), or ""."""
    if _STRONG_RE.search(text or ""):
        return "strong"
    return "weak" if _WEAK_RE.search(text or "") else ""


def has_delivery(orders: list[dict]) -> bool:
    return any(o.get("window") in ("inside", "outside", "unknown") for o in orders or ())


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _parse(v) -> datetime | None:
    if isinstance(v, datetime):
        return _aware(v)
    try:
        return _aware(datetime.fromisoformat(str(v).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def reading(*, delivered_at=None, hub_status: str | None = None,
            hub_fulfillment: str | None = None, hub_status_at=None,
            now: datetime | None = None) -> dict:
    """What the record proves about one order: {"window": "inside" |
    "outside" | "unknown" | "not_delivered", "delivered_at", "days"}."""
    now = now or datetime.now(timezone.utc)
    d = _parse(delivered_at)
    if d is not None:
        days = max(0, (now - d).days)
        return {"window": "inside" if days <= REPAIR_DAYS else "outside",
                "delivered_at": d, "days": days, "exact": True}
    marks = {str(hub_status or "").lower(), str(hub_fulfillment or "").lower()}
    if marks & _DELIVERED:
        at = _parse(hub_status_at)
        if at is not None and (now - at).days > REPAIR_DAYS:
            # delivered on or before `at`, and `at` is already past the window
            return {"window": "outside", "delivered_at": None,
                    "days": (now - at).days, "exact": False}
        return {"window": "unknown", "delivered_at": None, "days": None, "exact": False}
    return {"window": "not_delivered", "delivered_at": None, "days": None, "exact": False}


def _item_names(items) -> str:
    names = []
    for it in items or []:
        if isinstance(it, dict):
            n = str(it.get("name") or it.get("product") or "").strip()
            if n and n not in names:
                names.append(n)
    return ", ".join(names[:3])


def note(orders: list[dict]) -> str:
    """The fact handed to the writer on a repair ask. `orders` = readings
    with "number" and "items". Says only what the record proves."""
    lines = []
    for o in orders[:3]:
        num = o.get("number") or "an order"
        what = f" ({o['items']})" if o.get("items") else ""
        w = o.get("window")
        if w == "inside":
            left = REPAIR_DAYS - int(o.get("days") or 0)
            lines.append(f"order {num}{what}: delivered {o['delivered_at']:%-d %b %Y}, "
                         f"{o['days']} day(s) ago — INSIDE the {REPAIR_DAYS}-day window "
                         f"({left} day(s) left)")
        elif w == "outside" and o.get("exact"):
            lines.append(f"order {num}{what}: delivered {o['delivered_at']:%-d %b %Y}, "
                         f"{o['days']} days ago — OUTSIDE the {REPAIR_DAYS}-day window")
        elif w == "outside":
            lines.append(f"order {num}{what}: delivered more than {o['days']} days ago — "
                         f"OUTSIDE the {REPAIR_DAYS}-day window")
        elif w == "unknown":
            lines.append(f"order {num}{what}: delivered, the date is not on our record")
        else:
            lines.append(f"order {num}{what}: not shown as delivered yet")
    if not lines:
        return ("\n\n(REPAIR OR ALTERATION — our record shows no order for this contact, which "
                "does not mean they have none (another number, an order placed in the shop). Do "
                "not say whether they are inside the 14-day window: ask for the order number or "
                "when they received it, and a colleague confirms.)")
    tail = ("Go by this, not by a guess. Inside the window: arrange it. Outside: say the "
            f"{REPAIR_DAYS}-day rule plainly, once — a colleague decides any exception, never "
            "promise one. Where the date is not on record, do not say whether they are inside "
            "the window: ask when they received it, and a colleague confirms. If the item is "
            "not one of these orders, ask which order it came from.")
    return ("\n\n(REPAIR OR ALTERATION — what our record shows for this contact:\n- "
            + "\n- ".join(lines) + "\n" + tail + ")")


async def for_contact(channel: str, key: str, *, now: datetime | None = None) -> list[dict]:
    """This contact's hub orders, newest first, each with its reading. Reads
    in its own session; returns [] on any failure."""
    try:
        from sqlalchemy import or_, select
        from app.database import AsyncSessionLocal
        from app.models.order_event import OrderEvent
        from app.models.user import User
        async with AsyncSessionLocal() as db:
            person_id = None
            if channel == "whatsapp":
                u = (await db.execute(select(User).where(User.wa_id == key))).scalar_one_or_none()
                person_id = u.person_id if u else None
            else:
                from app.models.person import Identity
                ident = (await db.execute(select(Identity).where(
                    Identity.channel == channel, Identity.external_id == key))).scalars().first()
                person_id = ident.person_id if ident else None
            conds = [OrderEvent.wa_id == key]
            if person_id is not None:
                conds.append(OrderEvent.person_id == person_id)
            rows = (await db.execute(
                select(OrderEvent).where(or_(*conds), OrderEvent.hub_order_id.isnot(None))
                .order_by(OrderEvent.created_at.desc()).limit(5))).scalars().all()
            out = []
            for r in rows:
                rd = reading(delivered_at=(r.state or {}).get("delivered_at"),
                             hub_status=r.hub_status, hub_fulfillment=r.hub_fulfillment_status,
                             hub_status_at=r.hub_status_at, now=now)
                rd.update({"number": r.hub_order_number, "items": _item_names(r.items)})
                out.append(rd)
            return out
    except Exception:
        return []


def worst(orders: list[dict]) -> str | None:
    """"outside" when every delivered order on record is outside the window
    (the only state the policy step acts on), else None."""
    known = [o for o in orders if o.get("window") in ("inside", "outside", "unknown")]
    if known and all(o["window"] == "outside" for o in known):
        return "outside"
    return None
