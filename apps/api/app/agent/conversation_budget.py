"""The conversation budget and the bot shield — RECORD-ONLY for now (owner,
2026-11-04: "go ahead with the … cooling-off plan", record-only first).

PACING (agent/cooling.py) answers every message with a buying word in full
and never counts it — and its word list holds "do you have", "I want", any
number and every colour, so "do you have a wife" and "send me 100
shillings" were a sale, and pacing fired 0 times in 200 chats a day. A
token-drainer only had to mention blue; a bot only had to keep asking.

The budget reads WHAT HAPPENED, not which words were used:

  PROGRESS is a turn that moved the sale — a new item looked up, the cart
  changed, contact / measurements / parish saved, a quotation, a checkout
  link or an order made (the turn's own tool results).
  The BUDGET for a contact's day is `pacing_budget_base` replies plus
  `pacing_budget_per_step` for every step of progress. A buyer closes in
  10–15 replies and never meets it.
  Past the budget with no progress: WOULD SHORTEN (light model, brief, ask
  for the order); `pacing_budget_per_step` replies further: WOULD PAUSE. A
  cart, an unpaid order, an open deal or a complaint: WOULD ALERT THE TEAM
  instead — a buyer is never paused.
  The same item priced three times today: WOULD REPEAT THE PRICE BRIEFLY.
  A BOT score from the thread itself — replies landing within seconds of
  ours, again and again; our own words echoed back; auto-reply or AI text;
  dozens of messages an hour; the same text from many contacts — WOULD
  TREAT AS A BOT (one fixed line, then silence, the team alerted).
  Under a post: a fourth exchange with one person WOULD MOVE TO DM; the same
  comment on three posts WOULD TREAT AS SPAM.

Each decision is recorded once per contact per day (pacing_events, Reports →
Pacing) for the owner to mark right or wrong. Nothing a customer sees
changes in `pacing_budget_mode = "shadow"`. Best-effort throughout: any
failure records nothing and the turn is untouched.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

from app.core.config import settings

_log = logging.getLogger("neema.budget")

DAY_TTL = 2 * 24 * 3600
SEEN_TTL = 14 * 24 * 3600

# The tools whose call IS a step toward the order (search_catalog and
# send_product_cards count only when they surface an item new to this person).
PROGRESS_TOOLS = frozenset({
    "update_cart", "create_order", "capture_contact", "capture_customer",
    "save_measurements", "save_parish", "prepare_quotation",
    "whatsapp_checkout_link", "apply_offer"})

DECISIONS = {
    "shorten": "Would shorten and ask for the order",
    "pause": "Would pause (one warm close, then quiet)",
    "alert": "Would alert the team (a buyer past the budget)",
    "repeat_price": "Would repeat the price briefly",
    "bot": "Would treat as a bot",
    "move_to_dm": "Would move the comment thread to DM",
    "spam": "Would treat the comment as spam",
}

_AUTOREPLY_RE = re.compile(
    r"thank(?:s| you) for (?:contacting|reaching|your message|messaging)|"
    r"(?:this is|i am) an? (?:automated|auto(?:matic)?)\b|auto[- ]?reply|away message|"
    r"we(?:'ll| will) (?:get back|respond|reply) (?:to you )?(?:shortly|as soon as|soon)|"
    r"(?:currently|presently) (?:unavailable|away|out of (?:the )?office)|"
    r"(?:our )?business hours are|do not reply to this", re.IGNORECASE)
_AI_RE = re.compile(
    r"\bas an ai\b|\bi(?:'m| am) an? (?:ai|language model|virtual assistant|chatbot)\b|"
    r"i'?d be (?:happy|glad) to help (?:you )?with that|is there anything else i can (?:help|assist)|"
    r"\bi don'?t have (?:personal|the ability)", re.IGNORECASE)


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _k(kind: str, channel: str, key: str) -> str:
    return f"pace2:{kind}:{_day()}:{channel}:{key}"


def _toks(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(w) > 2}


def echoes(inbound: str, ours: str) -> bool:
    """Their message is mostly our own last words coming back."""
    a, b = _toks(inbound), _toks(ours)
    if len(a) < 6 or not b:
        return False
    return len(a & b) / len(a) >= 0.7


def budget_for(progress: int) -> int:
    return int(settings.pacing_budget_base) + int(settings.pacing_budget_per_step) * max(progress, 0)


def progress_in(tool_log: list | None, new_items: int) -> int:
    """Steps toward the order this turn: progress tools that ran, plus items
    new to this person."""
    n = sum(1 for t in tool_log or [] if (t or {}).get("tool") in PROGRESS_TOOLS
            and not ((t or {}).get("out") or {}).get("error"))
    return n + max(new_items, 0)


def bot_score(rows: list[tuple[str, datetime, str]], *, hour_count: int = 0,
              shared_by: int = 0) -> tuple[int, list[str]]:
    """(score, reasons) from the thread's latest rows, newest LAST:
    (direction 'inbound'|'outbound', created_at, text)."""
    reasons: list[str] = []
    score = 0
    fast, last_out, last_out_text, echo, auto, ai = 0, None, "", False, False, False
    inbound = 0
    for direction, at, text in rows:
        if direction == "outbound":
            last_out, last_out_text = at, text or ""
            continue
        inbound += 1
        if last_out is not None and at is not None and (at - last_out).total_seconds() < 4:
            fast += 1
        if last_out_text and echoes(text, last_out_text):
            echo = True
        if _AUTOREPLY_RE.search(text or ""):
            auto = True
        if _AI_RE.search(text or ""):
            ai = True
    if fast >= 3:
        score += 2
        reasons.append(f"{fast} replies within 4 seconds of ours")
    if echo:
        score += 2
        reasons.append("our own words echoed back")
    if auto:
        score += 2
        reasons.append("auto-reply text")
    if ai:
        score += 1
        reasons.append("AI-sounding text")
    if hour_count >= 30:
        score += 2
        reasons.append(f"{hour_count} messages in the last hour")
    if shared_by >= 5:
        score += 2
        reasons.append(f"the same text from {shared_by} contacts today")
    return score, reasons


async def _incr(redis, key: str, by: int = 1, ttl: int = DAY_TTL) -> int:
    v = int(await redis.incrby(key, by))
    await redis.expire(key, ttl)
    return v


async def _thread_rows(db, channel: str, key: str) -> tuple[list, int, object]:
    """The thread's last 12 messages (oldest first), its inbound count in the
    last hour, and its conversation id."""
    from sqlalchemy import func, or_, select
    from app.models.conversation import Conversation
    from app.models.message import Message, MsgDirection
    conv = (await db.execute(select(Conversation).where(
        Conversation.channel == channel,
        or_(Conversation.external_id == key, Conversation.wa_id == key)))).scalars().first()
    if conv is None:
        return [], 0, None
    not_note = Message.media_type.is_(None) | (Message.media_type != "note")
    rows = (await db.execute(
        select(Message.direction, Message.created_at, Message.text)
        .where(Message.conversation_id == conv.id).where(not_note)
        .order_by(Message.created_at.desc()).limit(12))).all()
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    hour = (await db.execute(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conv.id, Message.direction == MsgDirection.inbound,
            Message.created_at > since))).scalar() or 0
    out = []
    for d, at, t in reversed(rows):
        dv = d.value if hasattr(d, "value") else str(d)
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        out.append((dv, at, t or ""))
    return out, int(hour), conv.id


async def _shared_by(redis, channel: str, key: str, text: str) -> int:
    """How many contacts sent this exact text today (one long message only:
    'hi' and 'how much' are everyone's)."""
    t = " ".join((text or "").lower().split())
    if len(t) < 25:
        return 0
    k = f"pace2:text:{_day()}:{hashlib.sha1(t.encode()).hexdigest()[:16]}"
    await redis.sadd(k, f"{channel}:{key}")
    await redis.expire(k, DAY_TTL)
    return int(await redis.scard(k))


async def assess(redis, db, *, channel: str, key: str, user_text: str, reply: str,
                 tool_log: list | None, seen_products: list | None, public_comment: bool = False,
                 post_id: str | None = None, closer: bool = False) -> list[dict]:
    """After a real turn: count it, measure its progress and record what the
    budget and the bot shield WOULD do. Returns the decisions recorded."""
    if redis is None or (settings.pacing_budget_mode or "off") not in ("shadow", "live") \
            or closer or not (user_text or "").strip():
        return []
    try:
        return await _assess(redis, db, channel=channel, key=key, user_text=user_text,
                             reply=reply, tool_log=tool_log, seen_products=seen_products,
                             public_comment=public_comment, post_id=post_id)
    except Exception as exc:
        _log.info("conversation budget skipped for %s/%s: %s", channel, key, exc)
        return []


async def _assess(redis, db, *, channel, key, user_text, reply, tool_log, seen_products,
                  public_comment, post_id) -> list[dict]:
    from app.agent.review import money_figures
    from app.agent.cooling import business_in_play
    decisions: list[tuple[str, list[str]]] = []

    if public_comment:
        if post_id:
            n = await _incr(redis, _k(f"thread:{post_id}", channel, key))
            if n > 3:
                decisions.append(("move_to_dm", [f"exchange {n} with this person under one post"]))
            t = " ".join((user_text or "").lower().split())
            if len(t) >= 12:
                pk = f"pace2:posts:{_day()}:{channel}:{key}:{hashlib.sha1(t.encode()).hexdigest()[:12]}"
                await redis.sadd(pk, str(post_id))
                await redis.expire(pk, DAY_TTL)
                posts = int(await redis.scard(pk))
                if posts >= 3:
                    decisions.append(("spam", [f"the same comment on {posts} posts today"]))
        return await _record_all(redis, db, channel, key, decisions, {})

    # ── the budget ───────────────────────────────────────────────────────
    slugs = [str(p.get("slug") or p.get("name") or "") for p in (seen_products or []) if p]
    seen_key = f"pace2:seen:{channel}:{key}"
    new_items = 0
    for s in dict.fromkeys(x for x in slugs if x):
        if await redis.sadd(seen_key, s):
            new_items += 1
    await redis.expire(seen_key, SEEN_TTL)
    step = progress_in(tool_log, new_items)
    turns = await _incr(redis, _k("turns", channel, key))
    progress = await _incr(redis, _k("progress", channel, key), step) if step \
        else int(await redis.get(_k("progress", channel, key)) or 0)
    budget = budget_for(progress)
    counts = {"turns": turns, "progress": progress, "budget": budget}
    in_play = None
    if turns > budget and not step:
        in_play = await business_in_play(db, channel, key)
        over = turns - budget
        why = [f"{turns} replies today, budget {budget} ({progress} steps of progress)"]
        if in_play:
            decisions.append(("alert", why + ["a cart, order, deal or complaint is in play"]))
        elif over > int(settings.pacing_budget_per_step):
            decisions.append(("pause", why))
        else:
            decisions.append(("shorten", why))

    # ── the same price, again ───────────────────────────────────────────
    if money_figures(reply or "") and slugs:
        for s in dict.fromkeys(x for x in slugs if x):
            n = await _incr(redis, _k(f"priced:{s}", channel, key))
            if n >= 3:
                decisions.append(("repeat_price", [f"{s} priced {n} times today"]))
                break

    # ── the bot shield ──────────────────────────────────────────────────
    rows, hour = [], 0
    if db is not None:
        rows, hour, _conv = await _thread_rows(db, channel, key)
    shared = await _shared_by(redis, channel, key, user_text)
    score, reasons = bot_score(rows, hour_count=hour, shared_by=shared)
    counts["bot_score"] = score
    if score >= int(settings.pacing_bot_threshold):
        if in_play is None:
            in_play = await business_in_play(db, channel, key)
        if not in_play:
            decisions.append(("bot", reasons))
    return await _record_all(redis, db, channel, key, decisions, counts)


async def _record_all(redis, db, channel, key, decisions, counts) -> list[dict]:
    out = []
    for decision, reasons in decisions:
        # Once per contact per decision per day: the list stays a list.
        if not await redis.set(_k(f"rec:{decision}", channel, key), "1", ex=DAY_TTL, nx=True):
            continue
        await redis.hincrby(f"pace2:tally:{_day()}", decision, 1)
        await redis.expire(f"pace2:tally:{_day()}", DAY_TTL)
        await record(channel=channel, contact=key, decision=decision, reasons=reasons,
                     counts=counts)
        out.append({"decision": decision, "reasons": reasons, **counts})
    return out


async def record(*, channel: str, contact: str, decision: str, reasons: list[str],
                 counts: dict) -> None:
    """One pacing_events row (own session). Best-effort."""
    from sqlalchemy import or_, select
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation
    from app.models.pacing_event import PacingEvent
    try:
        async with AsyncSessionLocal() as db:
            conv = (await db.execute(select(Conversation).where(
                Conversation.channel == channel,
                or_(Conversation.external_id == contact, Conversation.wa_id == contact)))
            ).scalars().first()
            db.add(PacingEvent(
                channel=channel, contact=str(contact)[:128],
                conversation_id=conv.id if conv is not None else None,
                decision=decision, reasons=list(reasons or [])[:6],
                turns=counts.get("turns"), progress=counts.get("progress"),
                budget=counts.get("budget"), bot_score=counts.get("bot_score"),
                mode=(settings.pacing_budget_mode or "shadow")))
            await db.commit()
    except Exception:
        _log.warning("pacing event record failed for %s/%s", channel, contact, exc_info=True)


async def read_tally(redis) -> dict:
    if redis is None:
        return {}
    try:
        raw = await redis.hgetall(f"pace2:tally:{_day()}")
    except Exception:
        return {}
    out = {}
    for k, v in (raw or {}).items():
        ks = k.decode() if isinstance(k, bytes) else str(k)
        try:
            out[ks] = int(v)
        except (TypeError, ValueError):
            pass
    return out
