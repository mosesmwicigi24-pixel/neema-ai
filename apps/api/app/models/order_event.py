from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, Numeric, DateTime
from sqlalchemy.dialects.postgresql import JSONB, CHAR
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base

class OrderEvent(Base):
    __tablename__ = "order_events"

    id                 : Mapped[str]      = mapped_column(String(80), primary_key=True)  # {wa_id}_{epoch}
    wa_id              : Mapped[str]      = mapped_column(String(30), nullable=False, index=True)
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