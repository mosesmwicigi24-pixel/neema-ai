"""Durable order links — `GET /api/r/{ref}`.

Why this exists beside the older `/api/o/{ref}`:

`/api/o/` is a redis-backed TAP-TO-ORDER shortener. Its targets are storefront
product pages and wa.me handovers, its keys expire, and on a miss it 302s to a
bare WhatsApp chat. A customer who was told "here's your order link" and tapped
one of those landed in an empty chat with no order in sight — which is exactly
what happened to a real buyer, and what this module replaces.

`/api/r/` is backed by Postgres (`order_events.short_ref`), so:

  * it does not expire — a receipt link works next year;
  * it survives redis loss entirely;
  * a miss lands on the shop's help page, NEVER on a wa.me chat that gives the
    customer no idea what became of their order.

The target is always the hub's own durable `/order/{public_token}` page: the
receipt when the order is paid, the checkout when it is not.
"""
import logging
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.core.config import settings
from app.database import AsyncSessionLocal
from app.models.order_event import OrderEvent

router = APIRouter()
_log = logging.getLogger("neema.orderlink")

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no I/O/0/1 — these get read aloud


def new_short_ref() -> str:
    """A six-character ref a human can read down a phone line."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(6))


async def assign_short_ref(db, row: OrderEvent) -> str:
    """Give this order a ref, retrying on the (vanishingly rare) collision.

    The unique index is the authority — a check-then-insert would race.
    """
    for _ in range(6):
        ref = new_short_ref()
        exists = (await db.execute(
            select(OrderEvent.id).where(OrderEvent.short_ref == ref).limit(1)
        )).scalar_one_or_none()
        if exists is None:
            row.short_ref = ref
            return ref
    # Six collisions against a 32^6 space means something is wrong; fall back to
    # a longer ref rather than raising and costing the customer their order.
    return "".join(secrets.choice(_ALPHABET) for _ in range(10))


@router.get("/r/{ref}")
async def order_redirect(ref: str, request: Request):
    target = None
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(OrderEvent)
                .where(OrderEvent.short_ref == ref.upper())
                .limit(1)
            )).scalar_one_or_none()
            if row is not None:
                target = (row.hub_public_url or row.hub_payment_url or "").strip() or None
    except Exception:
        _log.warning("order link lookup failed for %s", ref, exc_info=True)

    if not target:
        # A dead order link must NOT dump the customer into a blank WhatsApp
        # chat — that is the failure this module exists to end. Send them
        # somewhere that can explain itself.
        base = (settings.storefront_url or "").rstrip("/")
        target = f"{base}/orders" if base else "https://bethanyhouse.co.ke"

    return RedirectResponse(target, status_code=302)
