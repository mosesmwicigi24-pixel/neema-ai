from datetime import datetime
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base

class CustomerHistory(Base):
    __tablename__ = "customer_history"

    wa_id         : Mapped[str]      = mapped_column(String(30), primary_key=True)
    last_status   : Mapped[str | None] = mapped_column(String(30), nullable=True)
    has_open_order: Mapped[bool]     = mapped_column(Boolean, default=False)
    last_event    : Mapped[dict]     = mapped_column(JSONB, default=dict)
    last_chat     : Mapped[dict]     = mapped_column(JSONB, default=dict)
    last_order    : Mapped[dict]     = mapped_column(JSONB, default=dict)
    counts        : Mapped[dict]     = mapped_column(JSONB, default=dict)
    updated_at    : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)