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
        # Enrich in place on a return visit. The inbox reads Person.display_name
        # and the avatar reads Identity.raw_profile.profile_pic, so a late name /
        # photo (e.g. the Meta Profile API only started answering once the app was
        # approved) must land on BOTH — otherwise the contact stays "Unknown"
        # forever despite the identity now knowing its name.
        if display_name and not ident.display_name:
            ident.display_name = display_name[:200]
        new_pic = (raw_profile or {}).get("profile_pic")
        if new_pic and (ident.raw_profile or {}).get("profile_pic") != new_pic:
            ident.raw_profile = {**(ident.raw_profile or {}), "profile_pic": new_pic}
        if display_name:
            person = await db.get(Person, ident.person_id)
            if person is not None and not person.display_name:
                person.display_name = display_name[:200]
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
    person/identity on first sight. Returns None for an empty wa_id — or for an
    id that cannot be a phone (a 16-17 digit Meta PSID/IGSID leaked into a
    WhatsApp path): minting a (whatsapp, <meta-id>) identity here is what created
    the phantom "WhatsApp" contacts in the CRM, so for a non-phone we only ADOPT
    an existing identity's person (any channel), never create."""
    from app.core.phone import is_plausible_phone

    wa_id = (wa_id or "").lstrip("+").strip()
    if not wa_id:
        return None
    if not is_plausible_phone(wa_id):
        existing = (await db.execute(
            select(Identity).where(Identity.external_id == wa_id)
            .order_by(Identity.created_at)
        )).scalars().first()
        return existing.person_id if existing is not None else None
    ident = await resolve_or_create_person(
        db, WHATSAPP, wa_id,
        display_name=display_name, source=source, confidence="deterministic",
    )
    return ident.person_id


# ── Cross-channel bridge: WhatsApp arrival via a social deep link ────────────
import json  # noqa: E402
import re    # noqa: E402

# Matches the ref minted by whatsapp_checkout_link (6 hex chars), e.g. "(ref 9F2A7C)".
_WAREF_RE = re.compile(r"\bref[:#\s]*([0-9A-Fa-f]{6})\b", re.IGNORECASE)


async def reconcile_waref(db: AsyncSession, redis, wa_id: str, text: str) -> bool:
    """When a WhatsApp buyer arrives via a wa.me deep link we generated inside
    their Messenger/IG DM, its `ref` token ties them back to that social contact.
    Clicking our unique link is a strong, self-asserted signal, so we MERGE the two
    persons (phone-anchored WhatsApp person stays primary) and stamp the source for
    attribution. One-shot — the ref is consumed. Best-effort; never raises. Returns
    True if a link was made."""
    if not text or redis is None:
        return False
    m = _WAREF_RE.search(text)
    if not m:
        return False
    key = f"waref:{m.group(1).upper()}"
    try:
        raw = await redis.get(key)
    except Exception:
        return False
    if not raw:
        return False

    async def _consume():
        try:
            await redis.delete(key)
        except Exception:
            pass

    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    channel, ext = data.get("channel"), str(data.get("external_id") or "")
    if not channel or not ext:
        await _consume()
        return False

    social = await _select_identity(db, channel, ext)
    wa_person_id = await resolve_person_id_for_wa_id(db, wa_id)
    if social is None or wa_person_id is None or social.person_id == wa_person_id:
        await _consume()                       # nothing to link (or already same person)
        return False

    # Stamp the attribution source on the WhatsApp person, then merge the social
    # person into it (reversible; identities move onto the phone-anchored person).
    wa_person = await db.get(Person, wa_person_id)
    if wa_person is not None:
        state = dict(wa_person.state or {})
        state.setdefault("lead_source", channel)
        src = (social.raw_profile or {}).get("source_post")
        if src:
            state["source_post"] = src
        wa_person.state = state

    from app.services.merge import merge_persons
    try:
        await merge_persons(db, primary_person_id=wa_person_id,
                            secondary_person_id=social.person_id,
                            primary_wa_id=(wa_id or "").lstrip("+"))
        await db.commit()
    except Exception:
        await db.rollback()
        return False
    await _consume()
    return True
