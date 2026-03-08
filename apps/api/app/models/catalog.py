import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, Boolean, Numeric, DateTime, ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base

class Catalog(Base):
    __tablename__ = "catalog"

    id          : Mapped[uuid.UUID]  = mapped_column(primary_key=True, default=uuid.uuid4)
    sku         : Mapped[str]        = mapped_column(String(30), nullable=False, unique=True)
    name        : Mapped[str]        = mapped_column(String(200), nullable=False)
    aliases     : Mapped[list]       = mapped_column(ARRAY(String), default=list)
    price       : Mapped[Decimal]    = mapped_column(Numeric(12, 2), nullable=False)
    unit        : Mapped[str | None] = mapped_column(String(30), nullable=True)
    category    : Mapped[str | None] = mapped_column(String(60), nullable=True)
    description : Mapped[str | None] = mapped_column(Text, nullable=True)
    in_stock    : Mapped[bool]       = mapped_column(Boolean, default=True)
    updated_at  : Mapped[datetime]   = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)