import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base


class ClientCrash(Base):
    """A crash report the Android app sent after it closed unexpectedly (or an
    error it caught in a background job). Kept so the owner can read — and
    hand over — the exact stack trace instead of 'the app closed'."""
    __tablename__ = "client_crashes"

    id          : Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    report_id   : Mapped[str] = mapped_column(String(64), unique=True, index=True)
    agent_id    : Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_name  : Mapped[str | None] = mapped_column(String(120), nullable=True)
    kind        : Mapped[str] = mapped_column(String(20))
    occurred_at : Mapped[str | None] = mapped_column(String(40), nullable=True)
    summary     : Mapped[str] = mapped_column(String(500), default="")
    trace       : Mapped[str] = mapped_column(Text, default="")
    thread      : Mapped[str | None] = mapped_column(String(120), nullable=True)
    app_version : Mapped[str] = mapped_column(String(40), default="")
    build       : Mapped[str] = mapped_column(String(40), default="")
    device      : Mapped[str] = mapped_column(String(120), default="")
    sdk         : Mapped[int] = mapped_column(Integer, default=0)
    created_at  : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
