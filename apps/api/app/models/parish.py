import uuid
from datetime import datetime

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Parish(Base):
    """The institution behind the individual — the priest orders, the PARISH buys.

    Rev Grace, the parish secretary and the choir master are three persons, but
    one customer: St Mary's Nakuru. Grouping them under a parish is what makes
    institutional selling possible — parish-level history ("St Mary's bought
    purple last Advent"), one seasonal message per parish instead of three, and
    a truthful answer to "who are our biggest customers?".

    Deliberately thin, like Person: name + where. `norm` is the dedup key so
    "St. Mary's Nakuru" and "st marys nakuru" resolve to ONE parish.
    """
    __tablename__ = "parishes"

    id         : Mapped[uuid.UUID]  = mapped_column(primary_key=True, default=uuid.uuid4)
    name       : Mapped[str]        = mapped_column(String(200))
    norm       : Mapped[str]        = mapped_column(String(200), unique=True, index=True)
    location   : Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at : Mapped[datetime]   = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
