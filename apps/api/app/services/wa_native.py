"""Native WhatsApp ingestion — everything n8n's Tier 1 pipeline did, in-process.

Gated by settings.whatsapp_native (default OFF): the front door keeps forwarding
to n8n untouched until the flag is flipped, so cutover is one env var and
rollback is flipping it back.

What this replaces, and with what:
  · n8n webhook receive + parse       → parse_events() on the raw payload the
                                        front door ALREADY receives first
  · message persistence (/api/n8n/message)
                                      → the SAME svc.upsert_message() n8n calls —
                                        conversation upsert, provision_user (name
                                        + country), previews, broadcasts, and the
                                        selective video/document escalation are
                                        byte-for-byte identical
  · debounce-buffer workflow          → a redis token buffer: rapid-fire messages
                                        are combined for WHATSAPP_DEBOUNCE_SECONDS
                                        and answered ONCE
  · /profile → should_run_ai → reply  → reconcile_waref + runtime.schedule_reply
                                        directly (pause + dedup guards included)
  · voice-note transcription (OpenAI via n8n)
                                      → call_transcribe's provider dispatch
                                        (faster-whisper when installed, OpenAI
                                        whisper-1 fallback when a key exists)
  · product-image recognition (GPT-4o sub-workflow)
                                      → nothing: Claude vision reads the image
                                        NATIVELY in run_turn — the captioner was
                                        already redundant spend
  · TTS audio replies                 → DEFERRED (deliberate): voice notes get a
                                        text reply. Revisit if customers miss it.

The wamid lands on the Message row through the existing front-door redis tap that
upsert_message already recovers — native replies can quote customer messages.
"""
from __future__ import annotations

import asyncio
import logging
import os

from app.core.config import settings

_log = logging.getLogger("neema.wa_native")

_bg_tasks: set = set()

# ── Parsing ──────────────────────────────────────────────────────────────────


def _text_of(msg: dict) -> str:
    """The customer-visible text of one webhook message, whatever its type."""
    t = msg.get("type")
    if t == "text":
        return ((msg.get("text") or {}).get("body") or "").strip()
    if t == "button":
        return ((msg.get("button") or {}).get("text") or "").strip()
    if t == "interactive":
        i = msg.get("interactive") or {}
        for k in ("button_reply", "list_reply"):
            if i.get(k):
                return (i[k].get("title") or "").strip()
        return ""
    if t == "location":
        loc = msg.get("location") or {}
        parts = [p for p in (loc.get("name"), loc.get("address")) if p]
        coords = f"{loc.get('latitude')},{loc.get('longitude')}"
        return "📍 Location: " + (", ".join(parts) + f" ({coords})" if parts else coords)
    if t == "contacts":
        names = [((c.get("name") or {}).get("formatted_name") or "")
                 for c in (msg.get("contacts") or [])]
        return "👤 Shared contact: " + ", ".join(n for n in names if n)
    # media types carry their text as a caption
    media = msg.get(t) or {}
    return (media.get("caption") or "").strip()


def parse_events(payload: dict) -> list[dict]:
    """Flatten a Cloud API webhook payload into inbound message events.

    Statuses (sent/delivered/read receipts) are deliberately dropped — nothing in
    the system consumes them today (parity with the n8n flow)."""
    out: list[dict] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            names = {c.get("wa_id"): ((c.get("profile") or {}).get("name") or None)
                     for c in value.get("contacts", []) or []}
            for msg in value.get("messages", []) or []:
                wa_id = (msg.get("from") or "").strip()
                wamid = msg.get("id")
                if not wa_id or not wamid:
                    continue
                mtype = msg.get("type")
                media = None
                if mtype in ("image", "audio", "video", "document", "sticker"):
                    m = msg.get(mtype) or {}
                    media = {"kind": "image" if mtype == "sticker" else mtype,
                             "media_id": m.get("id"),
                             "mime_type": m.get("mime_type"),
                             "filename": m.get("filename"),
                             "caption": (m.get("caption") or "").strip() or None}
                try:
                    ts_ms = int(msg.get("timestamp", "0")) * 1000
                except (TypeError, ValueError):
                    ts_ms = None
                out.append({"wa_id": wa_id, "wamid": wamid,
                            "name": names.get(wa_id), "type": mtype,
                            "text": _text_of(msg), "media": media, "ts_ms": ts_ms})
    return out


