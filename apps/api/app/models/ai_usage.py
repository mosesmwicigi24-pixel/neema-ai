import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Numeric, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base


class AiUsage(Base):
    """One row per LLM call, logged by n8n via POST /api/n8n/usage.

    Makes token spend visible per conversation / workflow / model so cost
    optimizations can be measured instead of guessed at.
    """
    __tablename__ = "ai_usage"

    id                : Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    wa_id             : Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    workflow          : Mapped[str | None] = mapped_column(String(80), nullable=True)
    node              : Mapped[str | None] = mapped_column(String(80), nullable=True)
    model             : Mapped[str | None] = mapped_column(String(60), nullable=True)
    prompt_tokens     : Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens : Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens     : Mapped[int] = mapped_column(Integer, default=0)
    cost_usd          : Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    created_at        : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
