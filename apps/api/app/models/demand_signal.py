import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class DemandSignal(Base):
    """Something a customer wanted that we could not sell them.

    Every day people ask Neema for things — and when the catalogue has no answer,
    that request currently vanishes into the chat. It is the most valuable
    unlogged data in the business: real, specific, paid-for-by-nobody demand, in
    the customer's own words. Aggregated it answers "what should we stock or make
    next?" with evidence instead of instinct.

    kind:
      no_match         — searched the catalogue and found nothing
      out_of_catalogue — asked for something we don't carry (agent escalated)
      sourcing_gap     — we sold it, but the hub couldn't cover the quantity
    """
    __tablename__ = "demand_signals"

    id         : Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at : Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    # Normalised for grouping (lowercased, collapsed whitespace) + what they actually said.
    query      : Mapped[str]              = mapped_column(String(200), index=True)
    raw_query  : Mapped[str | None]       = mapped_column(Text, nullable=True)
    kind       : Mapped[str]              = mapped_column(String(20), default="no_match", index=True)
    channel    : Mapped[str | None]       = mapped_column(String(20), nullable=True)
    # WHO asked — so we can count distinct people, not just repeat requests, and
    # tell them once we stock it.
    person_id  : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True)
    wa_id      : Mapped[str | None]       = mapped_column(String(64), nullable=True, index=True)
    detail     : Mapped[str | None]       = mapped_column(Text, nullable=True)
