"""Operator-editable application settings — tiny KV store.

First user: `operator_directives` (Phase E of docs/AGENTIC_PARTNER_PLAN.md) —
the standing orders Neema reads before every reply ("push copes this week").
A settings table instead of env vars so the OWNER can steer the agent from the
dashboard, between deploys, in seconds.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from app.models import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    id         : Mapped[str] = mapped_column(String(100), primary_key=True)
    value      : Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by : Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    updated_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
