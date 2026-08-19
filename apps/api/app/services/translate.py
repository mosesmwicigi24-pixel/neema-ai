"""The team's reading glass — English under every foreign message, lazily.

The thread with Христина Маркова (2026-08-18) made the problem plain: she
writes Bulgarian, Neema answers — sometimes in Bulgarian — and the human
FOLLOWING the sale on the dashboard can read neither side. The owner asked for
a translated copy under each such message, in gray, so a person can track the
conversation.

Shape of the solution (built cost-first, a day after the spend probe):

  · LAZY — nothing translates at ingest. The agent doesn't need translations,
    and most threads are never opened by a human. Opening a thread is the
    trigger; the thread still loads instantly because translation runs as a
    background task and lands over the SAME websocket channel new messages
    ride, a beat later.
  · BOTH DIRECTIONS — Neema mirrors the customer's language, so her own
    replies are translated too. Following half a conversation is not following.
  · ONE CALL, NOT N — all missing messages in the opened thread go to the
    light model as one numbered batch (≈$0.001 for a whole thread).
  · CACHED FOREVER — the result is written onto the message row, so a thread
    is translated at most once in its life. Already-readable messages store a
    copy of their own text as the "nothing to do" marker and are never asked
    about again.
  · HEURISTICS FIRST — English and Swahili (both read by the team) are
    filtered out by word lists before any model sees them; non-Latin scripts
    (Cyrillic, Amharic, Chinese, Arabic…) are definite candidates; ambiguous
    Latin text (French, Spanish, Portuguese…) lets the model decide, which
    also cleanly handles bare names and emoji the lists can't judge.
  · BUDGET-AWARE — skips entirely at the daily stop, meters its (tiny) spend
    under node "translate", and cools down on failure instead of retrying on
    every open.

Dashboard-only by construction: the agent's history builder and every send
path read `Message.text`; nothing here is ever shown to a customer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from sqlalchemy import select

from app.core.config import settings

_log = logging.getLogger("neema.agent")

_BATCH_MAX = 30            # newest-first cap per thread-open; the rest next open
_LOCK_TTL = 90             # one worker per thread at a time
_COOLDOWN_TTL = 600        # after a failed/partial call: don't re-burn per open

# Words the team reads without help. Function words + the trade's vocabulary,
# lowercase. Deliberately compact: the lists only need to catch the OBVIOUS
# readable messages — anything ambiguous goes to the model, which answers
# "already readable" for free-ish and is cached forever.
_ENGLISH = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "i", "you", "we", "they", "he", "she", "it", "my", "your", "our", "me",
    "how", "what", "when", "where", "which", "who", "why", "much", "many",
    "can", "could", "will", "would", "please", "thanks", "thank", "hello",
    "hi", "good", "morning", "evening", "afternoon", "yes", "no", "not",
    "do", "does", "did", "have", "has", "need", "want", "like", "for", "to",
    "of", "in", "on", "with", "this", "that", "there", "here", "send", "me",
    "price", "cost", "order", "buy", "delivery", "deliver", "size", "color",
    "colour", "tray", "cup", "cups", "set", "church", "god", "bless", "amen",
    "pastor", "bishop", "sister", "brother", "ok", "okay", "sure", "still",
    "waiting", "get", "back", "pay", "payment", "available", "ready",
}
_SWAHILI = {
    "asante", "karibu", "habari", "mambo", "sasa", "poa", "sawa", "ndio",
    "hapana", "bei", "ngapi", "pesa", "gani", "nzuri", "mzuri", "sana",
    "mungu", "bwana", "yesu", "baraka", "mbarikiwe", "tafadhali", "pole",
    "leo", "kesho", "nataka", "nipe", "nipatie", "tuma", "lipa", "malipo",
    "mpesa", "iko", "ipo", "hii", "hiyo", "hebu", "niaje", "shukrani",
    "kanisa", "mchungaji", "askofu", "dada", "kaka", "nimeipata", "ngoja",
    "bado", "nita", "uko", "wapi", "namna", "kiasi", "jumla", "kikombe",
    "vikombe", "sinia", "rangi", "ukubwa", "ndogo", "kubwa",
}
_READABLE = _ENGLISH | _SWAHILI

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_WORD_RE = re.compile(r"[a-zA-ZÀ-ÖØ-öø-ÿ']+")


def _has_non_latin_letters(text: str) -> bool:
    """True when the text carries letters from a non-Latin script (Cyrillic,
    Greek, Arabic, Amharic, CJK, Devanagari…). Emoji and symbols are not
    letters and never count; Vietnamese's Latin Extended Additional does not
    count as foreign script (its words still fail the word lists and go to
    the model, which is the right arbiter)."""
    for ch in text:
        if not ch.isalpha():
            continue
        o = ord(ch)
        if o <= 0x024F or 0x1E00 <= o <= 0x1EFF:
            continue
        return True
    return False


def needs_translation(text: str | None) -> bool:
    """Should this text be OFFERED to the translator?

    False = definitely readable (or nothing to translate): pure
    English/Swahili by word-list, bracketed system placeholders, bare
    links/numbers/emoji. True = a non-Latin script, or Latin text the lists
    can't vouch for — the model then makes the final call and its
    "already readable" answer is cached so nothing is asked twice."""
    t = (text or "").strip()
    if not t or t.startswith("["):
        return False
    t = _URL_RE.sub(" ", t)
    if _has_non_latin_letters(t):
        return True
    words = [w.lower() for w in _WORD_RE.findall(t)]
    if not words:
        return False                       # emoji, digits, links — nothing to say
    hits = sum(1 for w in words if w in _READABLE)
    if len(words) <= 3:
        return hits < len(words)           # short: every word must vouch
    return hits / len(words) < 0.34


def _marker_suspect(text: str | None) -> bool:
    """Could a "readable as-is" verdict on this text be WRONG?

    Every candidate already failed the word-lists, so ambiguity is normal —
    a bare name ("Bruno Nion") legitimately draws the readable marker. But a
    non-Latin script, or a sentence of four-plus words in which the lists
    recognise nothing, is not a name: a readable-verdict there is the model
    stonewalling (the French thread of 2026-08-19), and trusting it froze
    eight rows untranslated forever."""
    t = (text or "").strip()
    if not t:
        return False
    if _has_non_latin_letters(t):
        return True
    return needs_translation(t) and len(_WORD_RE.findall(t)) >= 4


def is_candidate(m) -> bool:
    """Message-level filter shared by the thread endpoint and the worker."""
    stored = getattr(m, "translated_text", None)
    text = getattr(m, "text", None)
    if stored:
        # A REAL translation (differs from the original) is done forever. The
        # readable-marker (stored == original) is trusted except where the
        # verdict itself is suspect — a whole foreign sentence declared
        # readable is the 2026-08-19 poison (a French thread frozen
        # untranslated for good) — those are offered again. A marker on a
        # bare name stays done: churn there would burn a call per open.
        if (stored or "").strip() != (text or "").strip():
            return False
        if not _marker_suspect(text):
            return False
    if getattr(m, "media_type", None) == "note":
        return False                       # operator-private, already English
    return needs_translation(text)


def translation_for(m) -> str | None:
    """What the dashboard shows under the bubble — None when the stored value
    is the readable-marker copy of the original."""
    t = (getattr(m, "translated_text", None) or "").strip()
    if not t or t == (getattr(m, "text", None) or "").strip():
        return None
    return t


# ── the background worker ────────────────────────────────────────────────────

_tasks: set = set()


def schedule_thread_translation(redis, conv_id, message_ids: list[str]) -> bool:
    """Fire-and-forget fill for one opened thread. Returns True when a task
    was actually started."""
    if not settings.translate_for_team or not message_ids:
        return False
    task = asyncio.create_task(_translate_thread(redis, str(conv_id),
                                                 [str(i) for i in message_ids]))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


def _parse_items(raw: str) -> list[dict]:
    """The model is told to answer with bare JSON; tolerate a fenced block or
    stray prose around it rather than failing the whole batch."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    try:
        out = json.loads(s)
    except Exception:
        a, b = s.find("["), s.rfind("]")
        if a < 0 or b <= a:
            return []
        try:
            out = json.loads(s[a:b + 1])
        except Exception:
            return []
    return [x for x in out if isinstance(x, dict)] if isinstance(out, list) else []


