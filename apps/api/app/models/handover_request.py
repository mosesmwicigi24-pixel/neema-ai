import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class HandoverRequest(Base):
    """One person asking the colleague who holds a chat to hand it over
    (owner, 2026-11-04: "a button that can request the other person who is
    holding that chat to release it to this person. If that is granted on the
    other end, then that will be transferred to this new person").

    status: pending | accepted | declined. A pending request older than
    HANDOVER_TTL (services/handover.py) reads as expired; one open per chat."""
    __tablename__ = "handover_requests"

    id              : Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id : Mapped[uuid.UUID]        = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    from_agent_id   : Mapped[uuid.UUID]        = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    holder_agent_id : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    status          : Mapped[str]              = mapped_column(String(12), default="pending", index=True)
    created_at      : Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    answered_at     : Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    answered_by     : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
