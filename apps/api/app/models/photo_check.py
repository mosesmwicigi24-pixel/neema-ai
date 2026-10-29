import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class PhotoCheck(Base):
    """One customer photo, checked against what we sell (services/photo_check).

    The owner's review list: in shadow mode every check is recorded and
    nothing changes, so the owner marks the wrong ones before referrals go
    live (owner, 2026-10-29). verdict: ours | close | refer | not_product |
    unknown. owner_mark: right | wrong, set from Reports → Photo checks."""
    __tablename__ = "photo_checks"

    id               : Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at       : Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    channel          : Mapped[str]              = mapped_column(String(20), default="whatsapp")
    contact          : Mapped[str]              = mapped_column(String(128))
    conversation_id  : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    message_id       : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    media_url        : Mapped[str | None]       = mapped_column(Text, nullable=True)
    image_sha        : Mapped[str | None]       = mapped_column(String(40), nullable=True, index=True)
    verdict          : Mapped[str]              = mapped_column(String(16), index=True)
    product          : Mapped[str | None]       = mapped_column(String(200), nullable=True)
    product_slug     : Mapped[str | None]       = mapped_column(String(200), nullable=True)
    match            : Mapped[str | None]       = mapped_column(String(8), nullable=True)
    ai_made          : Mapped[str | None]       = mapped_column(String(10), nullable=True)
    extra_embroidery : Mapped[bool | None]      = mapped_column(Boolean, nullable=True)
    reasons          : Mapped[list | None]      = mapped_column(JSONB, nullable=True)
    source           : Mapped[str | None]       = mapped_column(String(16), nullable=True)
    mode             : Mapped[str]              = mapped_column(String(8), default="shadow")
    acted            : Mapped[bool]             = mapped_column(Boolean, default=False)
    owner_mark       : Mapped[str | None]       = mapped_column(String(8), nullable=True)
    owner_note       : Mapped[str | None]       = mapped_column(Text, nullable=True)
    marked_by        : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    marked_at        : Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
