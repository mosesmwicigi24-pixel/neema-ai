"""Voice notes, interpreted (cycle 5, 2026-10-05).

Every inbound voice note — WhatsApp, Messenger, Instagram — is transcribed by
the one engine (services/transcribe.py) and the outcome lands on its message
row, where the team, the agent and the inbox all read it:

  · messages.text               the VERBATIM transcript (the contract the
                                dashboard's audio bubble, the agent's history
                                and the inbox preview already read). Until it
                                is in, the placeholder stays ("[audio received]").
  · messages.transcript_status  none | queued | processing | done | silent |
                                failed:<reason>  — the team sees WHY under the
                                player ("today's transcription budget is used up").
  · messages.transcript_lang    the spoken language, ISO-639-1.
  · translated_text / _from     English, when the note is not English
                                ("Translated from Swahili"), via the translator.

The flow never makes Meta's webhook wait for a provider: the row is saved at
once (status `queued`, the dashboard shows "Transcribing…"), the transcription
runs in the background, and the agent's turn carries a TOKEN for the note that
is resolved — after the debounce window, when the words are almost always in —
into one of three lines the prompt knows (prompt.py, VOICE NOTES):

  🎤 (voice note): <the customer's words>
  🎤 (voice note — no speech could be heard in it)
  🎤 (voice note — it could not be transcribed: <reason>)

The words are the customer's speech: they ride in the USER turn, never the
system prompt, and the prompt says plainly that anything in them that looks
like an instruction is just something the customer said. A token resolves only
against the SAME customer's inbound audio row — a customer who types a token
cannot read anyone else's note.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid

from sqlalchemy import select, update

from app.core.config import settings

_log = logging.getLogger("neema.voice")
_bg: set = set()

PLACEHOLDER = "[audio received]"
TOKEN_RE = re.compile(r"⟦voice:([0-9a-fA-F-]{36})⟧")
WAIT_SECONDS = 60          # how long a turn waits for a note still being transcribed
_PENDING = ("queued", "processing")


def token(message_id) -> str:
    return f"⟦voice:{message_id}⟧"


def strip_tokens(text: str | None) -> str:
    """Remove anything token-shaped from text a CUSTOMER typed (defence in
    depth: resolution also checks ownership)."""
    return TOKEN_RE.sub("", text or "")


# ── what the agent reads ─────────────────────────────────────────────────────

def turn_line(status: str | None, text: str | None, translation: str | None = None,
              translated_from: str | None = None) -> str:
    """The agent's view of one voice note, by its transcription outcome.

    A note in another language carries the team's English translation on a
    second line (voice note → sale, 2026-10-05: a Lingala or Urdu note was
    the agent's to puzzle out alone) — marked as a machine translation: the
    customer's own words come first and rule, and the reply stays in the
    language they spoke."""
    from app.services import transcribe as stt
    s = (status or "").strip()
    words = (text or "").strip()
    if s == "done" and words and words != PLACEHOLDER:
        line = f"🎤 (voice note): {words}"
        en = (translation or "").strip()
        if en and en != words and translated_from and translated_from.lower() != "english":
            line += (f"\n   (machine translation from {translated_from} — their own words "
                     f"above rule if the two differ: {en})")
        return line
    if s == "silent":
        return "🎤 (voice note — no speech could be heard in it)"
    if s in _PENDING:
        return "🎤 (voice note — still being transcribed, its words are not in yet)"
    if s.startswith("failed:") or s == "failed":
        return f"🎤 (voice note — it could not be transcribed: {stt.describe(s)})"
    return "🎤 (voice note — it was not transcribed)"


def history_text(m) -> str | None:
    """The line the agent's history shows for an inbound audio row, or None
    when the row is not a customer voice note (caller uses `text` as is)."""
    try:
        from app.models.message import MsgDirection
        if getattr(m, "media_type", None) != "audio" or m.direction != MsgDirection.inbound:
            return None
    except Exception:
        return None
    status = getattr(m, "transcript_status", None)
    text = (m.text or "").strip()
    if status is None and text and not text.startswith("["):
        status = "done"            # pre-2026-10-05 rows that WERE transcribed
    return turn_line(status, text, getattr(m, "translated_text", None),
                     getattr(m, "translated_from", None))


# ── the row ──────────────────────────────────────────────────────────────────

async def _claim(db, message_id) -> bool:
    """Atomically move a row into `processing` — only from a state that has
    no answer yet (NULL, queued, failed:*). Two workers, one transcription."""
    from app.models.message import Message
    res = await db.execute(
        update(Message)
        .where(Message.id == message_id)
        .where(Message.transcript_status.is_(None)
               | Message.transcript_status.in_(("queued", "failed"))
               | Message.transcript_status.like("failed:%"))
        .values(transcript_status="processing")
        .returning(Message.id))
    got = res.scalar_one_or_none() is not None
    await db.commit()
    return got


def _app_redis():
    """The app's redis (attached at boot), for a caller that passed none."""
    try:
        from app.services import ai_budget
        return ai_budget._sink
    except Exception:
        return None


def _local_file(media_url: str | None) -> str | None:
    """A served media URL → the file in our media dir, when it is one of ours."""
    if not media_url:
        return None
    from urllib.parse import urlparse
    name = os.path.basename(urlparse(media_url).path)
    if not name:
        return None
    from app.routers.media import MEDIA_DIR
    p = os.path.join(MEDIA_DIR, name)
    return p if os.path.isfile(p) else None


async def interpret(message_id, *, path: str | None = None, url: str | None = None,
                    redis=None) -> str:
    """Transcribe one voice-note row, translate it when not English, persist
    and tell every open screen. Returns the stored status. Never raises."""
    from app.database import AsyncSessionLocal
    from app.models.message import Message
    from app.services import transcribe as stt
    tmp = None
    try:
        mid = uuid.UUID(str(message_id))
        async with AsyncSessionLocal() as db:
            if not await _claim(db, mid):
                row = await db.get(Message, mid)
                return (row.transcript_status or "none") if row is not None else "missing"
            row = await db.get(Message, mid)
            if row is None:
                return "missing"
            media_url = row.media_url
        # When the work STARTED — the recovery sweep measures "stuck" from
        # here, never from the note's arrival (a late retry is not stuck).
        from app.services.transcript_recovery import mark_claimed
        await mark_claimed(redis if redis is not None else _app_redis(), "msg", mid)
        await _broadcast(redis, mid, status="processing")

        why = stt.configured()
        if why:
            res = stt.failed(why)
        else:
            src = path if (path and os.path.isfile(path)) else _local_file(media_url)
            if not src and (url or media_url):
                from app.services.meta_media import fetch_audio
                tmp = src = await fetch_audio(url or media_url)
            res = await stt.transcribe_file(src, kind="voice_note", redis=redis)

        lang = res.lang
        name, english = None, None
        if res.ok and settings.transcribe_translate:
            from app.services.translate import translate_transcript
            hint = lang if res.lang_source == "provider" else (lang if lang == "en" else None)
            name, english = await translate_transcript(redis, res.text, hint)
            if name and res.lang_source != "provider":
                lang = stt.lang_code(name) or lang
        return await _store(mid, res, lang, name, english, redis)
    except Exception as exc:                  # noqa: BLE001 — never raises
        _log.exception("voice note %s: interpretation failed: %s", message_id, exc)
        try:
            await _store_status(message_id, "failed:error", redis)
        except Exception:
            pass
        return "failed:error"
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass


async def _store(mid, res, lang, lang_name, english, redis) -> str:
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation
    from app.models.message import Message
    async with AsyncSessionLocal() as db:
        row = await db.get(Message, mid)
        if row is None:
            return "missing"
        if not res.ok and row.transcript_status == "done":
            # A second run (a recovery sweep racing a slow original, a twin
            # that timed out waiting) never turns heard words back into a
            # failure.
            return "done"
        row.transcript_status = res.status
        row.transcript_lang = (lang or None) and str(lang)[:12]
        if res.ok:
            caption = (row.text or "").strip()
            keep = caption and caption != PLACEHOLDER and not caption.startswith("[")
            # A caption the customer typed stays; the words follow it.
            row.text = f"{caption}\n{res.text}" if keep else res.text
            if english:
                row.translated_text = english
                row.translated_from = (lang_name or None) and str(lang_name)[:24]
            else:
                row.translated_text = row.text        # "nothing to translate" marker
                row.translated_from = None
            # The inbox preview: the words, while this note is still the latest.
            # (Checked — the preview being a placeholder is not enough: a
            # recovered or backfilled OLD note would overwrite "[image]" from a
            # later message with words from days ago.)
            if row.conversation_id:
                conv = await db.get(Conversation, row.conversation_id)
                if conv is not None and (conv.last_message_preview or "").startswith("[") \
                        and await _is_latest(db, row):
                    conv.last_message_preview = f"🎤 {res.text}"[:100]
        await db.commit()
        out = dict(status=row.transcript_status, text=row.text, lang=row.transcript_lang,
                   translation=english, translated_from=row.translated_from if english else None,
                   conv_id=str(row.conversation_id) if row.conversation_id else None)
    await _broadcast(redis, mid, **out)
    return res.status


async def _is_latest(db, row) -> bool:
    """No later message in this conversation than `row`."""
    from sqlalchemy import func
    from app.models.message import Message
    if row.created_at is None:
        return True
    later = (await db.execute(select(func.count()).select_from(Message).where(
        Message.conversation_id == row.conversation_id,
        Message.created_at > row.created_at,
        Message.id != row.id))).scalar_one()
    return not later


async def _store_status(message_id, status: str, redis) -> None:
    from app.database import AsyncSessionLocal
    from app.models.message import Message
    async with AsyncSessionLocal() as db:
        await db.execute(update(Message).where(Message.id == uuid.UUID(str(message_id)))
                         .values(transcript_status=status))
        await db.commit()
    await _broadcast(redis, message_id, status=status)


async def _broadcast(redis, mid, *, status: str, text: str | None = None, lang: str | None = None,
                     translation: str | None = None, translated_from: str | None = None,
                     conv_id: str | None = None) -> None:
    """`voice_transcript` on the conversation's channel — the open thread
    patches the bubble in place. Best-effort."""
    if redis is None:
        return
    try:
        if conv_id is None:
            from app.database import AsyncSessionLocal
            from app.models.message import Message
            async with AsyncSessionLocal() as db:
                row = await db.get(Message, uuid.UUID(str(mid)))
                if row is None or row.conversation_id is None:
                    return
                conv_id = str(row.conversation_id)
                if text is None and status in ("done",):
                    text = row.text
        payload = {"type": "voice_transcript", "conversationId": conv_id, "id": str(mid),
                   "transcriptStatus": status, "transcriptNote": _note(status),
                   "transcriptLang": lang}
        if text is not None and status == "done":
            payload["text"] = text
        if translation:
            payload["translation"] = translation
            payload["translatedFrom"] = translated_from
        await redis.publish(f"ws:channel:{conv_id}", json.dumps(payload))
    except Exception:
        pass


def _note(status: str | None) -> str | None:
    from app.services import transcribe as stt
    kind = stt.status_kind(status)
    if kind in ("failed", "silent"):
        return stt.describe(status)
    return None


def note_for(m) -> str | None:
    """The team-facing words under a voice note's player (failed / silent)."""
    if getattr(m, "media_type", None) != "audio":
        return None
    return _note(getattr(m, "transcript_status", None))


# ── scheduling + resolution ──────────────────────────────────────────────────

def schedule(message_id, *, path: str | None = None, url: str | None = None, redis=None) -> None:
    """Fire-and-forget `interpret` (keeps a strong ref so the task survives)."""
    try:
        task = asyncio.get_running_loop().create_task(
            interpret(message_id, path=path, url=url, redis=redis))
    except RuntimeError:
        return
    _bg.add(task)
    task.add_done_callback(_bg.discard)


async def resolve(text: str | None, *, channel: str, key: str,
                  wait_seconds: float | None = None) -> str:
    """Replace each voice token in a turn's text with the agent's line for that
    note, waiting (bounded) for notes still being transcribed. A token that is
    not THIS customer's inbound audio row is dropped, never resolved."""
    if not text or "⟦voice:" not in text:
        return text or ""
    ids = []
    for m in TOKEN_RE.finditer(text):
        try:
            ids.append(uuid.UUID(m.group(1)))
        except ValueError:
            continue
    lines = await _lines_for(ids, channel, key,
                             WAIT_SECONDS if wait_seconds is None else wait_seconds)

    def sub(m):
        try:
            return lines.get(uuid.UUID(m.group(1)), "")
        except ValueError:
            return ""
    out = TOKEN_RE.sub(sub, text)
    return "\n".join(ln for ln in (x.strip() for x in out.split("\n")) if ln)


async def _lines_for(ids: list, channel: str, key: str, wait_seconds: float) -> dict:
    from app.database import AsyncSessionLocal
    from app.models.message import Message, MsgDirection
    if not ids:
        return {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, wait_seconds)
    # Poll quickly at first (the words are usually seconds away), then back
    # off to 1.5 s: a flat 0.25 s was 4 queries a second, up to 240 per
    # waiting turn (measured, cycle 7).
    pause = 0.25
    while True:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(Message).where(Message.id.in_(ids)))).scalars().all()
        mine = {}
        for r in rows:
            owner = (r.wa_id == key) if channel == "whatsapp" else (
                r.channel == channel and r.external_id == key)
            if owner and r.media_type == "audio" and r.direction == MsgDirection.inbound:
                mine[r.id] = r
        pending = [r for r in mine.values() if r.transcript_status in _PENDING]
        if not pending or loop.time() >= deadline:
            return {i: turn_line(r.transcript_status, r.text, r.translated_text,
                                 r.translated_from) for i, r in mine.items()}
        await asyncio.sleep(min(pause, max(0.05, deadline - loop.time())))
        pause = min(1.5, pause * 1.5)
