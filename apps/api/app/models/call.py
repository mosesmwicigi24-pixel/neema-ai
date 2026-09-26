import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Call(Base):
    """A WhatsApp voice call — one row per inbound call, its whole lifecycle.

    status (services/call_log.py owns the transitions):
      ringing → answered → completed               (a call that connected)
      ringing → missed                             (inbound, nobody answered)
      ringing → declined | callback                (inbound, an agent turned it down)
      ringing → no_answer | cancelled | failed     (outbound, never connected)
    Rows written before 2026-09 say `ended` for `completed`; the API reports both
    as `completed`. The
    webhook creates it on `connect` (ringing) and closes it on `terminate`; the
    softphone's answer marks it answered + records who picked up. Kept as its own
    table so the Calls view can show recents (like a phone), measure durations,
    and tie each call to the person who called (linked by wa_id → identity).
    """
    __tablename__ = "calls"

    id           : Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    call_id      : Mapped[str]              = mapped_column(String(200), unique=True, index=True)  # Meta wacid
    wa_id        : Mapped[str | None]       = mapped_column(String(30), index=True)   # caller number
    caller_name  : Mapped[str | None]       = mapped_column(String(200), nullable=True)
    direction    : Mapped[str]              = mapped_column(String(10), default="inbound")
    status       : Mapped[str]              = mapped_column(String(20), default="ringing", index=True)
    person_id    : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True)
    agent_id     : Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    duration     : Mapped[int | None]       = mapped_column(Integer, nullable=True)   # seconds
    started_at   : Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    answered_at  : Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at     : Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    # Recording + transcript + AI summary (self-hosted Whisper → Claude). Populated
    # post-call: the browser records both sides and uploads on hangup; transcription
    # runs on our box; the summary is saved here AND as a customer note by phone.
    recording_url    : Mapped[str | None]   = mapped_column(String(500), nullable=True)  # served audio URL
    transcript       : Mapped[str | None]   = mapped_column(Text, nullable=True)          # full STT text
    transcript_lang  : Mapped[str | None]   = mapped_column(String(12), nullable=True)    # detected language
    summary          : Mapped[str | None]   = mapped_column(Text, nullable=True)          # LLM call brief
    # none | recorded | pending | processing | done | failed
    transcript_status: Mapped[str]          = mapped_column(String(20), default="none")
    # Structured post-call brief from the transcript (services/call_transcribe.py):
    # {intent, products[], objections[], commitments[], next_action,
    #  follow_up_message, sentiment}. NULL until a transcript is summarised.
    insights         : Mapped[dict | None]  = mapped_column(JSONB, nullable=True)
    # A missed / callback call is an open follow-up until someone calls the
    # customer back (a later connected call closes it too) or marks it done.
    follow_up_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
