from datetime import datetime, timezone
from sqlalchemy import String, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base


class RecordingNotice(Base):
    """The written recording / transcription notice went to this customer
    (services/recording_notice.py). One row per (channel, recipient), ever —
    the primary key IS the once-per-customer guarantee: the sender claims the
    row with INSERT … ON CONFLICT DO NOTHING before it sends, so two calls
    answered at the same instant (or a replayed webhook) send one notice. A
    send that fails gives the row back so a later call can try again."""
    __tablename__ = "recording_notices"

    channel   : Mapped[str] = mapped_column(String(20), primary_key=True)    # whatsapp | messenger
    recipient : Mapped[str] = mapped_column(String(64), primary_key=True)    # wa_id | PSID
    call_id   : Mapped[str | None] = mapped_column(String(200), nullable=True)  # the call it went out at
    sent_at   : Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"))
