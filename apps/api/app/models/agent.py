import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Enum as PgEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base
import enum

class AgentRole(str, enum.Enum):
    admin    = "admin"
    agent    = "agent"
    readonly = "readonly"

class Agent(Base):
    __tablename__ = "agents"

    id           : Mapped[uuid.UUID]   = mapped_column(primary_key=True, default=uuid.uuid4)
    name         : Mapped[str]         = mapped_column(String(100), nullable=False)
    email        : Mapped[str]         = mapped_column(String(200), nullable=False, unique=True)
    password_hash: Mapped[str]         = mapped_column(nullable=False)
    role         : Mapped[AgentRole]   = mapped_column(PgEnum(AgentRole), default=AgentRole.agent)
    is_available : Mapped[bool]        = mapped_column(Boolean, default=True)
    is_superuser : Mapped[bool]        = mapped_column(Boolean, default=False)
    active_convs : Mapped[int]         = mapped_column(Integer, default=0)
    avatar_url   : Mapped[str | None]  = mapped_column(nullable=True)
    created_at   : Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_seen_at : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)