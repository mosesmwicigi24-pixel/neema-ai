import uuid
from datetime import datetime
from sqlalchemy import String, Text, BigInteger, ForeignKey, Enum as PgEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models import Base
import enum

class MsgDirection(str, enum.Enum):
    inbound  = "inbound"
    outbound = "outbound"

class MsgSender(str, enum.Enum):
    user         = "user"
    ai           = "ai"
    human_agent  = "human_agent"

class Message(Base):
    __tablename__ = "messages"

    id              : Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    name            : Mapped[str | None]       = mapped_column(String(100), nullable=True)
    wa_id           : Mapped[str]              = mapped_column(String(30), nullable=False, index=True)
    conversation_id : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True)
    direction       : Mapped[MsgDirection]     = mapped_column(PgEnum(MsgDirection), nullable=False)
    sender          : Mapped[MsgSender]        = mapped_column(PgEnum(MsgSender), default=MsgSender.user)
    text            : Mapped[str | None]       = mapped_column(Text, nullable=True)
    waba_msg_id     : Mapped[str | None]       = mapped_column(String(100), nullable=True)
    agent_id        : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    ts_ms           : Mapped[int | None]       = mapped_column(BigInteger, nullable=True)
    media_id        : Mapped[str | None]       = mapped_column(String(200), nullable=True)
    media_type      : Mapped[str | None]       = mapped_column(String(20), nullable=True)
    media_url       : Mapped[str | None]       = mapped_column(Text, nullable=True)
    media_caption   : Mapped[str | None]       = mapped_column(Text,        nullable=True)
    mime_type       : Mapped[str | None]       = mapped_column(String(100), nullable=True)
    filename       : Mapped[str | None]        = mapped_column(String(200), nullable=True)
    created_at      : Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    conversation = relationship("Conversation", back_populates="messages")