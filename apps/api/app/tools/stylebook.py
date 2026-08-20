"""Learn the house voice from the replies the TEAM actually sent.

    docker compose exec -T api python -m app.tools.stylebook

The owner's observation (2026-08-19): when a human on the team answers, the
reply is small and sure — "The roman collar shirt goes for 2500" — while
Neema, for all her rules, still runs longer and deeper than the house ever
would. Rules describe the voice; the team's own messages ARE the voice.

So this reads every human reply in the last 120 days, pairs each with the
customer message it answered, measures how the team actually writes (median
words — the honest length target), picks a small spread of real exchanges
across the questions customers actually ask (price, availability, delivery,
payment, sizes, greetings, thanks), and stores the distilled block in
app_settings under ``house_voice``. The prompt injects it beside the brevity
contract, so every reply is drafted next to real examples of the house
answering.

Deterministic and zero-cost: no model call anywhere — selection is recency +
filters. Rerun it any time the team's style (or team) changes; Neema picks up
the new block within five minutes (settings cache TTL).

The exemplars teach LENGTH and TONE only. The prompt says so explicitly:
facts, prices and availability always come from the tools — a price in an
old exemplar is history, not an offer.
"""
from __future__ import annotations

import asyncio
import logging
import re
import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

# Message.conversation is a relationship declared by NAME — the mapper only
# resolves it once the whole registry is imported. Querying with the bare
# model import compiles nothing and dies on 'Conversation' (the tool's first
# live run, 2026-08-19). Importing the app registers every model, so anyone
# who imports this module can run its queries.
import app.main  # noqa: F401,E402 — registers models/relationships

logging.basicConfig(level=logging.INFO, format="%(message)s")
_log = logging.getLogger("neema.stylebook")

WINDOW_DAYS = 120         # how far back the team's replies are read
MAX_EXEMPLARS = 12        # the block stays small: it rides in EVERY prompt
MAX_BLOCK_CHARS = 2200    # hard cap on the stored block
Q_CHARS, A_CHARS = 120, 220

HOUSE_VOICE_KEY = "house_voice"

# Question buckets, checked in order — first match wins. English + the
# Swahili/sheng forms customers actually type.
_BUCKETS: list[tuple[str, tuple[str, ...]]] = [
    ("price", ("how much", "price", "cost", "bei ", "bei?", "ngapi",
               "rate", "charges")),
    ("availability", ("do you have", "available", "in stock", "uko na",
                      "mko na", "mnayo", "kuna ", "do u have", "una ")),
    ("delivery", ("deliver", "shipping", "ship ", "send it", "send to",
                  "location", "where are you", "mko wapi", "uko wapi",
                  "how long", "days")),
    ("payment", ("pay", "paybill", "mpesa", "m-pesa", "till", "lipa",
                 "deposit", "account number")),
    ("measurements", ("size", "measurement", "vipimo", "fit", "chest",
                      "length", "height")),
    ("thanks", ("thank", "asante", "amen", "god bless", "bless you")),
    ("greeting", ("hello", "hi ", "hey", "habari", "niaje", "good morning",
                  "good afternoon", "good evening", "shalom")),
]


def bucket_of(question: str) -> str:
    q = f" {(question or '').lower().strip()} "
    for name, keys in _BUCKETS:
        if any(k in q for k in keys):
            return name
    if len(q.split()) <= 3:
        return "greeting"
    return "other"


_WORD = re.compile(r"[A-Za-z0-9À-ɏ']+")


def _words(text: str) -> int:
    return len(_WORD.findall(text or ""))


def _clean(text: str) -> str:
    return " ".join((text or "").split())


