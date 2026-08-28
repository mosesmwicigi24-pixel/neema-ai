import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, Numeric, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, CHAR
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base

class OrderEvent(Base):
    __tablename__ = "order_events"

    id                 : Mapped[str]      = mapped_column(String(80), primary_key=True)  # {wa_id}_{epoch}
    wa_id              : Mapped[str]      = mapped_column(String(30), nullable=False, index=True)
    # Identity spine (additive): the human this order rolls up to. Backfilled 1:1
    # from wa_id. `channel` already exists below (default whatsapp).
    person_id          : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id         : Mapped[str | None] = mapped_column(String(80), nullable=True)
    event_type         : Mapped[str | None] = mapped_column(String(40), nullable=True)
    items              : Mapped[list]     = mapped_column(JSONB, default=list)
    subtotal           : Mapped[Decimal]  = mapped_column(Numeric(12, 2), default=0)
    currency           : Mapped[str]      = mapped_column(CHAR(3), default="KES")
    status             : Mapped[str]      = mapped_column(String(20), default="open")
    payment_status     : Mapped[str]      = mapped_column(String(20), default="unpaid")
    fulfillment_status : Mapped[str]      = mapped_column(String(20), default="pending")
    reply_text         : Mapped[str | None] = mapped_column(Text, nullable=True)
    channel            : Mapped[str]      = mapped_column(String(20), default="whatsapp")
    state              : Mapped[dict]     = mapped_column(JSONB, default=dict)
    created_at         : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at         : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Bethany House hub linkage (Part B push / Loop C relay) ──────────────
    # Set when a confirmed order-event is pushed into the hub as a pending order.
    hub_order_id       : Mapped[int | None] = mapped_column(Integer, nullable=True)
    hub_order_number   : Mapped[str | None] = mapped_column(String(40), nullable=True)
    # None = never attempted; "pushed" | "failed" | "skipped_dup" | "skipped_nomatch"
    hub_push_status    : Mapped[str | None] = mapped_column(String(20), nullable=True)
    hub_payment_url    : Mapped[str | None] = mapped_column(Text, nullable=True)
    hub_currency       : Mapped[str | None] = mapped_column(String(3), nullable=True)
    hub_total          : Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    hub_last_error     : Mapped[str | None] = mapped_column(Text, nullable=True)
    hub_pushed_at      : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── The customer's DURABLE order link ──────────────────────────────────
    # hub_payment_url above is a 72-hour pay session; every one Neema ever sent
    # is expired. hub_public_url is the hub's /order/{public_token}: the receipt
    # when paid, the checkout when not, and it does not expire. short_ref backs
    # our own /api/r/{ref} shortener so the chat shows a clean link.
    hub_public_url     : Mapped[str | None] = mapped_column(Text, nullable=True)
    hub_public_token   : Mapped[str | None] = mapped_column(String(64), nullable=True)
    short_ref          : Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)

    # ── Mirrored hub state ─────────────────────────────────────────────────
    # What the HUB says about this order. Kept apart from `status` above, which
    # is the operator's own triage flag set by hand in the Orders modal —
    # clobbering it would throw away human work. The Orders screen reads hub
    # truth when the order is linked and the local flag otherwise.
    hub_status             : Mapped[str | None] = mapped_column(String(24), nullable=True)
    hub_payment_status     : Mapped[str | None] = mapped_column(String(24), nullable=True)
    hub_fulfillment_status : Mapped[str | None] = mapped_column(String(24), nullable=True)
    hub_status_at          : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)