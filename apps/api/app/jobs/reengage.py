"""Re-engagement sweep: ONE fresh check-in for a customer who went quiet on us.

WHAT WENT WRONG (preview, 2026-10-10). The sweep used to pick threads whose
LAST message was the customer's and re-run the live reply turn on that
message (the agent loop with user_text=<their last message>, full history,
full tools). That is not a check-in — it is the interrupted turn played
again: the model wrote the NEXT line of an exchange that had stopped,
usually on purpose (a closer Neema chose not to answer, a reply held for
approval, a thread a colleague was checking). Out came "Thank you for your
patience.", "I'm confirming the blue and red chasubles with our team now —
they'll have the answer for you here in a moment…" and a fresh currency
conversion ending "Shall I place the order now?". On Meta those threads are
the missed-reply sweeper's (services/reply_sweeper.py) anyway.

WHAT IT DOES NOW. It picks the OTHER kind of thread — we spoke last, the
customer went quiet — and composes a fresh check-in from the transcript:
greet them by name, name what they were interested in (items and prices
only as already quoted in the thread), one question that moves toward the
order, short, in the thread's language (English / Swahili / French). The
model is called with NO tools and the transcript as quoted text, so it
cannot continue a turn, search, convert or create anything.

A QUALITY GATE stands before every send: a draft that thanks them for
waiting, promises a colleague is checking, continues an interrupted reply,
names a figure not already in the thread, does not name an item from the
thread, has no question, or is in the wrong language is REFUSED — skipped
and logged. Skipping beats sending nonsense.

Left alone (one sweep per thread, never two):
  · an unanswered customer message — the live path / missed-reply sweeper
    owns it (this sweep only takes threads whose newest turn is OURS);
  · human mode, closed threads, a colleague's last word, a hand-off line;
  · a cart with items (cart_recovery's), an order in the last 24 h
    (payment_followup's), a planned follow-up (the actions pipeline's);
  · paced / paused / guard-silenced contacts; comment threads; web chat;
  · outside the 24 h window (measured from the CUSTOMER's last message,
    with an hour's margin) and outside quiet hours (08:00–20:00 Nairobi).
Once per customer message: a Redis guard on their last inbound message id.

Manual by default; the daily timer (services/recovery_jobs.py) runs it only
when RECOVERY_REENGAGE_ENABLED is switched on — an outbound campaign is an
explicit owner decision. The CLI defaults to a dry run; pass --send to send:

    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.reengage            # preview only
    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.reengage --send     # SEND live
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.database import AsyncSessionLocal
# Import the FULL model set so SQLAlchemy's mapper registry is complete before we
# compile any query. Conversation.relationship("Agent"/"Intercept"/"Message") and
# the person spine must all be registered, or configuring the Conversation mapper
# raises `failed to locate a name ('Agent')`. The app's startup imports these via
# main; a standalone job must do it explicitly.
import app.models.agent      # noqa: F401
import app.models.agent_action  # noqa: F401
import app.models.intercept  # noqa: F401
import app.models.order_event  # noqa: F401
import app.models.person     # noqa: F401
import app.models.user       # noqa: F401
from app.models.conversation import Conversation, ConvStatus, InterceptMode
from app.models.message import Message, MsgDirection, MsgSender

_log = logging.getLogger("neema.reengage")

CHANNELS = ("whatsapp", "messenger", "instagram")
WINDOW_HOURS = 24
WINDOW_MARGIN_HOURS = 1        # never land in the window's last hour
MIN_IDLE_HOURS = 3             # give them room to come back on their own first
QUIET_START, QUIET_END = 8, 20
TRANSCRIPT_TURNS = 16
MAX_CHARS = 400
_GUARD_TTL = 7 * 24 * 3600     # one check-in per customer message, kept a week


def _nairobi_hour(now: datetime | None = None) -> int:
    return ((now or datetime.now(timezone.utc)) + timedelta(hours=3)).hour


def within_quiet_hours(now: datetime | None = None) -> bool:
    return QUIET_START <= _nairobi_hour(now) < QUIET_END


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── what a thread says ───────────────────────────────────────────────────────

# Our last line handed the customer to a person, held them ("thank you for
# waiting … in a moment"), or is the outage welcome — a check-in on top of it
# talks over the colleague or the answer that is meant to come.
_HANDOFF_RE = re.compile(
    r"\bcolleague|\bour team (?:will|is|are|has)\b|\bteam member\b|\bsomeone (?:will|from)\b"
    r"|\bget back to you\b|\bhand(?:ed|ing)? (?:you )?over\b|\bconnect you (?:with|to)\b"
    r"|\b(?:checking|confirming|verifying)\b[^.?!]{0,80}\bwith (?:our|the) team\b"
    r"|\bthank(?:s| you)? for (?:your )?(?:patience|waiting)\b|\bin a moment\b"
    r"|\bwelcome to bethany house\b|\bmwenzangu\b|\btimu yetu\b|\bun collègue\b|\bnotre équipe\b",
    re.IGNORECASE)


def is_handoff_line(text: str | None) -> bool:
    return bool(_HANDOFF_RE.search(text or ""))


_FR_WORDS = frozenset("""
bonjour bonsoir merci je vous votre vos est combien prix avec pour voulez souhaitez
commande oui nous les des une sur c'est j'ai s'il plaît voudrais aimerais coûte
""".split())


def looks_french(text: str | None) -> bool:
    toks = set(re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", (text or "").lower()))
    return len(toks & _FR_WORDS) >= 2


def thread_language(inbound_texts: list[str]) -> str:
    """'sw' | 'fr' | 'en' — the language of the customer's own latest words
    that can be placed (newest first, up to five); English when none can."""
    from app.agent.voice import looks_swahili
    for t in list(reversed(inbound_texts))[:5]:
        if looks_swahili(t):
            return "sw"
        if looks_french(t):
            return "fr"
    return "en"


# ── the quality gate ─────────────────────────────────────────────────────────

# Lines that continue an interrupted reply, thank them for waiting, promise a
# colleague, or price something anew. Any one of them → refuse.
_BAD_RE = re.compile(
    r"\bthank(?:s| you)?\s+(?:you\s+)?(?:so much\s+)?for\s+(?:your\s+)?(?:patience|waiting|holding)"
    r"|\bfor waiting\b|\bbear with\b|\bpatience\b"
    r"|\b(?:i'?m|i am|we'?re|we are)\s+(?:now\s+|still\s+)?(?:checking|confirming|verifying)\b"
    r"|\blet me (?:check|confirm|find out)\b|\bcolleague|\b(?:our|the) team (?:will|is|are|has)\b"
    r"|\bget back to you\b|\bin a moment\b|\bone moment\b|\bshortly\b|\bright back\b"
    r"|\btoday'?s rate\b|\bexchange rate\b|\bcurrent rate\b|\bis about\b"
    r"|\basante kwa (?:kusubiri|uvumilivu)\b|\bsubiri kidogo\b|\bmwenzangu\b|\btimu yetu\b"
    r"|\bmerci (?:de|pour) (?:votre )?(?:patience|attente)\b|\bun instant\b|\bnotre équipe\b",
    re.IGNORECASE)
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_GENERIC_ITEMS = frozenset({"order", "orders", "item", "items", "it", "them", "this", "that",
                            "one", "product", "products", "price", "oda", "bidhaa", "commande"})


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM_RE.findall(text or ""):
        n = m.replace(",", "").rstrip(".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def _norm(text: str) -> str:
    """Lower-case words only: "Cope — Complete Set" and "cope - complete set"
    are the same item; punctuation and dashes never decide a match."""
    return " ".join(re.sub(r"[^\w]+", " ", (text or "").lower()).split())


def quality_gate(text: str, item: str | list[str], *, transcript: list[tuple[str, str]],
                 name: str | None, language: str) -> str | None:
    """None when this check-in may go; otherwise why it is refused. `item` is
    the item (or items) the draft says it names: at least one must appear in
    the thread AND in the draft."""
    from app.agent.voice import looks_swahili
    t = (text or "").strip()
    if not t:
        return "empty draft"
    if len(t) > MAX_CHARS:
        return "too long"
    if _BAD_RE.search(t):
        return "continues a turn / thanks for waiting / promises a colleague / new price"
    if t[0].islower() or t.startswith(("…", "...", "-", "—")):
        return "reads as the middle of a reply"
    nt = _norm(t)
    for role, said in transcript:
        if role != "customer" and (nt in _norm(said) or nt[:40] == _norm(said)[:40]):
            return "replays an earlier line"
    thread = f" {_norm(' '.join(x for _, x in transcript))} "
    named = False
    for cand in ([item] if isinstance(item, str) else list(item or [])):
        it = _norm(cand)
        if len(it) >= 3 and it not in _GENERIC_ITEMS \
                and f" {it} " in thread and f" {it} " in f" {nt} ":
            named = True
            break
    if not named:
        return "names no item from the thread"
    new_figures = _numbers(t) - _numbers(" ".join(x for _, x in transcript))
    if new_figures:
        return "a figure not already in the thread"
    if "?" not in t:
        return "asks no question"
    if name and name.lower() not in t.lower():
        return "does not greet them by name"
    sw, fr = looks_swahili(t), looks_french(t)
    if language == "sw" and not sw:
        return "not in the thread's language (Swahili)"
    if language == "fr" and not fr:
        return "not in the thread's language (French)"
    if language == "en" and (sw or fr):
        return "not in the thread's language (English)"
    return None


def parse_draft(raw: str | None) -> tuple[list[str], str] | None:
    """(items, text) from the model's JSON answer; None when it skipped or the
    answer cannot be read."""
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("skip"):
        return None
    raw_items = data.get("items")
    items = [str(x).strip() for x in raw_items if str(x).strip()] \
        if isinstance(raw_items, list) else []
    if str(data.get("item") or "").strip():
        items.append(str(data["item"]).strip())
    text = str(data.get("text") or "").strip()
    return (items, text) if items and text else None


# ── composing ────────────────────────────────────────────────────────────────

_LANG = {"en": "English", "sw": "Swahili (the customer wrote Swahili)",
         "fr": "French (the customer wrote French)"}


def build_prompt(transcript: list[tuple[str, str]], *, name: str | None,
                 language: str) -> tuple[str, str]:
    system = (
        "You write ONE short WhatsApp/Messenger check-in for Bethany House, a church-"
        "vestments shop, to a customer who went quiet some hours ago. It is a FRESH "
        "message, not the next line of the conversation.\n"
        "Rules:\n"
        f"- Greet them{' by name (' + name + ')' if name else ''}.\n"
        "- Name what they were interested in, using the item's words exactly as they "
        "appear in the conversation. A price may be mentioned ONLY if it already "
        "appears in the conversation, copied exactly — never convert, total or invent.\n"
        "- End with ONE question that moves toward the order.\n"
        "- At most two sentences. No links, no discounts, no pressure.\n"
        "- Never thank them for waiting or for their patience, never say you or a "
        "colleague or the team are checking or will get back to them, never answer or "
        "continue the last message.\n"
        f"- Write in {_LANG.get(language, 'English')}.\n"
        'Reply with JSON only: {"items": ["<each item you name, written exactly as in '
        'the conversation>"], "text": "<the message>"} — or {"skip": "<why>"} when no '
        'item was discussed.'
    )
    lines = []
    for role, text in transcript[-TRANSCRIPT_TURNS:]:
        who = {"customer": "Customer", "team": "Colleague"}.get(role, "Neema")
        lines.append(f"{who}: {' '.join(text.split())[:400]}")
    user = "The conversation so far (for reference only):\n\n" + "\n".join(lines)
    return system, user


async def _compose_llm(system: str, user: str, redis=None) -> str:
    """One plain completion, NO tools: nothing can be searched, converted,
    ordered or written while composing (a preview is look-only by construction).
    The daily AI budget binds it as it binds a live turn: past the stop it
    raises (→ a logged draft failure), in economy it uses the light model."""
    from app.agent.runtime import build_llm
    from app.services import ai_budget
    mode = await ai_budget.guard_turn(redis)
    model = settings.tier2_model_light if mode == "economy" else None
    llm = build_llm(model=model, purpose="job:reengage", cache=False)
    res = await llm.complete(system=system, messages=[{"role": "user", "content": user}],
                             tools=[])
    return res.text or ""


async def _transcript(db, conv_id) -> list[tuple[str, str]]:
    rows = list(reversed((await db.execute(
        select(Message).where(Message.conversation_id == conv_id)
        .where(Message.media_type.is_(None) | (Message.media_type != "note"))
        .order_by(Message.created_at.desc()).limit(TRANSCRIPT_TURNS))).scalars().all()))
    out = []
    for m in rows:
        text = (m.text or "").strip()
        if not text:
            continue
        if m.direction == MsgDirection.inbound:
            out.append(("customer", text))
        elif getattr(m, "sender", None) == MsgSender.human_agent:
            out.append(("team", text))
        else:
            out.append(("neema", text))
    return out


async def _first_name(db, conv: Conversation, to: str) -> str | None:
    from app.services.quote_followup import first_name
    if conv.channel == "whatsapp":
        from app.models.user import User
        u = (await db.execute(select(User).where(User.wa_id == to))).scalar_one_or_none()
        if u is not None and first_name(u.name):
            return first_name(u.name)
    if getattr(conv, "person_id", None) is not None:
        from app.models.person import Person
        p = await db.get(Person, conv.person_id)
        return first_name(getattr(p, "display_name", None))
    return None


# ── selection ────────────────────────────────────────────────────────────────

async def _make_redis():
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True,
                              socket_connect_timeout=5, socket_timeout=5)
        await r.ping()
        return r
    except Exception:                      # a sweep can run without the cache
        _log.warning("redis unavailable — running without the double-send guard")
        return None


async def _latest_message(db, conv_id, direction: MsgDirection | None = None) -> Message | None:
    # Internal notes (escalation records, call summaries) are NOT conversation
    # turns — never let one stand in for the newest message.
    q = (select(Message).where(Message.conversation_id == conv_id)
         .where(Message.media_type.is_(None) | (Message.media_type != "note")))
    if direction is not None:
        q = q.where(Message.direction == direction)
    return (await db.execute(q.order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()


async def _has_cart(db, conv: Conversation, key: str) -> bool:
    from app.agent import cart as cartmod
    store = await cartmod._load_store(db, key, conv.channel or "whatsapp")
    cart = cartmod.read_cart(getattr(store, "state", None)) if store is not None else {}
    return bool((cart or {}).get("items"))


async def _followed_up(db, conv_id, since: datetime) -> bool:
    """A follow-up is planned for this thread, or one was sent after the
    customer's last message — either way they already have (or will have)
    their one check-in; this sweep does not add a second."""
    from sqlalchemy import or_, and_
    from app.models.agent_action import AgentAction
    return (await db.execute(select(AgentAction.id).where(
        AgentAction.conversation_id == conv_id,
        or_(AgentAction.status.in_(("planned", "needs_approval")),
            and_(AgentAction.status == "sent", AgentAction.updated_at >= since)),
    ).limit(1))).first() is not None


async def why_not(db, conv: Conversation, now: datetime) -> tuple[str | None, dict]:
    """(reason this thread is NOT re-engaged, row) — reason None means go."""
    from app.core.phone import is_plausible_phone
    from app.services.quote_followup import order_placed_recently
    key = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
    if not key:
        return "no recipient", {}
    # A web-chat session masquerades as a WhatsApp conversation but its key
    # ("web_<hash>") is not a number — a WABA send is a guaranteed Graph error.
    if conv.channel == "whatsapp" and not is_plausible_phone(key):
        return "not a phone thread", {}
    if conv.intercept_mode != InterceptMode.ai or conv.status != ConvStatus.open:
        return "human mode / closed", {}
    last = await _latest_message(db, conv.id)
    if last is None:
        return "empty thread", {}
    if last.direction == MsgDirection.inbound:
        # Theirs is the newest turn: they are owed a REAL reply (the live path /
        # missed-reply sweeper), never a check-in. One sweep per thread.
        return "unanswered customer message", {}
    if getattr(last, "sender", None) == MsgSender.human_agent:
        return "a colleague spoke last", {}
    if is_handoff_line(last.text):
        return "last outbound handed off to the team", {}
    if (_aware(last.created_at) or now) > now - timedelta(hours=MIN_IDLE_HOURS):
        return "not idle long enough", {}
    last_in = await _latest_message(db, conv.id, MsgDirection.inbound)
    if last_in is None:
        return "customer never wrote", {}
    if getattr(last_in, "comment_context", None):
        return "comment thread", {}
    closes = (_aware(last_in.created_at) or now) + timedelta(hours=WINDOW_HOURS - WINDOW_MARGIN_HOURS)
    if closes <= now:
        return "24h window closed", {}
    if await _followed_up(db, conv.id, _aware(last_in.created_at) or now):
        return "a follow-up is planned or already sent", {}
    if await order_placed_recently(db, conv, now):
        return "order placed (payment follow-up's)", {}
    if await _has_cart(db, conv, key):
        return "cart in progress (cart recovery's)", {}
    return None, {"conv": conv, "to": key, "last_in": last_in, "last_out": last}


async def find_quiet(db, now: datetime | None = None) -> list[dict]:
    """Open AI-mode threads where WE spoke last, the customer went quiet, and
    a fresh check-in may still land inside their 24 h window."""
    now = now or datetime.now(timezone.utc)
    convs = (await db.execute(
        select(Conversation).where(
            Conversation.channel.in_(CHANNELS),
            Conversation.intercept_mode == InterceptMode.ai,
            Conversation.status == ConvStatus.open,
            Conversation.last_message_at >= now - timedelta(hours=WINDOW_HOURS),
            Conversation.last_message_at <= now - timedelta(hours=MIN_IDLE_HOURS),
        ).order_by(Conversation.last_message_at.desc()))).scalars().all()
    out = []
    for conv in convs:
        reason, row = await why_not(db, conv, now)
        if reason is None:
            out.append(row)
    return out


def guard_key(msg: Message) -> str:
    return f"reengage:{msg.id}"


# ── one thread ───────────────────────────────────────────────────────────────

async def _handle(redis, row: dict, *, send: bool, write: bool = True) -> dict:
    from app.services import n8n_bridge as svc
    from app.services.meta_send import send_to_channel

    conv, to, last_in, last_out = row["conv"], row["to"], row["last_in"], row.get("last_out")
    is_wa = conv.channel == "whatsapp"
    res = {"channel": conv.channel, "to": to, "last_in": (last_in.text or "")[:80],
           "draft": "", "refused": None, "sent": False, "skipped": None, "error": None}

    # LEFT ALONE ON PURPOSE (owner, 2026-09-26): a thread Neema paced, paused
    # or the guard silenced is not one to chase.
    if redis is not None:
        try:
            from app.agent import cooling as _cool
            from app.agent.domain import is_paused as _guard_paused
            if (await _cool.is_cooled(redis, conv.channel, to)
                    or await redis.get(f"agent:pause:{conv.channel}:{to}")
                    or await _guard_paused(redis, conv.channel, to)):
                res["skipped"] = "left alone (paced / paused)"
                return res
        except Exception as exc:
            _log.warning("re-engage: pause check failed for %s/%s (%s) — skipped",
                         conv.channel, to[-4:] if to else "", exc)
            res["skipped"] = "pause check unavailable"
            return res

    # Once per customer message: a live send CLAIMS the guard; a dry run reads it.
    if redis is not None:
        try:
            ok = (await redis.set(guard_key(last_in), "1", nx=True, ex=_GUARD_TTL) if send
                  else not await redis.get(guard_key(last_in)))
            if not ok:
                res["skipped"] = "already re-engaged"
                return res
        except Exception as exc:
            _log.warning("re-engage: guard unavailable (%s) — continuing", exc)
    if not write:
        return res

    try:
        async with AsyncSessionLocal() as db:
            transcript = await _transcript(db, conv.id)
            name = await _first_name(db, conv, to)
        language = thread_language([t for r, t in transcript if r == "customer"])
        system, user = build_prompt(transcript, name=name, language=language)
        raw = await _compose_llm(system, user, redis)
    except Exception as e:
        res["error"] = f"draft failed: {str(e)[:160]}"
        return res

    parsed = parse_draft(raw)
    if parsed is None:
        res["skipped"] = res["refused"] = "no item to check in about"
        return res
    items, text = parsed
    why = quality_gate(text, items, transcript=transcript, name=name, language=language)
    if why:
        res["skipped"] = res["refused"] = why
        res["draft"] = text[:200]
        _log.info("re-engage REFUSED (%s) %s %s: %s", why, conv.channel,
                  f"…{to[-4:]}" if to else "…", text[:120])
        return res
    res["draft"] = text[:300]
    if not send:
        return res

    # Fresh recheck: the customer (or a colleague) may have spoken since we
    # selected the thread — then a check-in is the wrong message entirely.
    try:
        async with AsyncSessionLocal() as db2:
            now_last = await _latest_message(db2, conv.id)
        if last_out is not None and (now_last is None or now_last.id != last_out.id):
            res["skipped"] = "thread moved on since selection"
            return res
    except Exception as exc:
        res["error"] = f"recheck failed: {str(exc)[:160]}"
        return res

    try:
        if is_wa:
            wamid = await svc._send_waba(to, text)
            async with AsyncSessionLocal() as db3:
                await svc.save_outbound_message(db3, redis, to, text, waba_msg_id=wamid)
        else:
            await send_to_channel(conv.channel, to, text)
            async with AsyncSessionLocal() as db3:
                await svc.save_outbound_channel_message(db3, redis, conv.channel, to, text)
        res["sent"] = True
    except Exception as e:
        res["error"] = f"send failed: {str(e)[:160]}"
    return res


async def run(send: bool, ignore_quiet_hours: bool = False, *, redis=None,
              max_drafts: int | None = None) -> dict:
    """One sweep. `redis` given → used and left open (the in-process timer);
    `max_drafts` caps a preview: at most 3× that many are composed, and up to
    3 that pass the gate are kept as samples (refusals listed separately)."""
    from app.services.recovery_jobs import anonymise, sample
    own_redis = redis is None
    if own_redis:
        redis = await _make_redis()
    async with AsyncSessionLocal() as db:
        rows = await find_quiet(db)

    mode = "LIVE SEND" if send else "DRY RUN (no messages sent)"
    _log.info("── re-engage sweep · %s ─────────────────────────────", mode)
    _log.info("%d quiet thread(s) (we spoke last, idle >%dh, inside their %dh window, AI mode)",
              len(rows), MIN_IDLE_HOURS, WINDOW_HOURS)

    if send and not ignore_quiet_hours and not within_quiet_hours():
        _log.warning("quiet hours (%02d:00-%02d:00 Nairobi) — nothing sent. "
                     "Use --ignore-quiet-hours to override.", QUIET_START, QUIET_END)
        send = False

    sent = failed = skipped = composed = 0
    samples: list[dict] = []
    refused: list[dict] = []
    for row in rows:
        write = send or max_drafts is None or composed < max_drafts * 3
        r = await _handle(redis, row, send=send, write=write)
        if write and not r["skipped"] or r["refused"]:
            composed += 1
        if r["refused"] and len(refused) < 5:
            refused.append({**sample(r["channel"], r["to"], r["draft"]), "reason": r["refused"]})
        elif r["draft"] and not r["skipped"] and len(samples) < 3:
            samples.append(sample(r["channel"], r["to"], r["draft"]))
        if r["skipped"]:
            skipped += 1
            tag = f"SKIP ({r['skipped']})"
        elif r["error"]:
            failed += 1
            tag = f"FAIL — {r['error']}"
        elif r["sent"]:
            sent += 1
            tag = "SENT"
        else:
            tag = "DRAFT" if r["draft"] else "WOULD CHECK IN"
        _log.info("[%s] %-9s %s\n    last in: %s\n    check-in: %s",
                  tag, r["channel"], anonymise(r["to"]), r["last_in"], r["draft"])

    _log.info("── done: %d candidate(s) · %d sent · %d skipped · %d failed ──",
              len(rows), sent, skipped, failed)
    if own_redis and redis is not None:
        try:
            await redis.aclose()
        except Exception:
            pass
    return {"candidates": len(rows), "sent": sent, "skipped": skipped, "failed": failed,
            "would_send": 0 if send else len(rows) - skipped - failed, "samples": samples,
            "refused": refused}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Check in once with customers who went quiet after our reply (<=24h).")
    ap.add_argument("--send", action="store_true",
                    help="actually send. Without this flag it only previews (dry run).")
    ap.add_argument("--ignore-quiet-hours", action="store_true",
                    help="send even outside 08:00-20:00 Nairobi time.")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(run(send=args.send, ignore_quiet_hours=args.ignore_quiet_hours))
