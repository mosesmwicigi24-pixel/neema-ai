"""Call recording → transcript → AI summary. Zero marginal cost by default.

The audio is recorded in the agent's browser (both sides mixed by the Web Audio
API) and uploaded on hangup — free. Transcription runs on OUR box via
faster-whisper (self-hosted, no per-call API cost); the Whisper model handles
Swahili, English, and the code-switching Kenyan customers actually speak. The
transcript is summarised by the existing Claude client (reuses infra — no new
vendor) and saved (a) on the Call row and (b) as a durable customer note keyed by
phone number, so it shows in the sidebar Notes AND Neema recalls it next chat.

faster-whisper is an OPTIONAL dependency: it is lazy-imported and gated by
settings.whisper_enabled, so the app runs fine without it installed. The blocking
CPU inference runs via asyncio.to_thread so it never stalls the event loop. Swap
to a cloud provider (Groq / OpenAI Whisper) later by flipping whisper_provider —
one config change, no code rework.
"""
import asyncio
import logging
import os

from sqlalchemy import select

from app.core.config import settings
from app.database import AsyncSessionLocal
from app.models.call import Call

_log = logging.getLogger("neema.wa")
_bg_tasks: set = set()

# faster-whisper weights are expensive to load — cache the model across calls.
_fw_model = None


def _local_path(recording_url: str | None) -> str | None:
    """Map a served media URL back to the local file on disk."""
    if not recording_url:
        return None
    name = recording_url.rstrip("/").split("/")[-1]
    from app.routers.media import MEDIA_DIR
    p = os.path.join(MEDIA_DIR, name)
    return p if os.path.exists(p) else None


def _transcribe_faster_whisper(path: str) -> tuple[str, str]:
    """BLOCKING. Self-hosted Whisper via faster-whisper — free, runs on the box.
    Auto-detects Swahili/English (and code-switching). Returns (text, language)."""
    global _fw_model
    from faster_whisper import WhisperModel  # optional dep — imported only when enabled
    if _fw_model is None:
        _fw_model = WhisperModel(
            settings.whisper_model, device="cpu",
            compute_type=settings.whisper_compute_type,
        )
    segments, info = _fw_model.transcribe(path, vad_filter=True, beam_size=5)
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, (getattr(info, "language", None) or "")


def _transcribe_openai(path: str) -> tuple[str, str]:
    """BLOCKING. OpenAI Whisper API (whisper-1). Costs money — opt-in."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    with open(path, "rb") as f:
        resp = client.audio.transcriptions.create(model="whisper-1", file=f)
    return (getattr(resp, "text", "") or "").strip(), getattr(resp, "language", "") or ""


def _transcribe_groq(path: str) -> tuple[str, str]:
    """BLOCKING. Groq Whisper (whisper-large-v3) — fast + cheap cloud, opt-in."""
    from groq import Groq
    client = Groq(api_key=settings.groq_api_key)
    with open(path, "rb") as f:
        resp = client.audio.transcriptions.create(model="whisper-large-v3", file=f)
    return (getattr(resp, "text", "") or "").strip(), ""


def _transcribe_sync(path: str) -> tuple[str, str]:
    provider = (settings.whisper_provider or "faster_whisper").lower()
    if provider == "openai":
        return _transcribe_openai(path)
    if provider == "groq":
        return _transcribe_groq(path)
    return _transcribe_faster_whisper(path)


async def summarize_transcript(transcript: str) -> str:
    """Summarise a call transcript with the existing Claude client (reuses infra —
    no new vendor). Works for Swahili or English; output is a short English brief
    the agent + Neema can act on."""
    from app.agent.runtime import build_llm
    llm = build_llm(model=settings.tier2_model_light, purpose="calls", cache=False)
    system = (
        "You summarise a phone call between a Bethany House sales agent and a "
        "customer (clergy apparel + communion supplies, Kenya). The transcript may "
        "be in Swahili, English, or a mix — understand all of it. Write a tight "
        "brief in English:\n"
        "• Who called and what they wanted\n"
        "• Products / quantities / sizes discussed\n"
        "• Any price agreed (KES)\n"
        "• Decisions and the next action / follow-up\n"
        "Be factual, no preamble, 4-7 short lines. If the transcript is empty or "
        "unintelligible, reply exactly: (No clear speech captured.)"
    )
    resp = await llm.complete(
        system=system,
        messages=[{"role": "user", "content": transcript[:12000]}],
        tools=[],
    )
    return (resp.text or "").strip()


_INSIGHT_KEYS = ("intent", "products", "objections", "commitments", "next_action",
                 "follow_up_message", "sentiment")


def _parse_insights(text: str) -> dict | None:
    """The model's JSON brief, tolerant of a code fence or prose around it."""
    import json
    import re
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    out: dict = {}
    for k in ("summary",) + _INSIGHT_KEYS:
        v = data.get(k)
        if k in ("products", "objections", "commitments"):
            if isinstance(v, str):
                v = [v] if v.strip() else []
            elif not isinstance(v, list):
                v = [v] if isinstance(v, (int, float)) and not isinstance(v, bool) else []
            v = [str(x).strip() for x in v if not isinstance(x, (dict, list)) and str(x).strip()][:8]
        elif isinstance(v, (dict, list)):
            v = None
        elif v is not None:
            v = str(v).strip() or None
        out[k] = v
    return out


