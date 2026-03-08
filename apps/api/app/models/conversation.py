import uuid
from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, Enum as PgEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models import Base
import enum

class InterceptMode(str, enum.Enum):
    ai     = "ai"
    human  = "human"
    paused = "paused"

class ConvStatus(str, enum.Enum):
    open   = "open"
    closed = "closed"

class Conversation(Base):
    __tablename__ = "conversations"

    id                  : Mapped[uuid.UUID]      = mapped_column(primary_key=True, default=uuid.uuid4)
    wa_id               : Mapped[str]            = mapped_column(String(30), nullable=False, unique=True, index=True)
    intercept_mode      : Mapped[InterceptMode]  = mapped_column(PgEnum(InterceptMode), default=InterceptMode.ai)
    assigned_agent_id   : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    intercept_since     : Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at     : Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_preview: Mapped[str | None]      = mapped_column(Text, nullable=True)
    status              : Mapped[ConvStatus]      = mapped_column(PgEnum(ConvStatus), default=ConvStatus.open)
    created_at          : Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at          : Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id])
    messages       = relationship("Message", back_populates="conversation")
    intercepts     = relationship("Intercept", back_populates="conversation")