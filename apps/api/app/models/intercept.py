import uuid
from datetime import datetime
from sqlalchemy import Text, ForeignKey, Enum as PgEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models import Base
import enum

class InterceptAction(str, enum.Enum):
    intercept     = "intercept"
    release       = "release"
    transfer      = "transfer"
    approve_draft = "approve_draft"

class Intercept(Base):
    __tablename__ = "intercepts"

    id               : Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id  : Mapped[uuid.UUID]        = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id         : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    action           : Mapped[InterceptAction]  = mapped_column(PgEnum(InterceptAction), nullable=False)
    ai_reply_held    : Mapped[str | None]       = mapped_column(Text, nullable=True)
    agent_reply_sent : Mapped[str | None]       = mapped_column(Text, nullable=True)
    note             : Mapped[str | None]       = mapped_column(Text, nullable=True)
    created_at       : Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="intercepts")