async def analyse_call(transcript: str) -> tuple[str, dict | None]:
    """The post-call brief: (summary text, insights). Insights are what the sales
    team acts on — intent, products, objections, commitments, the next action and
    a ready follow-up message — kept only when the model returns them cleanly;
    otherwise the plain summary still lands (never a made-up field)."""
    from app.agent.runtime import build_llm
    llm = build_llm(model=settings.tier2_model_light, purpose="calls", cache=False)
    system = (
        "You analyse a phone call between a Bethany House sales agent and a "
        "customer (clergy apparel + communion supplies, Kenya). The transcript may "
        "be in Swahili, English, or a mix — understand all of it. Reply with ONE "
        "JSON object, English values, nothing else:\n"
        '{"summary": "4-7 short factual lines: who called, what they wanted, '
        'products/quantities/sizes, any KES price agreed, decisions",\n'
        ' "intent": "what the customer wants, one line",\n'
        ' "products": ["each product discussed, with size/qty if said"],\n'
        ' "objections": ["each concern or hesitation they raised"],\n'
        ' "commitments": ["each thing either side promised, with who and when"],\n'
        ' "next_action": "the single next step for the team, one line",\n'
        ' "follow_up_message": "a short, warm WhatsApp message the agent could '
        'send now to move the sale forward, in the customer\'s language",\n'
        ' "sentiment": "positive | neutral | negative"}\n'
        "Use [] or null for anything the call did not cover — never guess. If the "
        'transcript is empty or unintelligible, reply {"summary": "(No clear speech captured.)"}'
    )
    resp = await llm.complete(
        system=system,
        messages=[{"role": "user", "content": transcript[:12000]}],
        tools=[],
    )
    text = (resp.text or "").strip()
    data = _parse_insights(text)
    if data is None:
        return text, None
    summary = data.pop("summary", None) or ""
    insights = {k: v for k, v in data.items() if v not in (None, [], "")}
    return summary, (insights or None)


def _note_text(summary: str, insights: dict | None) -> str:
    """The CRM note: the summary, plus the next step when there is one."""
    nxt = (insights or {}).get("next_action")
    return f"{summary}\nNext: {nxt}" if nxt and nxt not in summary else summary


async def _publish_update(call_id: str) -> None:
    """Tell every open screen the call's brief is in (best-effort)."""
    try:
        import redis.asyncio as aioredis
        from app.services import call_log
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await call_log.publish_update(r, call_id)
        finally:
            await r.aclose()
    except Exception:
        pass


