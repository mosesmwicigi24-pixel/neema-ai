"""Payment → person reconciliation — the load-bearing deterministic bridge.

"Let identity precipitate out of money" (docs/MULTICHANNEL_IDENTITY_PLAN.md,
lever 2). When the hub captures an M-Pesa payment it knows the **payer MSISDN +
name**. A phone is the person in World A, so that payment binds a (possibly
no-phone social) lead into the phone-anchored world *deterministically* — the
only signal precise enough to auto-link across identity worlds.

`reconcile_payment` resolves the payer to a person:
  1. exact country-safe E.164 match to an existing WhatsApp identity → same human;
  2. else an existing `phone` identifier → that person;
  3. else a new phone-only person.
If both a WhatsApp person AND a separate phone-only person already exist for the
same number, they are the same human by a deterministic key, so they are merged
(Tier 1 auto-link, WhatsApp kept as primary). The payer phone (+ optional M-Pesa
ref / order number) is recorded as an `identifier`, and any matching local
order_event is stamped with the resolved person.

This is the neema *receiver*; the hub (bethany-house `feat/customer-country-e164`)
is the sender. Contract: POST the payer MSISDN + name (+ ref/order ids) here.
"""
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.phone import to_e164
from app.models.person import Person, Identity, Identifier
from app.models.order_event import OrderEvent
from app.services.merge import merge_persons


async def attach_identifier(
    db: AsyncSession,
    person_id: uuid.UUID,
    type_: str,
    value: str,
    *,
    source: str | None = None,
    confidence: str | None = None,
    raw: dict | None = None,
) -> Identifier:
    """Idempotently attach a (type, value) token to a person. If the token
    already exists it is returned unchanged — we never silently move a token to
    a different person (that would be a cross-person claim, resolved by merge,
    not here). SAVEPOINT-guarded against the unique race."""
    value = (value or "").strip()
    if not value:
        raise ValueError("identifier value is required")

    existing = (await db.execute(
        select(Identifier).where(Identifier.type == type_, Identifier.value == value)
    )).scalar_one_or_none()
    if existing is not None:
        return existing

    try:
        async with db.begin_nested():
            idf = Identifier(
                person_id=person_id, type=type_, value=value,
                source=source, confidence=confidence, raw=raw or {},
            )
            db.add(idf)
            await db.flush()
        return idf
    except IntegrityError:
        existing = (await db.execute(
            select(Identifier).where(Identifier.type == type_, Identifier.value == value)
        )).scalar_one_or_none()
        if existing is None:
            raise
        return existing


async def reconcile_payment(
    db: AsyncSession,
    *,
    payer_msisdn: str,
    payer_name: str | None = None,
    mpesa_ref: str | None = None,
    hub_order_id: int | None = None,
    order_number: str | None = None,
    region: str = "KE",
) -> dict:
    """Resolve an M-Pesa payer to a person (creating/linking deterministically),
    record the phone (+ ref/order) identifiers, and stamp the matching local
    order_event. Caller owns the commit. Returns a result dict describing the
    match — never raises on an unresolvable number, so a payment webhook can't be
    broken by a malformed MSISDN."""
    e164 = to_e164(payer_msisdn, region)
    if not e164:
        return {"resolved": False, "reason": "unparseable_msisdn", "msisdn": payer_msisdn}
    wa_key = e164.lstrip("+")   # WhatsApp identities store E.164 without the '+'

    wa_ident = (await db.execute(
        select(Identity).where(Identity.channel == "whatsapp", Identity.external_id == wa_key)
    )).scalar_one_or_none()
    phone_idf = (await db.execute(
        select(Identifier).where(Identifier.type == "phone", Identifier.value == e164)
    )).scalar_one_or_none()

    wa_person = wa_ident.person_id if wa_ident else None
    ph_person = phone_idf.person_id if phone_idf else None

    if wa_person and ph_person and wa_person != ph_person:
        # Same number under two persons → deterministically the same human.
        # Tier-1 auto-link: merge the phone-only person into the WhatsApp one.
        await merge_persons(
            db, wa_person, ph_person,
            performed_by=None, primary_wa_id=wa_key, secondary_wa_id=None,
        )
        person_id, matched_via = wa_person, "phone_merge"
    elif wa_person:
        person_id, matched_via = wa_person, "whatsapp_phone"
    elif ph_person:
        person_id, matched_via = ph_person, "phone_identifier"
    else:
        person = Person(display_name=(payer_name or None))
        db.add(person)
        await db.flush()
        person_id, matched_via = person.id, "new_person"

    # Record the payer phone (+ optional portable tokens) on the resolved person.
    await attach_identifier(
        db, person_id, "phone", e164,
        source="mpesa_payment", confidence="deterministic",
        raw={"name": payer_name} if payer_name else None,
    )
    if mpesa_ref:
        await attach_identifier(db, person_id, "mpesa_ref", mpesa_ref,
                                source="mpesa_payment", confidence="deterministic")
    if order_number:
        await attach_identifier(db, person_id, "order_number", order_number,
                                source="mpesa_payment", confidence="deterministic")

    # Capture the payer name if the person has none yet.
    if payer_name:
        person = await db.get(Person, person_id)
        if person is not None and not person.display_name:
            person.display_name = payer_name[:200]

    # Stamp the matching local order_event(s) with the resolved person.
    order_events_stamped = 0
    if hub_order_id is not None:
        res = await db.execute(
            update(OrderEvent).where(OrderEvent.hub_order_id == hub_order_id)
            .values(person_id=person_id)
        )
        order_events_stamped = res.rowcount or 0

    await db.flush()
    return {
        "resolved": True,
        "person_id": str(person_id),
        "matched_via": matched_via,
        "e164": e164,
        "order_events_stamped": order_events_stamped,
    }
