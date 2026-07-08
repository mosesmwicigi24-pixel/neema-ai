"""Identity resolution — the seam between a channel handle and the human.

`resolve_or_create_person` is the single find-or-create for an `(channel,
external_id)` identity and its backing `person`. Today the only channel is
`whatsapp` (external_id == wa_id), so this is a thin, deterministic mapping that
mirrors the backfill: one wa_id ⇒ one person ⇒ one `(whatsapp, wa_id)` identity.

It exists now (rather than when Messenger lands) so that every row created after
the spine migration is stamped with a `person_id` — the backfill covered history,
this covers the future. Nothing reads `person_id` for behaviour yet; keeping it
populated is what makes the later query-layer cutover safe.

Callers own the transaction (this only flushes). The create is guarded by a
SAVEPOINT so a rare concurrent insert that wins `UNIQUE(channel, external_id)`
never poisons the caller's transaction — we just adopt the winner.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.person import Person, Identity

WHATSAPP = "whatsapp"


async def _select_identity(db: AsyncSession, channel: str, external_id: str) -> Identity | None:
    return (await db.execute(
        select(Identity).where(
            Identity.channel == channel,
            Identity.external_id == external_id,
        )
    )).scalar_one_or_none()


async def resolve_or_create_person(
    db: AsyncSession,
    channel: str,
    external_id: str,
    *,
    display_name: str | None = None,
    raw_profile: dict | None = None,
    source: str | None = None,
    confidence: str | None = None,
) -> Identity:
    """Find-or-create the identity for `(channel, external_id)` and its person.

    Returns the `Identity` (with `.person_id` populated). Idempotent: a second
    call with the same handle returns the same identity/person. If the identity
    exists, an empty `display_name` is enriched from the passed one but the
    person link is never changed here (linking/merging is a separate, audited op).
    """
    external_id = (external_id or "").strip()
    if not external_id:
        raise ValueError("external_id is required to resolve an identity")

    ident = await _select_identity(db, channel, external_id)
    if ident is not None:
        if display_name and not ident.display_name:
            ident.display_name = display_name[:200]
        return ident

    try:
        async with db.begin_nested():          # SAVEPOINT — isolates the unique race
            person = Person(display_name=display_name[:200] if display_name else None)
            db.add(person)
            await db.flush()                    # assign person.id
            ident = Identity(
                person_id=person.id,
                channel=channel,
                external_id=external_id,
                display_name=display_name[:200] if display_name else None,
                raw_profile=raw_profile or {},
                source=source,
                confidence=confidence,
            )
            db.add(ident)
            await db.flush()                    # may raise IntegrityError on the unique
        return ident
    except IntegrityError:
        # A concurrent caller created the same identity first; adopt it. The
        # SAVEPOINT rollback already discarded our orphan person + identity.
        ident = await _select_identity(db, channel, external_id)
        if ident is None:                       # not the unique we guarded against — re-raise
            raise
        return ident


async def resolve_person_id_for_wa_id(
    db: AsyncSession,
    wa_id: str,
    *,
    display_name: str | None = None,
    source: str = "whatsapp",
) -> "uuid.UUID | None":  # noqa: F821  (uuid only needed as a type hint)
    """Convenience: the person_id behind a WhatsApp wa_id, creating the
    person/identity on first sight. Returns None only for an empty wa_id."""
    wa_id = (wa_id or "").lstrip("+").strip()
    if not wa_id:
        return None
    ident = await resolve_or_create_person(
        db, WHATSAPP, wa_id,
        display_name=display_name, source=source, confidence="deterministic",
    )
    return ident.person_id
