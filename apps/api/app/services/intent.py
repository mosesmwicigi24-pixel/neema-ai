"""Deterministic customer-intent floor — the things that must never depend on
a model reading them right.

Stage 1 (audit, 2026-11-05) covers the OPT-OUT: "please stop messaging me" in
the languages our customers write. Today nothing in the system recognises it;
every unprompted path would carry on. The preference is durable — stored on
the person (`persons.state.contact_preferences`), mirrored in redis for the
hot path, and written to the Activity timeline so staff can see it.

Later stages add the richer states (comparing, consulting, waiting for the
team, asked for time) as a model-written note with this module as the floor.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

_log = logging.getLogger("neema.intent")

OPT_OUT_TTL = 365 * 86400

# Short, explicit refusals of contact. Deliberately conservative: a question
# ("can you stop by?") or a long message is never an opt-out, and "stop" alone
# needs the messaging object. Languages: English, Swahili, French, Spanish,
# Portuguese, German, Hindi (Devanagari and romanised).
_OPT_OUT_RE = re.compile(
    r"(?:"
    # English
    r"\b(?:please\s+)?(?:stop|quit|cease)\s+(?:sending|messaging|texting|contacting|writing)(?:\s+(?:me|us))?\b"
    r"|\b(?:stop|no more)\s+(?:these\s+|the\s+)?(?:messages|texts|sms|follow[- ]?ups?|reminders|notifications)\b"
    r"|\bdo(?:n'?t| not)\s+(?:message|text|contact|write to|call)\s+(?:me|us)\s+(?:again|anymore|any more)\b"
    r"|\b(?:unsubscribe|opt\s*out|remove\s+(?:me|my number)|take me off|leave me alone)\b"
    r"|\bnot interested\b.{0,30}\b(?:stop|don'?t)\b"
    # Swahili
    r"|\b(?:acha|wacha|usi)\w*\s+(?:kunitumia|kuni\w*\s+ujumbe|kunitext|kuniandikia|kunisumbua)\b"
    r"|\businitumie\s+(?:ujumbe|meseji|message)"
    r"|\bsitaki\s+(?:ujumbe|meseji|messages?)\b"
    # French
    r"|\b(?:arr[êe]tez|arrete[sz]?|cessez)\s+de\s+(?:m'?[ée]crire|m'?envoyer|me\s+contacter|me\s+relancer)\b"
    r"|\bne\s+(?:m'?[ée]crivez|me\s+contactez|m'?envoyez)\s+plus\b"
    r"|\bd[ée]sabonne"
    # Spanish / Portuguese
    r"|\bno\s+me\s+(?:escrib|envíe|envie|mande|contacte)\w*\s+m[áa]s\b"
    r"|\bdeje[n]?\s+de\s+(?:escribirme|enviarme|contactarme)\b"
    r"|\bpare[m]?\s+de\s+(?:me\s+)?(?:mandar|enviar|escrever)\b"
    r"|\bn[ãa]o\s+me\s+(?:mande|envie|escreva)\s+mais\b"
    # German
    r"|\b(?:h[öo]r(?:en)?\s+(?:sie\s+)?auf|bitte\s+keine)\b.{0,20}\b(?:nachrichten|schreiben|kontaktieren)\b"
    r"|\bkeine\s+(?:weiteren\s+)?nachrichten\s+mehr\b"
    # Hindi (Devanagari + romanised)
    r"|मुझे\s+(?:मैसेज|संदेश|मेसेज)\s+(?:मत|न)\s+(?:भेजें|भेजो|करें|करो)"
    r"|(?:मैसेज|संदेश)\s+(?:भेजना\s+)?बंद\s+(?:करें|करो|कीजिए)"
    r"|\b(?:mujhe\s+)?(?:message|msg|sandesh)\s+(?:mat|na)\s+(?:bhej|kar)\w*"
    r"|\b(?:message|msg)\s+bhejna\s+band\s+kar\w*"
    r")",
    re.IGNORECASE)
_QUESTION_RE = re.compile(r"\?")


def is_opt_out(text: str | None) -> bool:
    """True when this customer message clearly asks us to stop messaging."""
    t = " ".join((text or "").split())
    if not t or len(t) > 240 or _QUESTION_RE.search(t):
        return False
    return bool(_OPT_OUT_RE.search(t))


# ── the durable record ───────────────────────────────────────────────────────

def _key(channel: str, key: str) -> str:
    return f"agent:optout:{channel}:{key}"


def preferences(person) -> dict:
    state = getattr(person, "state", None) or {}
    prefs = state.get("contact_preferences") if isinstance(state, dict) else None
    return dict(prefs) if isinstance(prefs, dict) else {}


async def record_opt_out(db, redis, conv, text: str, *, channel: str, key: str) -> None:
    """Write the preference everywhere it is read: the person's state (durable),
    the Activity timeline (visible), redis (fast path)."""
    from sqlalchemy.orm.attributes import flag_modified
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        pid = getattr(conv, "person_id", None)
        if pid is not None:
            from app.models.person import Person
            person = await db.get(Person, pid)
            if person is not None:
                state = dict(person.state or {})
                prefs = dict(state.get("contact_preferences") or {})
                prefs["opt_out"] = {"at": now, "channel": channel, "said": text[:160]}
                state["contact_preferences"] = prefs
                person.state = state
                try:
                    flag_modified(person, "state")
                except Exception:
                    pass
        if getattr(conv, "id", None) is not None:
            from app.models.intercept import Intercept, InterceptAction
            db.add(Intercept(conversation_id=conv.id, action=InterceptAction.flag,
                             note="🔕 Customer asked not to be messaged — no automated "
                                  "outreach from now on; replies to their own messages only."))
        await db.commit()
    except Exception as exc:
        _log.warning("opt-out not persisted for %s/%s: %s", channel, key[-4:], exc)
        try:
            await db.rollback()
        except Exception:
            pass
    if redis is not None:
        try:
            await redis.set(_key(channel, key), now, ex=OPT_OUT_TTL)
        except Exception:
            pass


async def opted_out(db, redis, conv) -> bool:
    """Has this customer asked us not to message them? Redis first (fast),
    then the person's durable preference (re-warming redis)."""
    channel = getattr(conv, "channel", None) or "whatsapp"
    key = conv.wa_id if channel == "whatsapp" else getattr(conv, "external_id", None)
    if redis is not None and key:
        try:
            if await redis.get(_key(channel, key)):
                return True
        except Exception:
            pass
    pid = getattr(conv, "person_id", None)
    if pid is None or db is None:
        return False
    try:
        from app.models.person import Person
        person = await db.get(Person, pid)
    except Exception:
        return False
    if person is None or not preferences(person).get("opt_out"):
        return False
    if redis is not None and key:
        try:
            await redis.set(_key(channel, key), "1", ex=OPT_OUT_TTL)
        except Exception:
            pass
    return True


def acknowledgement(text: str) -> str:
    """One short line in their language, then silence."""
    from app.agent.voice import looks_swahili
    t = (text or "").lower()
    if looks_swahili(text) or re.search(r"\b(acha|wacha|usinitumie|sitaki)\b", t):
        return "Sawa, tumeelewa — hatutakutumia ujumbe tena. Tuko hapa wakati wowote utakapotuhitaji."
    if re.search(r"\b(arr[êe]te|cessez|écri|ecri|contacter|désabonn)", t):
        return "Entendu — nous ne vous écrirons plus. Nous restons à votre disposition si besoin."
    if re.search(r"[ऀ-ॿ]", text or ""):
        return "ठीक है — हम आपको और संदेश नहीं भेजेंगे। ज़रूरत हो तो हम यहीं हैं।"
    return "Understood — we won't message you again. We're here whenever you need us."


def log_line(prefix: str, channel: str, key: str, **facts) -> str:
    """A log line with the contact masked (never a whole number in logs)."""
    masked = f"…{str(key)[-4:]}" if key else "…"
    return f"{prefix} {channel}/{masked} " + json.dumps(facts, ensure_ascii=False, default=str)