_SYSTEM = (
    "You are a precise translator for a customer-service team. You receive a "
    "JSON array of chat messages: [{\"i\": <index>, \"t\": <text>}, …]. Reply "
    "with ONLY a JSON array, one object per input: {\"i\": <same index>, "
    "\"lang\": <English name of the source language>, \"en\": <faithful "
    "English translation>}. Rules: translate meaning faithfully — never "
    "summarise, never add, keep emojis and line breaks. Return an empty "
    "string for \"en\" ONLY when the message is English or Swahili, or is "
    "just a name, emoji or number with nothing to translate. EVERY other "
    "language — French, Portuguese, Spanish, Bulgarian, Indonesian, anything "
    "— MUST be translated; never echo the original text as the translation. "
    "No prose, no code fences — the JSON array only."
)


async def _translate_thread(redis, conv_id: str, ids: list[str]) -> int:
    """Translate up to _BATCH_MAX missing messages of one thread in a single
    light-model call, persist, then push the results over the conversation's
    websocket channel. Returns how many messages got a real translation."""
    from app.database import AsyncSessionLocal
    from app.models.message import Message

    try:
        if redis is not None:
            try:
                if await redis.get(f"translate:cool:{conv_id}"):
                    return 0
                if not await redis.set(f"translate:lock:{conv_id}", "1",
                                       nx=True, ex=_LOCK_TTL):
                    return 0
            except Exception:
                pass
            # Past the daily stop even this waits for midnight — the humans
            # still see the originals, and the next thread-open catches up.
            from app.services import ai_budget
            if await ai_budget.mode(redis) == "stop":
                return 0

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(Message).where(Message.id.in_(ids[:200]))
                .order_by(Message.created_at.desc()))).scalars().all()
            rows = [m for m in rows if is_candidate(m)][:_BATCH_MAX]
            if not rows:
                return 0

            payload = [{"i": i, "t": (m.text or "")[:1200]}
                       for i, m in enumerate(rows)]
            from app.agent.runtime import build_llm
            llm = build_llm(model=settings.tier2_model_light)
            resp = await llm.complete(
                system=_SYSTEM,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                tools=[])
            items = _parse_items(resp.text)

            refused = 0
            done: list[dict] = []
            for it in items:
                try:
                    idx = int(it.get("i"))
                except Exception:
                    continue
                if not 0 <= idx < len(rows):
                    continue
                m = rows[idx]
                en = (it.get("en") or "").strip()
                if not en or en == (m.text or "").strip():
                    # The model says "readable as-is". A bare name earns that;
                    # a foreign SENTENCE does not — and a verdict that names a
                    # foreign language while refusing to translate contradicts
                    # itself. Storing the marker on those froze rows
                    # untranslated forever (the French thread, 2026-08-19);
                    # leave them empty instead so a later pass retries.
                    said_lang = (str(it.get("lang") or "").strip().lower())
                    contradiction = said_lang not in ("", "english", "swahili")
                    if contradiction or _marker_suspect(m.text):
                        refused += 1
                        continue
                    m.translated_text = m.text
                    m.translated_from = None
                else:
                    m.translated_text = en
                    m.translated_from = (str(it.get("lang") or "").strip()[:24]
                                         or None)
                    done.append({"id": str(m.id), "text": en,
                                 "lang": m.translated_from})
            if items:
                await db.commit()
            if refused and not done and redis is not None:
                # The model refused a whole batch it should have translated —
                # cool down instead of burning a call on every thread-open.
                try:
                    await redis.set(f"translate:cool:{conv_id}", "1", ex=_COOLDOWN_TTL)
                except Exception:
                    pass
                _log.warning("translate: model refused %d foreign message(s) in %s",
                             refused, conv_id)

            # Meter the spend honestly (node "translate") and feed the breaker.
            try:
                u = resp.usage or {}
                from app.core.ai_pricing import estimate_cost_usd
                from app.services import ai_budget
                from app.services import n8n_bridge as svc
                totals = {k: int(u.get(k, 0) or 0) for k in
                          ("input_tokens", "output_tokens", "cache_read_tokens",
                           "cache_write_tokens", "cache_write_1h_tokens")}
                await ai_budget.add_spend(redis, estimate_cost_usd(
                    settings.tier2_model_light,
                    totals["input_tokens"] + totals["cache_read_tokens"]
                    + totals["cache_write_tokens"],
                    totals["output_tokens"], cached_tokens=totals["cache_read_tokens"],
                    cache_write_tokens=totals["cache_write_tokens"],
                    cache_write_1h_tokens=totals["cache_write_1h_tokens"]))
                await svc.log_agent_usage(db, None, settings.tier2_model_light,
                                          totals, node="translate")
            except Exception:
                pass

        # Live delivery: same channel new_message rides, so the gray lines
        # appear in the open thread a beat after it loads.
        if done and redis is not None:
            try:
                from app.services.n8n_bridge import _broadcast
                await _broadcast(redis, conv_id, {
                    "type": "translations", "conversationId": conv_id,
                    "items": done,
                })
            except Exception:
                pass

        # A partial answer means some rows stayed NULL — cool down so reopening
        # the thread doesn't re-buy the same misses every few seconds.
        if len(items) < len(rows) and redis is not None:
            try:
                await redis.set(f"translate:cool:{conv_id}", "1", ex=_COOLDOWN_TTL)
            except Exception:
                pass
        if done:
            _log.info("translated %d message(s) for thread %s", len(done), conv_id)
        return len(done)
    except Exception as exc:
        _log.warning("thread translation failed for %s: %s", conv_id, exc)
        if redis is not None:
            try:
                await redis.set(f"translate:cool:{conv_id}", "1", ex=_COOLDOWN_TTL)
            except Exception:
                pass
        return 0
    finally:
        if redis is not None:
            try:
                await redis.delete(f"translate:lock:{conv_id}")
            except Exception:
                pass


