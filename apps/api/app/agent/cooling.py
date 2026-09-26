"""PACING — cooling off without betraying the sale (owner, 2026-09-26: "some
people want to chat with neema non-stop. how do we enhance cooling off
without betraying the quality of the sales and closing sales?").

Every model turn costs money; a buyer's whole close takes ten or fifteen of
them, a chatter takes forty a day. The ladder here reads WHAT the person is
doing, not just how much:

  a BUYING SIGNAL — an item named, a price or the order asked, a photo sent
      (`buying_signal`) — is answered in full, always, whatever the count;
  BUSINESS IN PLAY — a cart, an open deal, an unpaid order, a complaint on
      the thread (`business_in_play`) — keeps the thread warm, whatever the
      chat;
  a TURN COUNT past the hourly or daily economy line, or three drifting
      turns (small talk, stories, the same question again), moves the turn
      to the light model with a pacing note: still answered, at a third of
      the price, in one or two lines;
  past the cool-off line — or five drifting turns — with no buying signal
      and nothing in play, the thread gets ONE warm close that says exactly
      how to resume ("just say which item") and then silence for
      `cooling_hours`; the first buying signal lifts it and is answered;
  an IDENTICAL text within `cooling_dup_seconds` is not a new turn — the
      answer already on their screen stands.

  a QUESTION during the cool-off ("can you sing?", "je, mko wapi?") is
      answered at once, briefly, on the light model — a question is never
      left hanging (owner: re-engage on "a question");
  everything else during the cool-off rides the SLOW LANE: the messages are
      collected and answered together, once, every `cooling_defer_minutes`,
      briefly — slowed, never cut off (owner: "slow, pause, or defer").

Closers ("thanks", "ok") count for nothing — the closer gate owns them.
Public comments have their own per-post and per-person caps (runtime).
Best-effort throughout: no redis, a redis error, anything odd → no verdict,
and the turn runs as it always did."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from app.core.config import settings

_log = logging.getLogger("neema.cooling")

# What a buyer says. Money and order words (EN + SW) and the goods we sell.
_BUY_RE = re.compile(
    r"(?<![a-z'])(?:"
    r"order|orders|buy|buying|purchase|pay|paid|payment|price|prices|cost|costs|how much|"
    r"quote|quotation|invoice|receipt|deliver|delivery|ship|shipping|shipped|courier|dhl|pickup|"
    r"pick up|collect|size|sizes|measure|measurements|colou?rs?|discount|deposit|instal?ments?|"
    r"m-?pesa|paybill|till|link|available|availability|stock|ready|wholesale|bulk|catalog(?:ue)?|"
    r"photos?|pictures?|pics?|"
    r"bei|ngapi|nunua|agiza|oda|lipa|malipo|nimelipa|tuma|saizi|rangi|vipimo|jumla|bado|"
    r"picha|"
    r"cassocks?|kasoki|surplices?|saples|saplis|sapulisi|albs?|stoles?|stola|chasubles?|copes?|"
    r"gowns?|joho|collars?|kola|shirts?|cinctures?|belts?|ropes?|skull ?caps?|tallits?|"
    r"chalices?|kikombe|patens?|pateni|trays?|sinia|cups?|vikombe|wafers?|hosts?|bread|mkate|"
    r"wine|divai|thuribles?|chetezo|incense|ubani|candles?|mishumaa|mshumaa|oil|mafuta|"
    r"bibles?|biblia|bells?|kengele|crosses?|msalaba|rings?|pete|mitres?|croziers?|"
    r"vestments?|mavazi|communion|ushirika|clergy|bishop|pastor|priest|choir|"
    r"ordination|graduation|set|seti|"
    r"sell|sells|selling|uza|unauza|mnauza|products?|bidhaa|items?|do you have|mnayo|"
    r"nataka|natafuta|i need|i want|looking for|"
    r"located|location|shop|duka|address|visit|open|hours|branch|mko wapi|mahali|"
    r"nipe|nipatie|niuzie|shilingi|kiasi gani|niko na|nimeagiza|nimetuma|hela|doo|mkwanja|"
    r"ganji|fee|fees|gift|gifts|zawadi|present|hamper|"
    r"black|white|navy|blue|red|purple|green|gold|golden|silver|cream|maroon|grey|gray|"
    r"nyeusi|nyeupe|bluu|bule|nyekundu|zambarau|kijani|dhahabu|fedha|"
    r"small|medium|large|xl|xxl|inch|inches|cm|\d+|"
    r"total|balance|amount|due|owe|pesa|shilling|shillings|dollars?|ksh|kes|usd"
    r")(?![a-z'])",
    re.IGNORECASE)
_TITLES = {"pastor", "bishop", "rev", "reverend", "apostle", "prophet", "elder", "deacon", "dr",
           "archbishop", "fr", "father", "mama", "sister", "brother", "mr", "mrs", "ms"}


_QUESTION_RE = re.compile(
    r"\?|^(?:what|how|why|when|where|who|whom|which|can|could|would|will|do|does|did|is|are|"
    r"was|were|have|has|should|may|je|nini|vipi|lini|wapi|nani|gani|mbona|kwa nini|ni)\b",
    re.IGNORECASE)


def is_question(text: str) -> bool:
    """A question, by its mark or its first word (EN + SW)."""
    t = " ".join(str(text or "").split())
    return bool(t) and bool(_QUESTION_RE.search(t))


def buying_signal(text: str, has_media: bool = False) -> bool:
    """A photo, an item, a price, an order — anything a buyer says."""
    if has_media:
        return True
    t = " ".join(str(text or "").split())
    if not t:
        return False
    return bool(_BUY_RE.search(t))


# ── keys ─────────────────────────────────────────────────────────────────────

def _k(kind: str, channel: str, key: str) -> str:
    return f"cool:{kind}:{channel}:{key}"


def cool_seconds() -> int:
    return int(getattr(settings, "cooling_hours", 3) or 3) * 3600


async def is_cooled(redis, channel: str, key: str) -> bool:
    if redis is None:
        return False
    try:
        return bool(await redis.get(_k("off", channel, key)))
    except Exception:
        return False


async def cool(redis, channel: str, key: str) -> None:
    if redis is None:
        return
    try:
        await redis.set(_k("off", channel, key), datetime.now(timezone.utc).isoformat(),
                        ex=cool_seconds())
        await redis.delete(_k("drift", channel, key))
    except Exception:
        pass


async def lift(redis, channel: str, key: str) -> None:
    if redis is None:
        return
    try:
        await redis.delete(_k("off", channel, key), _k("drift", channel, key),
                           _k("h", channel, key))
    except Exception:
        pass


async def _bump(redis, kind: str, channel: str, key: str, ttl: int) -> int:
    try:
        n = int(await redis.incr(_k(kind, channel, key)))
        if n == 1:
            await redis.expire(_k(kind, channel, key), ttl)
        return n
    except Exception:
        return 0


async def note_turn(redis, channel: str, key: str) -> tuple[int, int]:
    """Count this turn in the hour and the day: (hour_count, day_count)."""
    if redis is None:
        return 0, 0
    return (await _bump(redis, "h", channel, key, 3600),
            await _bump(redis, "d", channel, key, 24 * 3600))


async def note_drift(redis, channel: str, key: str, sales_content: bool) -> int:
    """Consecutive turns with nothing to sell in them; a buying signal resets."""
    if redis is None:
        return 0
    if sales_content:
        try:
            await redis.delete(_k("drift", channel, key))
        except Exception:
            pass
        return 0
    return await _bump(redis, "drift", channel, key, 24 * 3600)


async def is_duplicate(redis, channel: str, key: str, text: str) -> bool:
    """The same words again within `cooling_dup_seconds` — the answer already
    on their screen stands. Short answers ("yes", "2") are never held: they
    may be answering two different questions."""
    if redis is None:
        return False
    t = " ".join(str(text or "").lower().split())
    if len(t) < 8 or len(t.split()) < 2:
        return False
    secs = int(getattr(settings, "cooling_dup_seconds", 180) or 0)
    if secs <= 0:
        return False
    h = hashlib.sha1(t.encode()).hexdigest()[:12]
    try:
        fresh = await redis.set(_k(f"dup:{h}", channel, key), "1", nx=True, ex=secs)
        return not fresh
    except Exception:
        return False


# ── what is in play on the thread ─────────────────────────────────────────────

async def business_in_play(db, channel: str, key: str) -> bool:
    """A cart with items, an open deal past 'new', an unpaid order this week,
    or a complaint / escalation flagged in the last day — the thread is a
    sale in progress and is never cooled. Best-effort: any failure → not."""
    if db is None:
        return False
    try:
        from app.agent import cart as cartmod
        cart = await cartmod.get_cart(db, key, channel)
        if cart and (cart.get("items") or []):
            return True
    except Exception:
        pass
    try:
        from datetime import timedelta
        from sqlalchemy import select
        from app.models.order_event import OrderEvent
        since = datetime.now(timezone.utc) - timedelta(days=7)
        row = (await db.execute(
            select(OrderEvent.id).where(OrderEvent.wa_id == key,
                                        OrderEvent.payment_status == "unpaid",
                                        OrderEvent.created_at > since).limit(1))).scalar_one_or_none()
        if row:
            return True
    except Exception:
        pass
    try:
        from datetime import timedelta
        from sqlalchemy import select
        from app.services.deals import _conversation_of, open_deal_for
        from app.models.intercept import Intercept, InterceptAction
        conv = await _conversation_of(db, key, channel)
        if conv is not None:
            deal = await open_deal_for(db, conversation_id=conv.id)
            if deal is not None and (deal.stage or "new") not in ("new", "lost"):
                return True
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            flag = (await db.execute(
                select(Intercept.id).where(
                    Intercept.conversation_id == conv.id,
                    Intercept.action.in_((InterceptAction.flag, InterceptAction.escalated)),
                    Intercept.created_at > since).limit(1))).scalar_one_or_none()
            if flag:
                return True
    except Exception:
        pass
    return False


# ── what we say ───────────────────────────────────────────────────────────────

def _address(name: str) -> str:
    toks = [t for t in str(name or "").replace(".", "").split() if t]
    if not toks:
        return ""
    if toks[0].lower() in _TITLES and len(toks) > 1:
        return f"{toks[0]} {toks[1]}"
    return toks[0]


def cool_line(swahili: bool = False, name: str = "") -> str:
    """ONE warm close that says exactly how to resume — never a chase, never
    a lecture, never 'you have been chatting too much'."""
    who = _address(name)
    if swahili:
        return ((f"Asante {who} — " if who else "Asante — ")
                + "nitakuacha kwa sasa. Ukiwa tayari kuagiza, taja tu bidhaa unayohitaji "
                  "na nitakuhudumia mara moja. Mungu akubariki.")
    return ((f"Thank you, {who} — " if who else "Thank you — ")
            + "I'll leave you to it for now. When you're ready for an item, just say "
              "which one and I'll pick it right up. God bless.")


def pacing_note(drift: int) -> str:
    """The tail note the writer gets on an economy turn."""
    close = ("If they are only chatting, ONE warm close — 'When you're ready for an "
             "item, just say which one and I'll pick it right up' — and call "
             "`pause_conversation`. " if drift >= 3 else "")
    return ("\n\nPACING: this person has been chatting a long while and no order is "
            "taking shape. Keep to ONE or two short lines; no cards, no new "
            "suggestions. Answer what they ask, then one gentle step toward the item "
            "they were looking at. " + close +
            "A buyer is never paced: an item named, a price asked, a photo, a cart, an "
            "order or a complaint gets your full attention.")


def flag_note(kind: str, hour: int, day: int) -> str:
    if kind == "cool":
        return (f"Neema paced this conversation: {day} turns today ({hour} this hour) with no "
                f"item, order or complaint in play — she sent one warm close and is silent "
                f"for {cool_seconds() // 3600}h unless they ask for an item.")
    return ""


# ── the tally (health) ───────────────────────────────────────────────────────

def _day_key() -> str:
    return "cool:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def record(redis, outcome: str, channel: str = "") -> None:
    if redis is None or outcome not in ("economy", "cooled", "silenced", "lifted", "duplicate",
                                        "deferred", "question"):
        return
    try:
        key = _day_key()
        await redis.hincrby(key, outcome, 1)
        if channel:
            await redis.hincrby(key, f"{outcome}:{channel}", 1)
        await redis.expire(key, 3 * 24 * 3600)
    except Exception:
        pass


async def read_tally(redis) -> dict:
    if redis is None:
        return {}
    try:
        raw = await redis.hgetall(_day_key()) or {}
    except Exception:
        return {}
    out: dict = {}
    for k, v in raw.items():
        k = k.decode() if isinstance(k, bytes) else str(k)
        v = v.decode() if isinstance(v, bytes) else v
        try:
            out[k] = int(v)
        except (TypeError, ValueError):
            pass
    return out


# ── the verdict ──────────────────────────────────────────────────────────────

async def should_defer(redis, channel: str, key: str, text: str, has_media: bool = False,
                       closer: bool = False) -> bool:
    """For the schedulers, before a turn is even created: a cooled thread's
    non-question chat rides the slow lane. A buying signal or a question goes
    straight through (run_turn lifts or answers briefly). Never a closer —
    the closer gate owns "ok" and "thanks"."""
    if not getattr(settings, "cooling_enabled", True) or redis is None or closer:
        return False
    if int(getattr(settings, "cooling_defer_minutes", 15) or 0) <= 0:
        return False
    try:
        if not await is_cooled(redis, channel, key):
            return False
    except Exception:
        return False
    if buying_signal(text, has_media) or is_question(text):
        return False
    return True


_LANE_TASKS: set = set()


async def slow_lane(redis, channel: str, key: str, text: str, media: dict | None, runner) -> bool:
    """Put a cooled thread's message on the slow lane: buffered, and answered
    together with whatever else arrives, once, after `cooling_defer_minutes`
    — `runner(text, media)` is the channel's own send path, run with
    deferred=True so the reply is one brief line. True when deferred."""
    if redis is None:
        return False
    import asyncio
    import json
    secs = int(getattr(settings, "cooling_defer_minutes", 15) or 15) * 60
    try:
        await redis.rpush(_k("lane", channel, key), json.dumps({"text": text or "", "media": media}))
        await redis.expire(_k("lane", channel, key), max(secs * 4, 3600))
        started = await redis.set(_k("lanelock", channel, key), "1", nx=True, ex=secs + 120)
    except Exception:
        return False
    await record(redis, "deferred", channel)
    _log.info("pacing: %s/%s on the slow lane (answered in %d min)", channel, key, secs // 60)
    if started:
        task = asyncio.create_task(_run_lane(redis, channel, key, runner, secs))
        _LANE_TASKS.add(task)
        task.add_done_callback(_LANE_TASKS.discard)
    return True


async def _run_lane(redis, channel: str, key: str, runner, secs: int) -> None:
    import asyncio
    import json
    await asyncio.sleep(secs)
    try:
        raw = await redis.lrange(_k("lane", channel, key), 0, -1)
        await redis.delete(_k("lane", channel, key), _k("lanelock", channel, key))
        if not await is_cooled(redis, channel, key):
            # A buying signal lifted the thread meanwhile and was answered with
            # the whole history in hand — the buffered chat is not answered twice.
            _log.info("pacing: slow lane for %s/%s dropped — the thread was lifted", channel, key)
            return
    except Exception:
        return
    texts, media = [], None
    for r in raw or []:
        try:
            item = json.loads(r.decode() if isinstance(r, bytes) else r)
        except Exception:
            continue
        if (item.get("text") or "").strip():
            texts.append(item["text"].strip())
        if item.get("media") and (media is None or item["media"].get("type") == "image"):
            media = item["media"]
    if not texts and not media:
        return
    try:
        await runner("\n".join(texts), media)
    except Exception as exc:
        _log.warning("slow lane reply failed for %s/%s: %s", channel, key, exc)


async def decide(redis, db, *, channel: str, key: str, text: str, has_media: bool = False,
                 closer: bool = False, swahili: bool = False, customer_name: str = "",
                 answering: bool = False, deferred: bool = False) -> dict | None:
    """What pacing does with this turn, before the writer sees it:

    None — nothing: answer as always.
    {"action": "silence", "why": "duplicate"} — the same words again within
        minutes; the answer on their screen stands.
    {"action": "defer", "why": "cooled"} — a cooled thread's non-question
        chat: the schedulers put it on the slow lane (where there is no lane,
        the caller stays silent).
    {"action": "cool", "reply"} — the one warm close; the thread is now
        cooled for `cooling_hours` (the caller flags the team).
    {"action": "economy", "note"} — answer on the light model, briefly: past
        the economy line, a question during the cool-off, or the slow lane's
        own batched turn (`deferred`).
    """
    if not getattr(settings, "cooling_enabled", True) or redis is None:
        return None
    if closer:
        return None                                   # the closer gate's business
    buying = buying_signal(text, has_media)
    # `answering`: our last line ended with a question — their reply ("black
    # please", "yes, one") is the sale talking, however few its words.
    sales = buying or answering
    if deferred:
        # The slow lane's own turn: one brief answer to everything they said.
        return None if buying else {"action": "economy", "note": pacing_note(3), "hour": 0, "day": 0}
    if await is_cooled(redis, channel, key):
        if buying or await business_in_play(db, channel, key):
            await lift(redis, channel, key)
            await record(redis, "lifted", channel)
            await is_duplicate(redis, channel, key, text)     # this ask is now answered
            _log.info("pacing: cool-off lifted for %s/%s — a buying signal", channel, key)
            return None
        if is_question(text):
            # A question is never left hanging: answered now, briefly.
            if await is_duplicate(redis, channel, key, text):
                await record(redis, "duplicate", channel)
                return {"action": "silence", "why": "duplicate"}
            await record(redis, "question", channel)
            return {"action": "economy", "note": pacing_note(3), "hour": 0, "day": 0}
        await record(redis, "silenced", channel)
        return {"action": "defer", "why": "cooled"}
    # A duplicate is held only when the earlier copy was ANSWERED — read after
    # the cool-off check, so a silenced ask repeated still lifts the thread.
    if await is_duplicate(redis, channel, key, text):
        await record(redis, "duplicate", channel)
        _log.info("pacing: duplicate text within minutes for %s/%s — the answer stands", channel, key)
        return {"action": "silence", "why": "duplicate"}
    if sales:
        await note_drift(redis, channel, key, sales_content=True)
        return None                                   # a buyer is never paced, never counted
    # Only unprompted chat counts toward the hourly and daily lines.
    hour, day = await note_turn(redis, channel, key)
    drift = await note_drift(redis, channel, key, sales_content=False)
    s = settings
    if await business_in_play(db, channel, key):
        # A sale in progress is never cooled and never made brief — except a
        # whole day of pure chat past the cool-off line, which goes light.
        if day > int(getattr(s, "cooling_cool_day", 40)):
            await record(redis, "economy", channel)
            return {"action": "economy", "note": pacing_note(drift), "hour": hour, "day": day}
        return None
    over_cool = (hour > int(getattr(s, "cooling_cool_hour", 20))
                 or day > int(getattr(s, "cooling_cool_day", 40))
                 or drift >= int(getattr(s, "cooling_drift_turns", 5)))
    over_econ = (hour > int(getattr(s, "cooling_economy_hour", 10))
                 or day > int(getattr(s, "cooling_economy_day", 20))
                 or drift >= 3)
    if over_cool:
        await cool(redis, channel, key)
        await record(redis, "cooled", channel)
        _log.info("pacing: %s/%s cooled for %dh (%d/h, %d/day, drift %d)", channel, key,
                  cool_seconds() // 3600, hour, day, drift)
        return {"action": "cool", "reply": cool_line(swahili, customer_name),
                "flag": flag_note("cool", hour, day)}
    if over_econ:
        await record(redis, "economy", channel)
        return {"action": "economy", "note": pacing_note(drift), "hour": hour, "day": day}
    return None