# Replies that move the customer to ANOTHER channel instead of answering.
# The standing rules forbid deflection ("'DM us for the price' when you KNOW
# the answer is a lost sale") — so a deflecting reply, however real, must
# never become a teaching example. Found in the first live report
# (2026-08-19): "can I pay in Ethiopian currency?" was answered with
# "i will be calling you using our other whatsapp number".
_DEFLECTIONS = ("will be calling you", "will call you", "we will call",
                "dm us", "inbox us", "check your inbox", "check your dm",
                "message us on", "text us on", "whatsapp us on",
                "reach us on", "call us on", "call our")


def usable_answer(text: str | None) -> bool:
    """Is this human reply worth learning from? Small, textual, self-contained
    — and it must actually ANSWER, not deflect.

    Links are excluded (an exemplar must read whole without following one),
    as are media placeholders and anything so long the team themselves would
    call it a letter."""
    t = _clean(text or "")
    if not t or t.startswith("[") or t.startswith("🤝"):
        return False
    low = t.lower()
    if "http" in low or "www." in low:
        return False
    if any(d in low for d in _DEFLECTIONS):
        return False                       # deflection is anti-teaching
    if not re.search(r"[A-Za-zÀ-ɏ]", t):
        return False                       # digits or emoji alone teach nothing
    # A media send whose caption is just the filename ("FB_IMG_17843…jpg") is
    # not language — one leaked into the house voice and taught Neema that a
    # filename is an acceptable reply to "do you have pictures?".
    if re.search(r"\.(jpe?g|png|gif|webp|mp4|3gp|pdf|docx?|xlsx?)\b", t.lower()):
        return False
    n = _words(t)
    return 1 <= n <= 60


def usable_question(text: str | None) -> bool:
    t = _clean(text or "")
    return bool(t) and not t.startswith("[") and _words(t) >= 1


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", _clean(text).lower())


async def collect_pairs(db) -> tuple[list[dict], list[int], list[int]]:
    """(exemplar pairs, human reply word counts, AI reply word counts).

    A pair is the newest inbound customer message with usable text within 48h
    before a human reply, in the same conversation — the question that reply
    answered."""
    from app.models.message import Message, MsgDirection, MsgSender
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

    human = (await db.execute(
        select(Message)
        .where(Message.direction == MsgDirection.outbound,
               Message.sender == MsgSender.human_agent,
               Message.text.isnot(None),
               Message.created_at > since)
        .order_by(Message.created_at.desc())
        .limit(4000)
    )).scalars().all()
    # Internal notes (briefings etc.) are team-facing — never customer voice.
    human = [m for m in human if (m.media_type or "") != "note"]

    human_wc = [_words(m.text) for m in human if _clean(m.text)]

    ai_rows = (await db.execute(
        select(Message.text)
        .where(Message.direction == MsgDirection.outbound,
               Message.sender == MsgSender.ai,
               Message.text.isnot(None),
               Message.created_at > since)
        .order_by(Message.created_at.desc())
        .limit(4000)
    )).scalars().all()
    ai_wc = [n for t in ai_rows if (n := _words(_clean(t or "")))]

    conv_ids = {m.conversation_id for m in human if m.conversation_id}
    inbound_by_conv: dict = {}
    if conv_ids:
        rows = (await db.execute(
            select(Message)
            .where(Message.conversation_id.in_(conv_ids),
                   Message.direction == MsgDirection.inbound,
                   Message.text.isnot(None),
                   Message.created_at > since - timedelta(days=2))
            .order_by(Message.created_at.asc())
        )).scalars().all()
        for m in rows:
            inbound_by_conv.setdefault(m.conversation_id, []).append(m)

    pairs: list[dict] = []
    for reply in human:                       # newest first already
        if not usable_answer(reply.text):
            continue
        q_msg = None
        for cand in reversed(inbound_by_conv.get(reply.conversation_id, [])):
            if cand.created_at >= reply.created_at:
                continue
            if (reply.created_at - cand.created_at) > timedelta(hours=48):
                break
            if usable_question(cand.text):
                q_msg = cand
                break
        if q_msg is None:
            continue
        q, a = _clean(q_msg.text), _clean(reply.text)
        pairs.append({"q": q[:Q_CHARS], "a": a[:A_CHARS],
                      "kind": bucket_of(q), "at": reply.created_at})
    return pairs, human_wc, ai_wc


