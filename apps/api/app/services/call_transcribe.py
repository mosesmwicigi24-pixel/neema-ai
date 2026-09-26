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
            v = [str(x).strip() for x in (v or []) if str(x).strip()][:8]
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
        summary, insights = await analyse_call(text) if text.strip() else ("", None)

        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c is None:
                return
            c.transcript = text or None
            c.transcript_lang = lang or None
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
    except Exception as exc:
        _log.warning("transcribe pipeline failed for %s: %s", call_id, exc)
        await _set_status(call_id, "failed")
        await _publish_update(call_id)


def schedule_transcription(call_id: str) -> None:
    """Fire-and-forget the transcription pipeline (keeps a strong ref so the task
    isn't garbage-collected mid-flight). No-op if Whisper isn't enabled."""
    if not settings.whisper_enabled:
        return
    task = asyncio.create_task(_process(call_id))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
