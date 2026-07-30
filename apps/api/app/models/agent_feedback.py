"""Learning-loop rows (plan D): corrections + self-QA findings.

AgentFeedback — every time a human edits Neema's draft before sending, the
(draft, sent) pair is a lesson. QaFinding — the nightly self-review's catches
(re-asked questions, missed closes). Both feed the weekly distillation that
proposes rule changes for the owner to approve.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from app.models import Base


class AgentFeedback(Base):
    __tablename__ = "agent_feedback"

    id              : Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id : Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    draft           : Mapped[str] = mapped_column(Text)
    sent            : Mapped[str] = mapped_column(Text)
    created_at      : Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)


class QaFinding(Base):
    __tablename__ = "qa_findings"

    id              : Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id : Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    kind            : Mapped[str] = mapped_column(String(40), index=True)
    detail          : Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at      : Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)
