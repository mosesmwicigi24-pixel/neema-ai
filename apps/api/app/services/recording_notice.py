"""The written recording / transcription notice — once per customer, OFF by default.

Calls are recorded by the softphone (browser / Android) and voice notes are
transcribed by OpenAI; Meta's own spoken announcement is off by owner choice
(CALL_META_TRANSCRIPTION / CALL_META_RECORDING stay false). With
CALL_RECORDING_NOTICE_ENABLED on, the customer gets ONE short written line
the first time one of their calls connects while recording is enabled.

Why there, and only there:
  * It is the one moment every recorded call passes through —
    call_log.mark_answered moves a call ringing → answered for inbound calls
    (an agent picks up) AND outbound ones (the customer picks up), on WhatsApp
    and Messenger alike, exactly once per call (a conditional UPDATE, so a
    replayed webhook never moves it twice). Recording starts at that moment.
  * The call-permission request can't carry it for every call: inbound calls
    never pass through one, the outside-24 h route is a Meta-approved template
    (new wording = new approval), and Messenger's `calling_optin` has no text
    of ours at all.
  * Once per customer, ever (the recording_notices primary key) — never on
    every call.

Window rules: free-form text only inside Meta's 24 h customer-service window
— WhatsApp: their last inbound message or inbound call (call_log); Messenger:
the standard RESPONSE window (no tag — this is automated, never HUMAN_AGENT).
Outside it nothing is sent: logged, and NOT claimed, so the next connected
call inside the window sends it.
"""
import asyncio
import logging

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings

_log = logging.getLogger("neema.calls")

_bg_tasks: set = set()

# Outcomes (returned for tests; logged for the box).
DISABLED, RECORDING_OFF, NO_RECIPIENT, OUTSIDE_WINDOW = "disabled", "recording_off", "no_recipient", "outside_window"
ALREADY, SENT, FAILED = "already", "sent", "failed"


def notice_text() -> str:
    return (settings.call_recording_notice_text or "").strip()


def active() -> bool:
    return bool(settings.call_recording_notice_enabled and settings.call_recording_enabled
                and notice_text())


def schedule(call_id: str, redis=None) -> None:
    """Fire-and-forget from the answer path (which must not wait on Meta).
    A no-op — no task at all — while the notice is off."""
    if not active():
        return
    try:
        task = asyncio.get_running_loop().create_task(_guarded(call_id, redis))
    except RuntimeError as exc:                     # no running loop: nothing to send from
        _log.warning("recording notice not scheduled for %s: %s", call_id, exc)
        return
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _guarded(call_id: str, redis) -> None:
    try:
        await send_for_call(call_id, redis)
    except Exception as exc:                        # a background task has no caller to raise to
        _log.exception("recording notice for call %s crashed: %s", call_id, exc)


async def send_for_call(call_id: str, redis=None) -> str:
    """Send the notice for this (just connected) call when it is due. Returns
    the outcome; every outcome but SENT/ALREADY/DISABLED is logged."""
    if not settings.call_recording_notice_enabled or not notice_text():
        return DISABLED
    if not settings.call_recording_enabled:
        return RECORDING_OFF
    from app.database import AsyncSessionLocal
    from app.models.call import Call
    from app.models.recording_notice import RecordingNotice
    async with AsyncSessionLocal() as db:
        call = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
        channel = (getattr(call, "channel", None) or "whatsapp") if call else None
        recipient = None
        if call is not None:
            recipient = call.external_id if channel == "messenger" else (call.wa_id or "").lstrip("+")
        if not recipient or channel not in ("whatsapp", "messenger"):
            _log.warning("recording notice: call %s has no customer to write to", call_id)
            return NO_RECIPIENT
        if await _already(db, RecordingNotice, channel, recipient):
            return ALREADY
        conv = None
        if channel == "whatsapp":
            from app.services.call_log import in_service_window
            in_window = await in_service_window(db, recipient)
        else:
            from app.models.conversation import Conversation
            from app.services.conversation import messaging_window
            conv = (await db.execute(select(Conversation).where(
                Conversation.channel == "messenger", Conversation.external_id == recipient)
            )).scalars().first()
            in_window = conv is not None and (await messaging_window(db, conv)).get("mode") == "open"
        if not in_window:
            _log.info("recording notice skipped for %s %s (call %s): outside the 24 h window",
                      channel, recipient, call_id)
            return OUTSIDE_WINDOW
        # Claim before sending: the primary key lets exactly one sender through.
        claimed = (await db.execute(
            insert(RecordingNotice).values(channel=channel, recipient=recipient, call_id=call_id)
            .on_conflict_do_nothing(index_elements=["channel", "recipient"])
            .returning(RecordingNotice.recipient))).first()
        await db.commit()
        if claimed is None:
            return ALREADY
        text = notice_text()
        try:
            wamid = await _deliver(channel, recipient, text)
        except Exception as exc:
            # Not delivered: give the claim back so the next call tries again.
            _log.warning("recording notice to %s %s failed (call %s): %s — will retry on a later call",
                         channel, recipient, call_id, exc)
            await db.execute(delete(RecordingNotice).where(
                RecordingNotice.channel == channel, RecordingNotice.recipient == recipient,
                RecordingNotice.call_id == call_id))
            await db.commit()
            return FAILED
        # Delivered: keep it in the thread so the team sees what was said. A
        # failure here must not resend (the customer has it) — logged only.
        try:
            from app.services import n8n_bridge
            if channel == "whatsapp":
                await n8n_bridge.save_outbound_message(db, redis, recipient, text, waba_msg_id=wamid)
            else:
                await n8n_bridge.save_outbound_channel_message(db, redis, channel, recipient, text)
        except Exception as exc:
            await db.rollback()
            _log.warning("recording notice to %s %s sent but not saved to the thread: %s",
                         channel, recipient, exc)
        _log.info("recording notice sent to %s %s (call %s)", channel, recipient, call_id)
        return SENT


async def _already(db, model, channel: str, recipient: str) -> bool:
    return (await db.execute(select(model.recipient).where(
        model.channel == channel, model.recipient == recipient))).first() is not None


async def _deliver(channel: str, recipient: str, text: str) -> str | None:
    """One free-form text. Raises on any refusal (the caller releases the claim)."""
    if channel == "whatsapp":
        from app.services import n8n_bridge
        return await n8n_bridge._send_waba(recipient, text)
    from app.services.meta_send import page_of_contact, send_meta_message
    page_id = await page_of_contact(channel, recipient)
    await send_meta_message(recipient, text, page_id=page_id)
    return None
