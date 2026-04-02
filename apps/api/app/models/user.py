import uuid
from datetime import datetime
from sqlalchemy import String, Text, Boolean, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base

class User(Base):
    __tablename__ = "users"

    id              : Mapped[uuid.UUID]   = mapped_column(primary_key=True, default=uuid.uuid4)
    wa_id           : Mapped[str]         = mapped_column(String(30), nullable=False, unique=True, index=True)
    phone           : Mapped[str | None]  = mapped_column(String(30), nullable=True)
    name            : Mapped[str | None]  = mapped_column(String(100), nullable=True)
    name_confirmed  : Mapped[bool]        = mapped_column(Boolean, default=False)
    email           : Mapped[str | None]  = mapped_column(String(200), nullable=True)
    location        : Mapped[str | None]  = mapped_column(String(200), nullable=True)
    age             : Mapped[int | None]  = mapped_column(Integer, nullable=True)
    country         : Mapped[str | None]   = mapped_column(String(100), nullable=True)
    country_iso     : Mapped[str | None]   = mapped_column(String(5),   nullable=True)
    flag_url        : Mapped[str | None]   = mapped_column(String(200), nullable=True)
    last_text       : Mapped[str | None]  = mapped_column(Text, nullable=True)
    last_direction  : Mapped[str | None]  = mapped_column(String(10), nullable=True)
    last_message_at : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state           : Mapped[dict]        = mapped_column(JSONB, default=lambda: {"active": "active", "cart": {"items": [], "subtotal": 0}})
    created_at      : Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at      : Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)