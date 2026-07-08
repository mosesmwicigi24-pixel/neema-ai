import uuid
from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, Enum as PgEnum, DateTime, UniqueConstraint
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


def _external_id_from_wa_id(context):
    """Default external_id to wa_id — so every existing `Conversation(wa_id=…)`
    (the WhatsApp path) keeps working unchanged after the channel cutover. New
    non-WhatsApp rows pass external_id explicitly, so this isn't invoked for them."""
    return context.get_current_parameters().get("wa_id")

class Conversation(Base):
    __tablename__ = "conversations"
    # One conversation per channel handle. For WhatsApp external_id == wa_id, so
    # UNIQUE(channel, external_id) preserves the old one-conv-per-wa_id guarantee
    # while extending it to Messenger (PSID) / Instagram (IGSID).
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_conversation_channel_external_id"),
    )

    id                  : Mapped[uuid.UUID]      = mapped_column(primary_key=True, default=uuid.uuid4)
    # WhatsApp handle — kept populated for WhatsApp (the compat shim: existing
    # wa_id lookups still work). NULL for non-phone channels (Messenger/IG).
    wa_id               : Mapped[str | None]     = mapped_column(String(30), nullable=True, index=True)
    channel             : Mapped[str]            = mapped_column(String(20), nullable=False, server_default="whatsapp")
    # The channel-native handle: wa_id | Messenger PSID | Instagram IGSID. The
    # real key now (with channel). == wa_id for WhatsApp.
    external_id         : Mapped[str]            = mapped_column(String(128), nullable=False, default=_external_id_from_wa_id)
    person_id           : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True)
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