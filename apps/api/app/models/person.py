import uuid
from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models import Base


class Person(Base):
    """The human — the stable CRM unit that many channel identities roll up to.

    A `person` is deliberately thin: it exists so that a WhatsApp contact, a
    Messenger PSID and an Instagram IGSID that are *the same human* can be
    linked without collapsing their per-channel history. Orders, tags, lead
    stage, agent memory attach to the person (directly, or roll up from its
    identities). See docs/MULTICHANNEL_IDENTITY_PLAN.md.

    Today Neema is WhatsApp-only, so on backfill every `wa_id` becomes exactly
    one person + one `(whatsapp, wa_id)` identity — a 1:1 mapping that changes
    nothing until a second identity is linked (real merge) or a second channel
    is ingested.
    """
    __tablename__ = "persons"

    id            : Mapped[uuid.UUID]   = mapped_column(primary_key=True, default=uuid.uuid4)
    display_name  : Mapped[str | None]  = mapped_column(String(200), nullable=True)
    # Free-form rollup state (reserved for person-level tags / lead_stage / memory
    # once the query layer moves off wa_id). Empty until then — additive, no reads yet.
    state         : Mapped[dict]        = mapped_column(JSONB, default=dict)

    # ── Reversible-merge tombstone ────────────────────────────────────────────
    # When this person is merged INTO another, merged_into_id points at the
    # survivor and merged_at records when. The row is never deleted, so a merge
    # is reversible by audit. Filled by the real merge (crm merge_customers);
    # NULL for every live person.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merged_at     : Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)

    created_at    : Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at    : Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    identities = relationship(
        "Identity", back_populates="person", foreign_keys="Identity.person_id"
    )


class Identity(Base):
    """One (channel, external_id) handle for a human — the natural key of a
    single messaging surface.

    Examples: (whatsapp, "254712345678"), (messenger, PSID), (instagram, IGSID).
    `UNIQUE(channel, external_id)` guarantees one identity row per handle; many
    identities point at one `person`. Linking two channels = attaching their
    identities to the same person (reversibly).
    """
    __tablename__ = "identities"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_identity_channel_external_id"),
        Index("ix_identities_person_id", "person_id"),
    )

    id          : Mapped[uuid.UUID]   = mapped_column(primary_key=True, default=uuid.uuid4)
    person_id   : Mapped[uuid.UUID]   = mapped_column(
        ForeignKey("persons.id", ondelete="RESTRICT"), nullable=False
    )
    channel     : Mapped[str]         = mapped_column(String(20), nullable=False)   # whatsapp | messenger | instagram | …
    external_id : Mapped[str]         = mapped_column(String(128), nullable=False)  # wa_id / PSID / IGSID
    display_name: Mapped[str | None]  = mapped_column(String(200), nullable=True)
    raw_profile : Mapped[dict]        = mapped_column(JSONB, default=dict)          # channel profile blob (pic, username…)

    # How/with what confidence this identity was bound to its person — the
    # reconciliation ladder from the plan. source: whatsapp_inbound | backfill |
    # manual_link | mpesa_payment | meta_id_match | ctwa. confidence: deterministic
    # | assisted | weak. Backfilled whatsapp identities are ("backfill",
    # "deterministic") — a phone IS the person in World A.
    source      : Mapped[str | None]  = mapped_column(String(40), nullable=True)
    confidence  : Mapped[str | None]  = mapped_column(String(20), nullable=True)

    created_at  : Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at  : Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    person = relationship("Person", back_populates="identities", foreign_keys=[person_id])


class Identifier(Base):
    """A portable identity token bound to a person — a phone/email the customer
    volunteered or we matched, an M-Pesa payer MSISDN, an order number quoted
    across channels. Distinct from `Identity` (a messaging surface): an
    identifier is a *claim* that helps bridge worlds. `UNIQUE(type, value)` →
    one token maps to one person. See docs/MULTICHANNEL_IDENTITY_PLAN.md.
    """
    __tablename__ = "identifiers"
    __table_args__ = (
        UniqueConstraint("type", "value", name="uq_identifier_type_value"),
        Index("ix_identifiers_person_id", "person_id"),
    )

    id         : Mapped[uuid.UUID]   = mapped_column(primary_key=True, default=uuid.uuid4)
    person_id  : Mapped[uuid.UUID]   = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), nullable=False)
    type       : Mapped[str]         = mapped_column(String(20), nullable=False)   # phone | email | mpesa_ref | order_number
    value      : Mapped[str]         = mapped_column(String(128), nullable=False)
    source     : Mapped[str | None]  = mapped_column(String(40), nullable=True)
    confidence : Mapped[str | None]  = mapped_column(String(20), nullable=True)
    raw        : Mapped[dict]        = mapped_column(JSONB, default=dict)
    created_at : Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at : Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class PersonMerge(Base):
    """Audit row for one real, reversible person-level merge.

    Written by app/services/merge.py when secondary's identities are moved onto
    primary. Holds exactly what unmerge needs to reverse the move: the moved
    identity ids and the external_ids (wa_ids) whose denormalized person_id cache
    was refreshed. `undone_at` is set when the merge is reversed.
    """
    __tablename__ = "person_merges"
    __table_args__ = (
        Index("ix_person_merges_primary_person_id", "primary_person_id"),
        Index("ix_person_merges_secondary_person_id", "secondary_person_id"),
    )

    id                  : Mapped[uuid.UUID]   = mapped_column(primary_key=True, default=uuid.uuid4)
    primary_person_id   : Mapped[uuid.UUID]   = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    secondary_person_id : Mapped[uuid.UUID]   = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    moved_identity_ids  : Mapped[list]        = mapped_column(JSONB, default=list)
    moved_identifier_ids: Mapped[list]        = mapped_column(JSONB, default=list)
    moved_external_ids  : Mapped[list]        = mapped_column(JSONB, default=list)
    primary_wa_id       : Mapped[str | None]  = mapped_column(String(30), nullable=True)
    secondary_wa_id     : Mapped[str | None]  = mapped_column(String(30), nullable=True)
    performed_by        : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    created_at          : Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    undone_at           : Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    undone_by           : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
