"""Planned actions — Neema's initiative, with a veto window (plan B2).

Every follow-up Neema intends to take is a visible row FIRST: the operator can
veto or edit before it fires; sensitive ones wait for one-tap approval.
Executed by services/actions.py's leader-locked scheduler loop.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id         : Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    deal_id    : Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), nullable=True, index=True)
    conversation_id : Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    due_at     : Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # follow_up (Neema's own promise) | customer_promise (their stated timeline)
    # | quote_follow_up / buying_follow_up (they were about to buy) | check_in /
    # replenishment (a day they named) | fit_check (care) | payment_reminder
    kind       : Mapped[str] = mapped_column(String(30), default="follow_up")
    # The commitment's identity (audit, 2026-11-05): one OPEN row per
    # (conversation, dedupe_key), enforced by a partial unique index — a second
    # booking of the same matter updates the first instead of stacking. Keys:
    # buying:<deal>, promise:<deal>, customer_promise:<deal>,
    # check_in:purchase_decision|supplies|delivery, care:<order>, payment:<orders>.
    dedupe_key : Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    # Which planner filed it: scribe | tool | hub | cart_recovery | payment_followup | human
    source     : Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason     : Mapped[str | None] = mapped_column(Text, nullable=True)
    draft      : Mapped[str | None] = mapped_column(Text, nullable=True)
    # planned | needs_approval | sent | vetoed | failed
    status     : Mapped[str] = mapped_column(String(20), default="planned", index=True)
    created_by : Mapped[str] = mapped_column(String(10), default="ai")
    created_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
