import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base


class RecoverySend(Base):
    """One message a daily recovery sweep actually sent (cart_recovery,
    payment_followup, reengage) — so the Reports page can say how many
    customers answered and ordered afterwards (services/recovery_results.py).
    `ref` is what it was about: the cart's fingerprint, or the hub order ids."""
    __tablename__ = "recovery_sends"
    __table_args__ = (Index("ix_recovery_sends_job_sent_at", "job", "sent_at"),)

    id              : Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job             : Mapped[str] = mapped_column(String(32))
    conversation_id : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    person_id       : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True)
    channel         : Mapped[str] = mapped_column(String(20), default="whatsapp")
    ref             : Mapped[str | None] = mapped_column(String(200), nullable=True)
    sent_at         : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
