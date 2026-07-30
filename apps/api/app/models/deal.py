"""The Deal — Neema OWNS an outcome, visibly (docs/AGENTIC_PARTNER_PLAN.md, B1).

One open deal per conversation: what's being bought, what's settled, what's
blocking, whose move is next, and when Neema plans to act. Updated by the
post-turn scribe (services/deals.py) — the seller sells, the scribe files.
The operator edits everything from the board; `guidance` is injected into
Neema's prompt for THIS deal only.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PgUUID, JSONB

from app.models import Base


class Deal(Base):
    __tablename__ = "deals"

    id              : Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    person_id       : Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True)
    conversation_id : Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    title           : Mapped[str | None] = mapped_column(String(300), nullable=True)
    # [{"name": ..., "qty": ..., "price": ...}] — mirrors the live cart.
    items_snapshot  : Mapped[list] = mapped_column(JSONB, default=list)
    # new | qualified | proposal | won | lost — mirrors the lead pipeline.
    stage           : Mapped[str] = mapped_column(String(30), default="new", index=True)
    blocking        : Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"kind": "follow_up", "due_at": iso, "owner": "ai"|"human", "note": ...}
    next_action     : Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Operator-set, injected into the prompt for THIS deal ("no discount here").
    guidance        : Mapped[str | None] = mapped_column(Text, nullable=True)
    status          : Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at      : Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at      : Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
