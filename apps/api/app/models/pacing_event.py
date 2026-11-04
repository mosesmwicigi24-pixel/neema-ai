import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class PacingEvent(Base):
    """What the conversation budget and the bot shield WOULD do for one
    contact (agent/conversation_budget), once per decision per day.

    Record-only first (owner, 2026-11-04): the owner marks each right or
    wrong in Reports → Pacing before anything reaches a customer.
    decision: shorten | pause | alert | repeat_price | bot | move_to_dm | spam."""
    __tablename__ = "pacing_events"

    id              : Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at      : Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    channel         : Mapped[str]              = mapped_column(String(20), default="whatsapp")
    contact         : Mapped[str]              = mapped_column(String(128))
    conversation_id : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    decision        : Mapped[str]              = mapped_column(String(16), index=True)
    reasons         : Mapped[list | None]      = mapped_column(JSONB, nullable=True)
    turns           : Mapped[int | None]       = mapped_column(Integer, nullable=True)
    progress        : Mapped[int | None]       = mapped_column(Integer, nullable=True)
    budget          : Mapped[int | None]       = mapped_column(Integer, nullable=True)
    bot_score       : Mapped[int | None]       = mapped_column(Integer, nullable=True)
    mode            : Mapped[str]              = mapped_column(String(8), default="shadow")
    owner_mark      : Mapped[str | None]       = mapped_column(String(8), nullable=True)
    owner_note      : Mapped[str | None]       = mapped_column(Text, nullable=True)
    marked_by       : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    marked_at       : Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