async def _save_call_note(db, wa_id: str, summary: str) -> None:
    """Persist the summary as a durable customer note keyed by phone number: it
    surfaces in the sidebar Notes (users.state['crm_notes']) AND feeds the agent's
    memory so Neema references the call on the next chat. Appends — never clobbers
    a manually-written note. Best-effort."""
    if not wa_id or not summary:
        return
    from datetime import datetime, timezone
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.user import User

    stamp = datetime.now(timezone.utc).strftime("%d %b %Y")
    entry = f"\U0001F4DE Call ({stamp}): {summary}"

    u = (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()
    if u is None:
        u = User(wa_id=wa_id, phone=wa_id)
        db.add(u)
        await db.flush()
    state = dict(u.state or {})
    prev = (state.get("crm_notes") or "").strip()
    state["crm_notes"] = f"{prev}\n\n{entry}".strip() if prev else entry
    u.state = state
    flag_modified(u, "state")
    await db.commit()

    # Feed the agent's durable memory too (kept short so it stays useful).
    try:
        from app.agent import memory as memorymod
        await memorymod.add_fact(db, wa_id, f"Phone call: {summary[:300]}", channel="whatsapp")
    except Exception:
        pass


async def _set_status(call_id: str, status: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c is not None:
                c.transcript_status = status
                await db.commit()
    except Exception:
        pass


async def _process(call_id: str) -> None:
    """Load a call's recording, transcribe, summarise, and persist. Runs detached
    with its own DB sessions; heavy inference happens outside any open transaction."""
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c is None or not c.recording_url:
                return
            path = _local_path(c.recording_url)
            wa_id = c.wa_id
            if not path:
                c.transcript_status = "failed"
                await db.commit()
                _log.warning("transcribe: recording file missing for %s", call_id)
                return
            c.transcript_status = "processing"
            await db.commit()
        await _publish_update(call_id)

        # Heavy, blocking work — off the event loop, outside any DB session.
        text, lang = await asyncio.to_thread(_transcribe_sync, path)
        await _finish(call_id, wa_id, text, lang)
    except Exception as exc:
        _log.warning("transcribe pipeline failed for %s: %s", call_id, exc)
        await _set_status(call_id, "failed")
        await _publish_update(call_id)


def _sane_brief(summary, insights) -> tuple[str, dict | None]:
    """Whatever the model handed back → (text, insights of the documented shape)."""
    summary = summary.strip()[:8000] if isinstance(summary, str) else ""
    if not isinstance(insights, dict):
        return summary, None
    clean: dict = {}
    for k in _INSIGHT_KEYS:
        v = insights.get(k)
        if k in ("products", "objections", "commitments"):
            v = [str(x).strip()[:300] for x in (v if isinstance(v, list) else [])
                 if isinstance(x, (str, int, float)) and str(x).strip()][:8]
        elif isinstance(v, (str, int, float)) and not isinstance(v, bool):
            v = str(v).strip()[:1000] or None
        else:
            v = None
        if v not in (None, []):
            clean[k] = v
    return summary, (clean or None)


async def _keep_transcript(call_id: str, text: str, lang: str | None, status: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c is not None:
                c.transcript = text or None
                c.transcript_lang = (lang or None) and str(lang)[:12]
                c.transcript_status = status
                await db.commit()
    except Exception as exc:
        _log.warning("transcribe: keeping the transcript failed for %s: %s", call_id, exc)


async def _finish(call_id: str, wa_id: str | None, text: str, lang: str | None) -> bool:
    """A transcript is in (ours or Meta's): summary + insights → the Call row →
    every screen → the customer's CRM note. True when the brief landed. When
    the AI is down (or answers nonsense it can't use) the transcript is still
    kept and the status is `failed` (Retry) — never a crash, never a made-up
    brief. Raises only when the database itself fails (callers mark it)."""
    text = text if isinstance(text, str) else ""
    try:
        summary, insights = await analyse_call(text) if text.strip() else ("", None)
        summary, insights = _sane_brief(summary, insights)
    except Exception as exc:
        _log.warning("transcribe: analysis failed for %s: %s", call_id, exc)
        await _keep_transcript(call_id, text, lang, "failed")
        await _publish_update(call_id)
        return False

    async with AsyncSessionLocal() as db:
        c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
        if c is None:
            return False
        c.transcript = text or None
        c.transcript_lang = (lang or None) and str(lang)[:12]
        c.summary = summary or None
        c.insights = insights
        c.transcript_status = "done"
        await db.commit()
    await _publish_update(call_id)

    if summary and wa_id:
        async with AsyncSessionLocal() as db:
            try:
                await _save_call_note(db, wa_id, _note_text(summary, insights))
            except Exception as exc:
                _log.warning("transcribe: saving call note failed for %s: %s", call_id, exc)
    return True


def schedule_transcription(call_id: str) -> None:
    """Fire-and-forget the transcription pipeline (keeps a strong ref so the task
    isn't garbage-collected mid-flight). No-op if Whisper isn't enabled."""
    if not settings.whisper_enabled:
        return
    task = asyncio.create_task(_process(call_id))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)



# ── Meta's own recording / transcription (opt-in, per call) ──────────────────
# Arrive on the `calls` webhook as `call_transcription_available` /
# `call_recording_available` with a media id. The download URL is valid for 5
# minutes, so the fetch starts at once (detached — the webhook never waits on
# it). A failure here only loses the artifact; the call is untouched.

SPEAKERS = {0: "Agent", 1: "Customer"}      # Meta: channel 0 = business, 1 = customer
_TEXT_KEYS = ("text", "transcript", "word")
_CHANNEL_KEYS = ("channel", "channel_id", "channel_index", "speaker")
_START_KEYS = ("start", "start_time", "start_ms", "offset")
_LANG_KEYS = ("language", "detected_language", "language_code")


def media_id_of(event: dict, kind: str) -> str | None:
    """The media id in a `call_*_available` event. The brief names the media id
    but not its field, so the likely homes are checked in order."""
    for key in (kind, "media", "recording", "transcription"):
        obj = event.get(key)
        if isinstance(obj, dict):
            for k in ("id", "media_id"):
                if obj.get(k):
                    return str(obj[k])
        elif isinstance(obj, str) and key == "media" and obj:
            return obj
    if event.get("media_id"):
        return str(event["media_id"])
    return None


def _find_lang(doc) -> str | None:
    if isinstance(doc, dict):
        for k in _LANG_KEYS:
            v = doc.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()[:12]
        for v in doc.values():
            if isinstance(v, (dict, list)):
                found = _find_lang(v)
                if found:
                    return found
    elif isinstance(doc, list):
        for v in doc:
            found = _find_lang(v)
            if found:
                return found
    return None


def _pieces(doc, out: list) -> None:
    """Every {channel, text} entry in the document, in document order."""
    if isinstance(doc, dict):
        ch = next((doc[k] for k in _CHANNEL_KEYS if k in doc), None)
        txt = next((doc[k] for k in _TEXT_KEYS if isinstance(doc.get(k), str)), None)
        if ch is not None and txt is not None:
            start = next((doc[k] for k in _START_KEYS if isinstance(doc.get(k), (int, float))), None)
            try:
                ch = int(ch)
            except (TypeError, ValueError):
                pass
            out.append((start, len(out), ch, txt.strip()))
            return
        for v in doc.values():
            if isinstance(v, (dict, list)):
                _pieces(v, out)
    elif isinstance(doc, list):
        for v in doc:
            _pieces(v, out)


def parse_meta_transcript(doc) -> tuple[str, str | None]:
    """Meta's transcript JSON → ("Agent: …\nCustomer: …", language). Tolerant:
    segments or words carrying a channel become speaker-labelled lines
    (consecutive pieces of one speaker are joined); a document with only a
    plain text field is used as it is."""
    lang = _find_lang(doc)
    found: list = []
    _pieces(doc, found)
    if found:
        if all(p[0] is not None for p in found):
            found.sort(key=lambda p: (p[0], p[1]))
        lines: list[list] = []
        for _, _, ch, txt in found:
            if not txt:
                continue
            who = SPEAKERS.get(ch, f"Speaker {ch}") if isinstance(ch, int) else str(ch)
            if lines and lines[-1][0] == who:
                lines[-1][1].append(txt)
            else:
                lines.append([who, [txt]])
        return "\n".join(f"{who}: {' '.join(parts)}" for who, parts in lines), lang
    if isinstance(doc, dict):
        for k in ("text", "transcript"):
            if isinstance(doc.get(k), str):
                return doc[k].strip(), lang
    return "", lang


async def ingest_meta_transcription(call_id: str, media_id: str) -> str:
    """Download Meta's transcript, store it speaker-labelled, then summary +
    insights + CRM note. Returns what happened (for logs / tests). Claimed on
    the row first (Meta may deliver the event twice, at once): one download,
    one analysis, one CRM note per call."""
    from app.services import wa_calling
    import json as _json
    async with AsyncSessionLocal() as db:
        c = (await db.execute(
            select(Call).where(Call.call_id == call_id).with_for_update())).scalar_one_or_none()
        if c is None:
            return "unknown_call"
        if c.transcript_status in ("processing", "done"):
            return "already"
        prev = c.transcript_status
        wa_id = c.wa_id
        c.transcript_status = "processing"
        await db.commit()
    try:
        raw, _mime = await wa_calling.download_media(media_id)
        doc = _json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    except Exception as exc:
        _log.warning("meta transcript download failed for %s: %s", call_id, exc)
        await _restore_status(call_id, prev)     # never touches the call
        return "download_failed"
    text, lang = parse_meta_transcript(doc)
    await _publish_update(call_id)
    try:
        ok = await _finish(call_id, wa_id, text, lang)
    except Exception as exc:
        _log.warning("meta transcript analysis failed for %s: %s", call_id, exc)
        await _keep_transcript(call_id, text, lang, "failed")
        await _publish_update(call_id)
        return "analysis_failed"
    return "done" if ok else "analysis_failed"


async def _restore_status(call_id: str, prev: str | None) -> None:
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(
                select(Call).where(Call.call_id == call_id).with_for_update())).scalar_one_or_none()
            if c is not None and c.transcript_status == "processing":
                c.transcript_status = prev or "none"
                await db.commit()
    except Exception:
        pass


async def ingest_meta_recording(call_id: str, media_id: str) -> str:
    """Keep Meta's recording as the call's recording — only when we don't
    already have our own (the softphone's upload wins)."""
    import os
    import uuid
    from app.services import wa_calling
    async with AsyncSessionLocal() as db:
        c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
        if c is None:
            return "unknown_call"
        if c.recording_url:
            return "already"
    try:
        content, _mime = await wa_calling.download_media(media_id)
    except Exception as exc:
        _log.warning("meta recording download failed for %s: %s", call_id, exc)
        return "download_failed"
    if not content:
        return "empty"
    from app.routers.media import MEDIA_DIR
    os.makedirs(MEDIA_DIR, exist_ok=True)
    name = f"call_meta_{uuid.uuid4().hex}.ogg"
    with open(os.path.join(MEDIA_DIR, name), "wb") as f:
        f.write(content)
    base = (getattr(settings, "media_public_url", "") or "").rstrip("/")
    url = f"{base}/api/admin/media/{name}" if base else name
    async with AsyncSessionLocal() as db:
        c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
        if c is None or c.recording_url:
            return "already"
        c.recording_url = url
        if (c.transcript_status or "none") == "none":
            c.transcript_status = "recorded"
        await db.commit()
    await _publish_update(call_id)
    return "done"


async def _meta_artifact(kind: str, call_id: str, event: dict) -> str:
    media_id = media_id_of(event, kind)
    if not media_id:
        _log.warning("meta %s event for %s carried no media id", kind, call_id)
        return "no_media"
    try:
        if kind == "transcription":
            return await ingest_meta_transcription(call_id, media_id)
        return await ingest_meta_recording(call_id, media_id)
    except Exception as exc:
        _log.warning("meta %s ingest failed for %s: %s", kind, call_id, exc)
        return "failed"


def schedule_meta_artifact(kind: str, call_id: str, event: dict) -> None:
    """Fetch Meta's transcript / recording now, detached from the webhook."""
    try:
        task = asyncio.get_running_loop().create_task(_meta_artifact(kind, call_id, event))
    except RuntimeError:
        return
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
