import uuid
from datetime import datetime
from sqlalchemy import String, Text, BigInteger, ForeignKey, Enum as PgEnum, DateTime
from sqlalchemy.dialects.postgresql import JSONB
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

def _external_id_from_wa_id(context):
    """Default external_id to wa_id so existing `Message(wa_id=…)` (WhatsApp)
    keeps working after the channel cutover; Messenger/IG messages pass it."""
    return context.get_current_parameters().get("wa_id")


class Message(Base):
    __tablename__ = "messages"

    id              : Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    name            : Mapped[str | None]       = mapped_column(String(100), nullable=True)
    # WhatsApp handle — populated for WhatsApp (shim); NULL for Messenger/IG.
    wa_id           : Mapped[str | None]       = mapped_column(String(30), nullable=True, index=True)
    channel         : Mapped[str]              = mapped_column(String(20), nullable=False, server_default="whatsapp")
    # Channel-native handle (wa_id | PSID | IGSID) == the conversation's external_id.
    external_id     : Mapped[str | None]       = mapped_column(String(128), nullable=True, index=True, default=_external_id_from_wa_id)
    person_id       : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True)
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
    # For Facebook/Instagram comment messages: the source-post context so an
    # agent (and the AI) can see WHAT the comment is replying to. Shape:
    #   {"post_id", "title", "permalink", "thumb"} — any field may be missing.
    # NULL for every non-comment message. Kept as one JSONB blob so new context
    # fields (ad id, parent comment, …) never need another migration.
    comment_context : Mapped[dict | None]      = mapped_column(JSONB, nullable=True)
    # Reply-to (quote): when this message is a reply to an earlier one, the source
    # message id + a cached snippet of its text + who sent it, so the thread renders
    # the quoted bubble without a join. On WhatsApp the reply is also delivered
    # natively (Cloud API context.message_id, resolved from the source's waba_msg_id).
    reply_to_id     : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    reply_to_text   : Mapped[str | None]       = mapped_column(Text, nullable=True)
    reply_to_sender : Mapped[str | None]       = mapped_column(String(20), nullable=True)
    created_at      : Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    conversation = relationship("Conversation", back_populates="messages")