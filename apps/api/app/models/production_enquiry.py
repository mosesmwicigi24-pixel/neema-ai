import uuid
from datetime import datetime

from sqlalchemy import String, Text, BigInteger, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ProductionEnquiry(Base):
    """A customer's made-to-order request captured from the public measurement
    form. It starts as an ENQUIRY (status='new') flagged in the staff inbox; a
    colleague reviews it and, with one tap, pushes it into the hub as a real
    production order (status='pushed', hub_order_id set) — the point where money
    and a real order come into being. Kept as its own row (not just an inbox
    message) so the push is structured + idempotent and the order is trackable.
    """
    __tablename__ = "production_enquiries"

    id               : Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at       : Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    product_slug     : Mapped[str | None]       = mapped_column(String(200), nullable=True)
    product_name     : Mapped[str | None]       = mapped_column(String(200), nullable=True)
    hub_product_id   : Mapped[int | None]       = mapped_column(BigInteger, nullable=True)
    customer_name    : Mapped[str | None]       = mapped_column(String(200), nullable=True)
    phone            : Mapped[str | None]       = mapped_column(String(30), nullable=True, index=True)
    country_iso      : Mapped[str | None]       = mapped_column(String(5), nullable=True)
    measurements     : Mapped[dict]             = mapped_column(JSONB, default=dict)
    notes            : Mapped[str | None]       = mapped_column(Text, nullable=True)
    location         : Mapped[str | None]       = mapped_column(String(200), nullable=True)
    conversation_id  : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    person_id        : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True)
    # new → pushed (a hub production order exists) → declined
    status           : Mapped[str]              = mapped_column(String(20), default="new", index=True)
    hub_order_id     : Mapped[int | None]       = mapped_column(BigInteger, nullable=True)
    hub_order_number : Mapped[str | None]       = mapped_column(String(50), nullable=True)
