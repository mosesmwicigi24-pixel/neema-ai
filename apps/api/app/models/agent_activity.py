"""One row per thing Neema DID in a turn — the visible half of her work.

The reply a customer receives is the tip: beneath it the agent searched the
catalogue, showed cards and albums, changed the cart, created the order,
saved measurements, booked check-ins. All of that used to live only in
`agent tool …` log lines nobody could reach from the dashboard — so the
Activity Log told the story of the system (pickups, deals, orders) but not
of the AGENT. The owner asked for every activity of every turn (2026-08-19);
these rows are that trail, rendered into the same Activity Log ledger.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, ForeignKey, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class AgentActivity(Base):
    __tablename__ = "agent_activities"

    # The Activity Log reads one conversation's trail ordered by time — the
    # same hot shape as messages, so the same composite index.
    __table_args__ = (
        Index("ix_agent_activities_conversation_id_created_at",
              "conversation_id", "created_at"),
    )

    id              : Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id : Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True)
    person_id       : Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("persons.id", ondelete="SET NULL"), nullable=True)
    channel         : Mapped[str]              = mapped_column(String(20), nullable=False)
    # Channel-native handle (wa_id | PSID | web session key) — lets the trail
    # survive even when no conversation row could be resolved.
    contact         : Mapped[str | None]       = mapped_column(String(128), nullable=True, index=True)
    tool            : Mapped[str]              = mapped_column(String(40), nullable=False)
    # The human-readable line the Activity Log shows ("Searched the catalogue"),
    # and the specifics beneath it ("“communion tray” → 3 results").
    summary         : Mapped[str]              = mapped_column(Text, nullable=False)
    detail          : Mapped[str | None]       = mapped_column(Text, nullable=True)
    # Compact echo of the tool call for debugging — bounded at write time.
    payload         : Mapped[dict | None]      = mapped_column(JSONB, nullable=True)
    created_at      : Mapped[datetime]         = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, index=True)
