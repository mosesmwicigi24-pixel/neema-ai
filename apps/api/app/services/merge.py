"""Real, reversible person-level merge.

Today's `merge_customers` was cosmetic — it copied scalar fields and stashed a
`merged_ids` list, re-pointing nothing. This makes a merge *real*: the merge unit
is the `person`, and merging moves the secondary's **identities** (the source of
truth) onto the primary, then refreshes the denormalized `person_id` cache on the
wa_id-keyed tables to match. Every move is written to `person_merges` so it can
be undone exactly.

Precision over recall (docs/MULTICHANNEL_IDENTITY_PLAN.md): this is only ever
invoked by an operator's explicit confirm or a deterministic key — never an
automatic weak-signal merge.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.person import Person, Identity, PersonMerge
from app.models.user import User
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.order_event import OrderEvent
from app.models.customer_history import CustomerHistory

# The wa_id-keyed tables whose person_id is a denormalized cache of
# identity.person_id (World A / whatsapp today).
_WA_MODELS = [User, Conversation, Message, OrderEvent, CustomerHistory]


async def merge_persons(
    db: AsyncSession,
    primary_person_id: uuid.UUID,
    secondary_person_id: uuid.UUID,
    *,
    performed_by: uuid.UUID | None = None,
    primary_wa_id: str | None = None,
    secondary_wa_id: str | None = None,
) -> PersonMerge:
    """Move every identity on `secondary` onto `primary`, refresh the
    denormalized person_id cache for the moved wa_ids, tombstone the secondary
    person, and write a reversible audit row (returned). Caller owns the commit.
    """
    if primary_person_id == secondary_person_id:
        raise ValueError("cannot merge a person into itself")

    idents = (await db.execute(
        select(Identity).where(Identity.person_id == secondary_person_id)
    )).scalars().all()
    moved_identity_ids = [str(i.id) for i in idents]
    # Only whatsapp external_ids index the denormalized wa_id tables today.
    moved_external_ids = [i.external_id for i in idents if i.channel == "whatsapp"]

    # 1. Move the identities (the source of truth).
    for i in idents:
        i.person_id = primary_person_id

    # 2. Refresh the denormalized person_id cache for those wa_ids.
    if moved_external_ids:
        for model in _WA_MODELS:
            await db.execute(
                update(model)
                .where(model.wa_id.in_(moved_external_ids))
                .values(person_id=primary_person_id)
            )

    # 3. Tombstone the secondary person (kept, never deleted → reversible).
    secondary = await db.get(Person, secondary_person_id)
    if secondary is not None:
        secondary.merged_into_id = primary_person_id
        secondary.merged_at = datetime.now(timezone.utc)

    # 4. Audit.
    audit = PersonMerge(
        primary_person_id=primary_person_id,
        secondary_person_id=secondary_person_id,
        moved_identity_ids=moved_identity_ids,
        moved_external_ids=moved_external_ids,
        primary_wa_id=primary_wa_id,
        secondary_wa_id=secondary_wa_id,
        performed_by=performed_by,
    )
    db.add(audit)
    await db.flush()
    return audit


async def unmerge(
    db: AsyncSession,
    audit: PersonMerge,
    *,
    undone_by: uuid.UUID | None = None,
) -> None:
    """Reverse a `person_merges` row exactly: move the recorded identities back
    to the secondary person, restore the denormalized cache for those wa_ids,
    clear the secondary's tombstone, and stamp the audit undone. Caller commits.
    """
    if audit.undone_at is not None:
        raise ValueError("this merge has already been undone")

    ident_ids = [uuid.UUID(x) for x in (audit.moved_identity_ids or [])]
    if ident_ids:
        await db.execute(
            update(Identity)
            .where(Identity.id.in_(ident_ids))
            .values(person_id=audit.secondary_person_id)
        )

    if audit.moved_external_ids:
        for model in _WA_MODELS:
            await db.execute(
                update(model)
                .where(model.wa_id.in_(audit.moved_external_ids))
                .values(person_id=audit.secondary_person_id)
            )

    secondary = await db.get(Person, audit.secondary_person_id)
    if secondary is not None:
        secondary.merged_into_id = None
        secondary.merged_at = None

    audit.undone_at = datetime.now(timezone.utc)
    audit.undone_by = undone_by
    await db.flush()


async def latest_active_merge(
    db: AsyncSession,
    primary_wa_id: str,
    secondary_wa_id: str,
) -> PersonMerge | None:
    """The most recent not-yet-undone merge of `secondary_wa_id` into
    `primary_wa_id`, or None."""
    return (await db.execute(
        select(PersonMerge)
        .where(
            PersonMerge.primary_wa_id == primary_wa_id,
            PersonMerge.secondary_wa_id == secondary_wa_id,
            PersonMerge.undone_at.is_(None),
        )
        .order_by(PersonMerge.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