# ── The reply box's outbound direction (the "Samsung keyboard" toggle) ───────
# A human types English; what the customer receives is their own language. The
# thread stores what was actually SENT as `text` and the human's English as
# `translated_text` — so the reading-glass line under the bubble works in
# reverse automatically, and the record is honest about both.


async def target_language(db, conv_id) -> tuple[str | None, str | None]:
    """(language_name, sample_text) for a conversation — the language to
    translate the human's reply INTO. Prefers the thread's already-cached
    detections (free), else hands back the newest real inbound text as a
    sample for the model to match."""
    from app.models.message import Message, MsgDirection
    try:
        rows = (await db.execute(
            select(Message.translated_from, Message.text)
            .where(Message.conversation_id == conv_id,
                   Message.direction == MsgDirection.inbound)
            .order_by(Message.created_at.desc()).limit(12))).all()
    except Exception:
        return None, None
    sample = None
    for lang, text in rows:
        t = (text or "").strip()
        if lang:
            return lang, None
        if sample is None and t and not t.startswith("[") and needs_translation(t):
            sample = t[:400]
    return None, sample


async def translate_reply(db, redis, conv_id, text: str) -> dict:
    """Translate one human-typed reply into the customer's language.

    Returns {"text": <to-send>, "lang": <language name | None>}. Fails OPEN in
    every direction — budget stop, no detectable target, model hiccup — by
    returning the original English: a human's reply must never be blocked by
    the translator that exists to help it."""
    original = (text or "").strip()
    out = {"text": original, "lang": None}
    if not original or not settings.translate_for_team:
        return out
    try:
        from app.services import ai_budget
        if await ai_budget.mode(redis) == "stop":
            return out
        lang, sample = await target_language(db, conv_id)
        if not lang and not sample:
            return out                      # thread reads as English — nothing to do
        if lang and lang.strip().lower() in ("english", "swahili"):
            return out
        target = (f"into {lang}" if lang
                  else "into the language of this customer message: "
                       f"«{sample}»")
        system = (
            "You translate a customer-service reply for a church-supplies "
            "store. Translate the agent's message faithfully " + target + ". "
            "Warm, respectful register (Vous/Sie/formal you where the language "
            "distinguishes). Keep emojis, numbers, prices, product names and "
            "links EXACTLY as written. Reply with ONLY a JSON object: "
            "{\"lang\": <English name of the target language>, "
            "\"text\": <the translation>}. No prose, no code fences."
        )
        from app.agent.runtime import build_llm
        llm = build_llm(model=settings.tier2_model_light)
        resp = await llm.complete(system=system,
                                  messages=[{"role": "user", "content": original}],
                                  tools=[])
        s = (resp.text or "").strip()
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
        try:
            obj = json.loads(s)
        except Exception:
            a, b = s.find("{"), s.rfind("}")
            obj = json.loads(s[a:b + 1]) if 0 <= a < b else {}
        translated = (obj.get("text") or "").strip() if isinstance(obj, dict) else ""
        if translated:
            out = {"text": translated,
                   "lang": (str(obj.get("lang") or lang or "").strip()[:24] or None)}
        try:
            u = resp.usage or {}
            from app.core.ai_pricing import estimate_cost_usd
            from app.services import n8n_bridge as svc
            totals = {k: int(u.get(k, 0) or 0) for k in
                      ("input_tokens", "output_tokens", "cache_read_tokens",
                       "cache_write_tokens", "cache_write_1h_tokens")}
            await ai_budget.add_spend(redis, estimate_cost_usd(
                settings.tier2_model_light,
                totals["input_tokens"] + totals["cache_read_tokens"]
                + totals["cache_write_tokens"],
                totals["output_tokens"], cached_tokens=totals["cache_read_tokens"],
                cache_write_tokens=totals["cache_write_tokens"],
                cache_write_1h_tokens=totals["cache_write_1h_tokens"]))
            await svc.log_agent_usage(db, None, settings.tier2_model_light,
                                      totals, node="translate")
        except Exception:
            pass
        return out
    except Exception as exc:
        _log.warning("reply translation failed for %s: %s", conv_id, exc)
        return out