# ── Media: download from the Graph, rehost, transcribe ───────────────────────


async def download_media(media_id: str) -> tuple[str | None, str | None]:
    """(public_url, local_path) for a WhatsApp media id — fetched from the Graph
    with the WABA token and rehosted in our served media dir (Meta's CDN links
    expire). None on any failure; the message still lands, just without media."""
    import httpx
    import mimetypes
    if not media_id or not settings.waba_token:
        return None, None
    try:
        base = f"https://graph.facebook.com/{settings.waba_api_version}"
        headers = {"Authorization": f"Bearer {settings.waba_token}"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            meta = await client.get(f"{base}/{media_id}", headers=headers)
            if not meta.is_success:
                _log.warning("media meta %s → %s", media_id, meta.status_code)
                return None, None
            info = meta.json()
            blob = await client.get(info.get("url", ""), headers=headers)
            if not blob.is_success or not blob.content:
                _log.warning("media fetch %s → %s", media_id, blob.status_code)
                return None, None
        from app.routers.media import MEDIA_DIR
        os.makedirs(MEDIA_DIR, exist_ok=True)
        ext = mimetypes.guess_extension((info.get("mime_type") or "").split(";")[0]) or ""
        name = f"wa_{media_id}{ext}"
        path = os.path.join(MEDIA_DIR, name)
        import aiofiles
        async with aiofiles.open(path, "wb") as f:
            await f.write(blob.content)
        public = (settings.media_public_url or "").rstrip("/")
        return (f"{public}/api/admin/media/{name}" if public else name), path
    except Exception as exc:
        _log.warning("media download failed for %s: %s", media_id, exc)
        return None, None


def _transcribe_path_sync(path: str) -> str | None:
    """Transcribe a voice note. Tries the configured whisper provider first
    (faster-whisper when installed = free + private), then falls back to OpenAI
    whisper-1 when a key exists — the same engine the n8n flow used, so cutover
    never LOSES transcription. None when neither works."""
    from app.services import call_transcribe as ct
    try:
        text, _lang = ct._transcribe_sync(path)
        return (text or "").strip() or None
    except Exception:
        pass
    if settings.openai_api_key:
        try:
            text, _lang = ct._transcribe_openai(path)
            return (text or "").strip() or None
        except Exception as exc:
            _log.warning("openai transcription failed: %s", exc)
    return None


async def transcribe_voice_note(path: str | None) -> str | None:
    if not path:
        return None
    return await asyncio.to_thread(_transcribe_path_sync, path)


# ── Debounce: rapid-fire messages get ONE considered reply ───────────────────


def _buf_key(wa_id: str) -> str:
    return f"wa:native:buf:{wa_id}"


def _tok_key(wa_id: str) -> str:
    return f"wa:native:tok:{wa_id}"


async def _enqueue(redis, wa_id: str, text: str, media: dict | None) -> int | None:
    """Buffer one message and bump the debounce token. Returns the token, or None
    when redis is down (caller then replies immediately — no debounce, no loss)."""
    if redis is None:
        return None
    import json
    try:
        await redis.rpush(_buf_key(wa_id), json.dumps({"text": text, "media": media}))
        await redis.expire(_buf_key(wa_id), 600)
        tok = await redis.incr(_tok_key(wa_id))
        await redis.expire(_tok_key(wa_id), 600)
        return int(tok)
    except Exception:
        return None


async def _drain(redis, wa_id: str, token: int) -> tuple[str, dict | None] | None:
    """The combined buffered turn — or None when a newer message superseded this
    flush (its own flush will carry the whole buffer)."""
    import json
    try:
        current = await redis.get(_tok_key(wa_id))
        if current is None or int(current) != token:
            return None
        raw = await redis.lrange(_buf_key(wa_id), 0, -1)
        await redis.delete(_buf_key(wa_id))
    except Exception:
        return None
    texts, media = [], None
    for r in raw:
        try:
            item = json.loads(r)
        except Exception:
            continue
        if (item.get("text") or "").strip():
            texts.append(item["text"].strip())
        # Prefer an image so the agent SEES what they sent; else keep the latest.
        if item.get("media") and (media is None or item["media"].get("type") == "image"):
            media = item["media"]
    return "\n".join(texts), media


def _is_doc_request(text: str | None) -> bool:
    """The customer wants a FILE we can't auto-produce (a PDF, a brochure, a
    price list…) — a human sends those. Ports the n8n media-request detector's
    document half (incl. its Swahili terms); PHOTO requests are NOT matched here
    because Neema now sends product-photo cards herself."""
    import re
    low = (text or "").lower()
    if not low:
        return False
    doc_words = ("pdf", "catalogue", "catalog", "brochure", "flyer", "lookbook",
                 "price list", "pricelist", "document", "invoice", "quotation",
                 "katalogi", "brosha")
    if not any(w in low for w in doc_words):
        return False
    # Only when they're ASKING for it, not merely mentioning it.
    return bool(re.search(
        r"(send|share|attach|forward|drop|give|email|whatsapp|nitumie|tuma|need|want|have)",
        low))


async def _escalate_doc_request(redis, wa_id: str, text: str) -> None:
    """Flip the conversation to a human with a visible reason — the same outcome
    the n8n media-escalation branch produced via POST /api/n8n/escalate."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation, InterceptMode
    from app.models.intercept import Intercept, InterceptAction

    async with AsyncSessionLocal() as db:
        conv = (await db.execute(select(Conversation).where(
            Conversation.wa_id == wa_id))).scalar_one_or_none()
        if conv is None or conv.intercept_mode == InterceptMode.human:
            return
        conv.intercept_mode = InterceptMode.human
        conv.assigned_agent_id = None
        conv.intercept_since = datetime.now(timezone.utc)
        reason = "Customer requested a document/file — a human should send it"
        db.add(Intercept(conversation_id=conv.id, agent_id=None,
                         action=InterceptAction.intercept, note=reason))
        await db.commit()
        conv_id = str(conv.id)
    if redis is not None:
        import json as _json
        try:
            await redis.publish("ws:channel:agents:all", _json.dumps({
                "event": "notification", "type": "media_escalation",
                "title": "📎 Media Request",
                "body": f"📎 {text[:120]} — conversation is ready for pickup",
                "wa_id": wa_id, "conv_id": conv_id}))
            await redis.publish(f"ws:channel:{conv_id}", _json.dumps({
                "type": "intercept_changed", "conversationId": conv_id,
                "mode": "human", "assignedAgentId": None,
                "eventKind": "intercept",
                "eventReason": "Customer requested a document/file"}))
        except Exception:
            pass
    _log.info("native: %s asked for a document — escalated to human", wa_id)


async def _reply_after_debounce(redis, wa_id: str, token: int | None,
                                text: str, media: dict | None) -> None:
    """Wait out the debounce window, then answer the COMBINED turn once."""
    from app.agent import runtime
    from app.database import AsyncSessionLocal

    if token is not None:
        await asyncio.sleep(max(settings.whatsapp_debounce_seconds, 1))
        drained = await _drain(redis, wa_id, token)
        if drained is None:
            return                            # superseded — a later flush owns it
        text, media = drained
    if not (text or media):
        return

    # A request for a FILE (pdf/brochure/price list) goes to a human — Neema can
    # send product photos herself, but not produce documents.
    if media is None and _is_doc_request(text):
        await _escalate_doc_request(redis, wa_id, text)
        return

    # A human has this conversation → the AI stays silent (parity with /profile).
    try:
        from sqlalchemy import select
        from app.models.conversation import Conversation, InterceptMode
        async with AsyncSessionLocal() as db:
            conv = (await db.execute(select(Conversation).where(
                Conversation.wa_id == wa_id))).scalar_one_or_none()
            if conv is not None and conv.intercept_mode == InterceptMode.human:
                _log.info("native: %s is human-handled — not replying", wa_id)
                return
            # Cross-channel bridge: a wa.me deep-link ref in the text links this
            # number to the social contact + rebuilds their cart (parity).
            try:
                from app.services.identity import reconcile_waref
                await reconcile_waref(db, redis, wa_id, text)
            except Exception:
                pass
    except Exception as exc:
        _log.warning("native pre-reply checks failed for %s: %s", wa_id, exc)

    dedup = f"native:{wa_id}:{token if token is not None else text[:32]}"
    await runtime.schedule_reply(redis, wa_id, text, dedup, media=media)


# ── Entry point ──────────────────────────────────────────────────────────────


async def _ingest_one(event: dict, redis) -> None:
    from app.database import AsyncSessionLocal
    from app.schemas.n8n import MessageDto
    from app.services import n8n_bridge as svc

    wa_id, wamid = event["wa_id"], event["wamid"]
    # Idempotency: Meta retries webhooks — each wamid is processed once.
    if redis is not None:
        try:
            if not await redis.set(f"wa:native:seen:{wamid}", "1", nx=True, ex=24 * 3600):
                return
        except Exception:
            pass

    text = event.get("text") or ""
    media = event.get("media")
    media_url, media_path, transcript = None, None, None
    if media and media.get("media_id"):
        media_url, media_path = await download_media(media["media_id"])
        if media["kind"] == "audio":
            transcript = await transcribe_voice_note(media_path)
            if transcript:
                text = transcript            # the voice note IS the message

    dto = MessageDto(
        wa_id=wa_id, name=event.get("name"), direction="inbound",
        text=text, ts_ms=event.get("ts_ms"), docid=wamid,
        media_type=(media or {}).get("kind"), media_url=media_url,
        media_id=(media or {}).get("media_id"),
        media_caption=(media or {}).get("caption") or (transcript if media else None),
        mime_type=(media or {}).get("mime_type"),
        filename=(media or {}).get("filename"),
    )
    async with AsyncSessionLocal() as db:
        # Genuinely first contact? (The n8n version of this notification fired on
        # EVERY text — its condition could never be false. This is the correct one.)
        from sqlalchemy import select
        from app.models.conversation import Conversation
        is_new = (await db.execute(select(Conversation.id).where(
            Conversation.wa_id == svc._normalize_wa_id(wa_id)))).scalar_one_or_none() is None
        # The SAME persistence n8n used: conversation upsert, provision_user
        # (name + country), previews, broadcast, video/document escalation.
        await svc.upsert_message(db, redis, dto)
    if is_new and redis is not None:
        import json as _json
        try:
            await redis.publish("ws:channel:agents:all", _json.dumps({
                "event": "notification", "type": "new_conversation",
                "title": f"New chat from {event.get('name') or wa_id}",
                "body": (text or f"[{(media or {}).get('kind', 'message')}]")[:160],
                "wa_id": wa_id}))
        except Exception:
            pass

    # What the agent should respond to for THIS message.
    turn_media = None
    if media and media["kind"] == "image" and media_url:
        turn_media = {"type": "image", "url": media_url,
                      "caption": media.get("caption") or ""}
    turn_text = text
    if not turn_text and media and not turn_media:
        turn_text = media.get("caption") or f"(the customer sent a {media['kind']})"

    token = await _enqueue(redis, wa_id, turn_text, turn_media)
    task = asyncio.create_task(
        _reply_after_debounce(redis, wa_id, token, turn_text, turn_media))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def handle_webhook(payload: dict, redis) -> int:
    """Process one raw webhook payload natively. Returns how many inbound
    messages were ingested. Never raises — the front door must always ack."""
    n = 0
    try:
        for event in parse_events(payload):
            try:
                await _ingest_one(event, redis)
                n += 1
            except Exception as exc:
                _log.exception("native ingest failed for %s: %s", event.get("wamid"), exc)
    except Exception as exc:
        _log.exception("native webhook handling failed: %s", exc)
    return n
