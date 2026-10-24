import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base


class PushDevice(Base):
    """A phone that should ring when a customer calls, even with the app closed:
    its Firebase Cloud Messaging token and whose phone it is. One row per token
    (a token moves with the app install, so a second sign-in on the same phone
    takes the row over). Tokens Firebase calls dead are deleted on the next send
    (services/push.py)."""
    __tablename__ = "push_devices"

    id           : Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token        : Mapped[str] = mapped_column(String(512), unique=True, index=True)
    agent_id     : Mapped[str] = mapped_column(String(64), index=True)
    platform     : Mapped[str] = mapped_column(String(16), default="android")
    app_version  : Mapped[str] = mapped_column(String(40), default="")
    device       : Mapped[str] = mapped_column(String(120), default="")
    created_at   : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen_at : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
