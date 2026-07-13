"""Persist the WhatsApp call lifecycle so the Calls view can show recents.

Best-effort throughout: a failure here must never break the call itself (which
is why the webhook/endpoints wrap these in try/except). Each helper opens its own
short session.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.call import Call

_log = logging.getLogger("neema.wa")


async def record_ringing(call_id: str, wa_id: str | None, name: str | None) -> None:
    """Create the call row on `connect` (status=ringing). Resolves the person so
    the Calls view can link to the customer. Idempotent on call_id."""
    try:
        async with AsyncSessionLocal() as db:
            exists = (await db.execute(select(Call.id).where(Call.call_id == call_id))).scalar_one_or_none()
            if exists:
                return
            person_id = None
            if wa_id:
                from app.services.identity import resolve_person_id_for_wa_id
                try:
                    person_id = await resolve_person_id_for_wa_id(db, wa_id, source="whatsapp_call")
                except Exception:
                    person_id = None
            db.add(Call(call_id=call_id, wa_id=wa_id, caller_name=name,
                        status="ringing", person_id=person_id))
            await db.commit()
    except Exception as exc:
        _log.warning("call_log ringing failed: %s", exc)


async def mark_answered(call_id: str, agent_id) -> None:
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c and c.status in ("ringing",):
                c.status = "answered"
                c.answered_at = datetime.now(timezone.utc)
                c.agent_id = agent_id
                await db.commit()
    except Exception as exc:
        _log.warning("call_log answered failed: %s", exc)


async def mark_ended(call_id: str, status: str | None = None, duration: int | None = None) -> None:
    """Close the call on `terminate`. A call that was never answered becomes
    `missed` (or `declined` if we hung up); an answered one becomes `ended`."""
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if not c or c.status in ("ended", "missed", "declined"):
                return
            c.ended_at = datetime.now(timezone.utc)
            if duration is not None:
                c.duration = duration
            elif c.answered_at:
                c.duration = int((c.ended_at - c.answered_at).total_seconds())
            c.status = "ended" if c.answered_at else (status or "missed")
            await db.commit()
    except Exception as exc:
        _log.warning("call_log ended failed: %s", exc)
