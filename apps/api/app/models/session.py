import uuid
from datetime import datetime
from sqlalchemy import String, BigInteger, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base

class Session(Base):
    __tablename__ = "sessions"

    id            : Mapped[str]      = mapped_column(String(80), primary_key=True)
    wa_id         : Mapped[str]      = mapped_column(String(30), nullable=False, index=True)
    start_ts      : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ts       : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    turns         : Mapped[int]      = mapped_column(Integer, default=0)
    ttl_expire_at : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)