def choose_exemplars(pairs: list[dict], cap: int = MAX_EXEMPLARS) -> list[dict]:
    """A spread over question kinds, newest first within each, no duplicate
    answers — round-robin so one busy bucket can't crowd out the rest."""
    seen: set[str] = set()
    by_kind: dict[str, list[dict]] = {}
    for p in pairs:                           # already newest-first
        key = _norm(p["a"])
        if not key or key in seen:
            continue
        seen.add(key)
        by_kind.setdefault(p["kind"], []).append(p)

    order = [name for name, _ in _BUCKETS] + ["other"]
    chosen: list[dict] = []
    rank = 0
    while len(chosen) < cap:
        took = False
        for kind in order:
            rows = by_kind.get(kind) or []
            if rank < len(rows) and len(chosen) < cap:
                chosen.append(rows[rank])
                took = True
        if not took:
            break
        rank += 1
    return chosen


def render_block(exemplars: list[dict], human_wc: list[int],
                 ai_wc: list[int]) -> str:
    """The text stored in app_settings — stats line, then real exchanges."""
    if not exemplars:
        return ""
    med = round(statistics.median(human_wc)) if human_wc else 0
    p75 = round(statistics.quantiles(human_wc, n=4)[2]) if len(human_wc) >= 4 else med
    gap = ""
    if ai_wc and human_wc:
        ai_med = round(statistics.median(ai_wc))
        if ai_med > med:
            gap = f" (recent AI replies ran {ai_med} — close that gap)"
    lines = [f"- The team's replies run a median of {med} words, three quarters "
             f"under {p75} — write at THAT size{gap}."]
    for p in exemplars:
        lines.append(f'- They asked: "{p["q"]}" — the team answered: "{p["a"]}"')
    out = "\n".join(lines)
    while len(out) > MAX_BLOCK_CHARS and len(lines) > 2:
        lines.pop()
        out = "\n".join(lines)
    return out


async def refresh(db, redis) -> str:
    """Re-learn the house voice from the current replies and store the block.
    Returns the stored block ('' when there was nothing to learn). Used by the
    CLI run below AND by the weekly heartbeat — the team's style drifts, new
    people join, coaching lands; the textbook must follow without anyone
    remembering a script."""
    from app.services.app_settings import HOUSE_VOICE_CACHE, set_value

    pairs, human_wc, ai_wc = await collect_pairs(db)
    chosen = choose_exemplars(pairs)
    block = render_block(chosen, human_wc, ai_wc)

    _log.info("human replies read : %d (window %dd)", len(human_wc), WINDOW_DAYS)
    _log.info("usable Q→A pairs   : %d", len(pairs))
    kinds: dict[str, int] = {}
    for p in pairs:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    for k in sorted(kinds, key=kinds.get, reverse=True):
        _log.info("  %-13s %d", k, kinds[k])
    if not block:
        _log.info("nothing to learn yet — no usable human replies found; "
                  "the prompt keeps its current voice")
        return ""
    _log.info("---- the block Neema will read ----\n%s\n----", block)

    await set_value(db, HOUSE_VOICE_KEY, block)
    _log.info("stored %d chars → app_settings.%s (%d exemplars)",
              len(block), HOUSE_VOICE_KEY, len(chosen))
    if redis is not None:
        try:
            await redis.delete(HOUSE_VOICE_CACHE)
            _log.info("cache dropped — live on the next customer turn")
        except Exception:
            _log.info("cache not reachable — live within 5 minutes (TTL)")
    return block


async def main() -> None:
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.database import AsyncSessionLocal

    r = None
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        pass
    async with AsyncSessionLocal() as db:
        await refresh(db, r)
    if r is not None:
        try:
            await r.aclose()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
