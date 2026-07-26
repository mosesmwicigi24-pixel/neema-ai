"""Seasonal outreach: reach the parishes who will need the next season's colour.

The Church year is this business's demand signal, and it is knowable months ahead
(see app/core/liturgical.py). A parish that bought purple for Advent last year will
need purple again — and because vestments are MADE TO ORDER, the useful moment to
ask is weeks BEFORE the season starts, not when it arrives.

This sweep finds the customers who bought during the SAME liturgical season in a
previous year and offers them the coming season's colour in good time.

Deliberately MANUAL and never on a timer — an outbound campaign must be an
explicit human decision. Defaults to a dry run; pass --send to actually send:

    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.seasonal_outreach            # preview only
    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.seasonal_outreach --send     # SEND live

THE 24-HOUR RULE — the thing that makes this different from the other sweeps.
Most of this audience has NOT written to us recently, so free-form WhatsApp is
not allowed. Each recipient is routed honestly:
  · window OPEN (they messaged within 24h) → a warm free-form message
  · window CLOSED → an APPROVED MARKETING TEMPLATE (WA_SEASONAL_TEMPLATE). If no
    template is configured, they are LISTED and skipped — never messaged illegally.
Meta channels have no such window for a normal DM, so those send free-form.

Other guardrails: quiet hours (08:00-20:00 Nairobi), AI-mode open conversations
only, and one message per customer per season per year.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core import liturgical
from app.core.config import settings
from app.database import AsyncSessionLocal
# Full model set so the mapper registry is complete in a standalone job.
import app.models.agent      # noqa: F401
import app.models.intercept  # noqa: F401
import app.models.person     # noqa: F401
from app.models.conversation import Conversation, ConvStatus, InterceptMode
from app.models.message import Message, MsgDirection
from app.models.order_event import OrderEvent
from app.models.user import User

_log = logging.getLogger("neema.seasonal")

QUIET_START, QUIET_END = 8, 20
WINDOW_HOURS = 24
LEAD_DAYS = 42            # start offering a season six weeks out
_GUARD_TTL = 200 * 24 * 3600      # one offer per customer per season per year


def _nairobi_hour(now: datetime | None = None) -> int:
    return ((now or datetime.now(timezone.utc)) + timedelta(hours=3)).hour


def within_quiet_hours(now: datetime | None = None) -> bool:
    return QUIET_START <= _nairobi_hour(now) < QUIET_END


def next_season(today: date | None = None, lead_days: int = LEAD_DAYS) -> dict | None:
    """The season close enough that made-to-order should start now, or None."""
    s = liturgical.summary(today or date.today(), lead_days=lead_days)
    return s["order_now"][0] if s["order_now"] else None


async def _make_redis():
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True,
                              socket_connect_timeout=5, socket_timeout=5)
        await r.ping()
        return r
    except Exception:
        _log.warning("redis unavailable — running without the once-per-season guard")
        return None


async def _window_open(db, conv: Conversation) -> bool:
    """True when the customer wrote to us within 24h — the only time free-form
    WhatsApp is permitted."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    last_in = (await db.execute(
        select(Message).where(Message.conversation_id == conv.id,
                              Message.direction == MsgDirection.inbound)
        .order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()
    if last_in is None or last_in.created_at is None:
        return False
    at = last_in.created_at
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at >= cutoff


async def find_audience(db, season: str, today: date | None = None) -> list[dict]:
    """Customers who ordered during this SAME liturgical season in a previous year
    — the people who will need that colour again."""
    today = today or date.today()
    orders = (await db.execute(select(OrderEvent))).scalars().all()

    seen: dict[str, dict] = {}
    for o in orders:
        created = o.created_at
        if created is None:
            continue
        d = created.date() if hasattr(created, "date") else created
        if d.year >= today.year and liturgical.season_on(d) == season:
            continue                       # already this year's season — not a repeat
        if liturgical.season_on(d) != season:
            continue
        key = o.wa_id
        if not key or key in seen:
            continue
        seen[key] = {"wa_id": key, "last_bought": d.isoformat(),
                     "items": [i.get("name") for i in (o.items or []) if i.get("name")][:3]}

    out: list[dict] = []
    for key, info in seen.items():
        conv = (await db.execute(
            select(Conversation).where(Conversation.wa_id == key))).scalars().first()
        if conv is None or conv.intercept_mode != InterceptMode.ai \
                or conv.status != ConvStatus.open:
            continue
        user = (await db.execute(select(User).where(User.wa_id == key))).scalar_one_or_none()
        parish_id = None
        if user is not None and user.person_id is not None:
            try:
                from app.models.person import Person
                person = await db.get(Person, user.person_id)
                parish_id = getattr(person, "parish_id", None)
            except Exception:
                parish_id = None
        out.append({**info, "conv": conv, "name": (user.name if user else None),
                    "parish_id": parish_id,
                    "open_window": await _window_open(db, conv)})
    return out


def dedupe_by_parish(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """One seasonal message per PARISH, not one per member. Three people from
    St Mary's each getting the same Advent offer reads as spam and makes the
    business look like it doesn't know they're one church — the MOST RECENT
    buyer gets the message and speaks for the parish. People with no parish on
    file are individuals and pass through untouched. Returns (keep, dropped)."""
    # Pass 1: the winner per parish is the most recent buyer.
    best: dict = {}
    for r in rows:
        pid = r.get("parish_id")
        if pid is None:
            continue
        cur = best.get(pid)
        if cur is None or (r.get("last_bought") or "") > (cur.get("last_bought") or ""):
            best[pid] = r
    # Pass 2: partition, preserving order.
    keep, dropped = [], []
    for r in rows:
        pid = r.get("parish_id")
        if pid is None or best.get(pid) is r:
            keep.append(r)
        else:
            dropped.append(r)
    return keep, dropped


# Clergy titles are part of the name here — "Rev Grace", never "Grace", and never
# the bare title "Rev". Mirrors the same convention Neema uses in conversation.
_TITLES = {"pastor", "bishop", "rev", "revd", "reverend", "apostle", "prophet",
           "elder", "deacon", "deaconess", "dr", "archbishop", "fr", "father",
           "sr", "sister", "mother", "canon", "venerable", "pst", "ps"}


def greeting_name(full: str | None) -> str:
    """How to address them: title + first name for clergy, else the first name."""
    parts = [p for p in (full or "").split() if p]
    if not parts:
        return ""
    if parts[0].strip(".").lower() in _TITLES and len(parts) > 1:
        return f"{parts[0]} {parts[1]}"
    return parts[0]


def compose(row: dict, season: dict, name: str | None = None) -> str:
    """The free-form version — warm, specific, and useful rather than salesy."""
    who = greeting_name(name if name is not None else row.get("name"))
    weeks = max(round(season["days_away"] / 7), 1)
    bought = f" You had {row['items'][0]} from us last time." if row.get("items") else ""
    return (
        f"Hello{(' ' + who) if who else ''} 🙏 {season['season']} begins in about "
        f"{weeks} week(s), and it calls for {season['colour']}.{bought}\n\n"
        "Since we make to order, now is the right time if you'd like anything ready in "
        "good time. Would you like me to check what we have?"
    )


def template_params(row: dict, season: dict, name: str | None = None) -> list[str]:
    """{{1}} name (title + first, for clergy) · {{2}} season · {{3}} colour · {{4}} weeks."""
    weeks = max(round(season["days_away"] / 7), 1)
    who = greeting_name(name if name is not None else row.get("name")) or "there"
    return [who, season["season"], season["colour"], str(weeks)]


async def _handle(redis, row: dict, season: dict, *, send: bool) -> dict:
    from app.services import n8n_bridge as svc
    from app.services.meta_send import send_to_channel, META_CHANNELS

    conv = row["conv"]
    ch = conv.channel or "whatsapp"
    to = row["wa_id"]
    is_wa = ch not in META_CHANNELS
    res = {"channel": ch, "to": to, "name": row.get("name"),
           "last_bought": row["last_bought"], "route": "", "text": "",
           "sent": False, "skipped": None, "error": None}

    year_key = f"seasonal:{season['season']}:{season['date'][:4]}:{to}"
    if send and redis is not None:
        try:
            if not await redis.set(year_key, "1", nx=True, ex=_GUARD_TTL):
                res["skipped"] = "already offered this season"
                return res
        except Exception:
            pass

    use_template = is_wa and not row["open_window"]
    if use_template and not settings.wa_seasonal_template:
        # Outside the window with no approved template — messaging would breach
        # WhatsApp policy. List them, never send.
        res["route"] = "needs template"
        res["skipped"] = "outside 24h window, no WA_SEASONAL_TEMPLATE configured"
        res["text"] = compose(row, season, row.get("name"))[:160]
        return res

    res["route"] = "template" if use_template else "free-form"
    text = compose(row, season, row.get("name"))
    res["text"] = text[:160]
    if not send:
        return res

    try:
        if use_template:
            await svc.send_wa_template(to, settings.wa_seasonal_template,
                                       settings.wa_seasonal_lang,
                                       template_params(row, season, row.get("name")))
        elif is_wa:
            await svc._send_waba(to, text)
            async with AsyncSessionLocal() as db2:
                await svc.save_outbound_message(db2, redis, to, text)
        else:
            await send_to_channel(ch, to, text)
            async with AsyncSessionLocal() as db2:
                await svc.save_outbound_channel_message(db2, redis, ch, to, text)
        res["sent"] = True
    except Exception as e:
        res["error"] = f"send failed: {str(e)[:160]}"
    return res


async def run(send: bool, ignore_quiet_hours: bool = False,
              lead_days: int = LEAD_DAYS) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    season = next_season(lead_days=lead_days)
    mode = "LIVE SEND" if send else "DRY RUN (no messages sent)"
    _log.info("── seasonal outreach · %s ───────────────────────────", mode)
    if season is None:
        _log.info("No season within %d days — nothing to offer yet.", lead_days)
        return {"candidates": 0, "sent": 0, "skipped": 0, "failed": 0}
    _log.info("%s begins %s (%d days) — needs %s",
              season["season"], season["date"], season["days_away"], season["colour"])

    redis = await _make_redis()
    async with AsyncSessionLocal() as db:
        rows = await find_audience(db, season["season"])
    _log.info("%d customer(s) bought during %s in a previous year",
              len(rows), season["season"])
    rows, same_parish = dedupe_by_parish(rows)
    for d in same_parish:
        _log.info("[SKIP (same parish)] %-9s %s — another member speaks for the parish",
                  d["conv"].channel, d["to"] if "to" in d else d["wa_id"])

    if send and not ignore_quiet_hours and not within_quiet_hours():
        _log.warning("quiet hours (%02d:00-%02d:00 Nairobi) — nothing sent.",
                     QUIET_START, QUIET_END)
        send = False

    sent = failed = skipped = 0
    for row in rows:
        r = await _handle(redis, row, season, send=send)
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
            tag = "DRAFT"
        _log.info("[%s] %-9s %-14s %s\n    bought during %s: %s\n    msg  : %s",
                  tag, r["channel"], r["route"], r["to"], season["season"],
                  r["last_bought"], r["text"])

    _log.info("── done: %d candidate(s) · %d sent · %d skipped · %d failed ──",
              len(rows), sent, skipped, failed)
    if redis is not None:
        try:
            await redis.aclose()
        except Exception:
            pass
    return {"candidates": len(rows), "sent": sent, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Offer the coming liturgical season's colour to the parishes "
                    "who bought during that same season before.")
    ap.add_argument("--send", action="store_true",
                    help="actually send. Without this flag it only previews (dry run).")
    ap.add_argument("--ignore-quiet-hours", action="store_true")
    ap.add_argument("--lead-days", type=int, default=LEAD_DAYS,
                    help=f"how far ahead to work (default {LEAD_DAYS}).")
    args = ap.parse_args()
    asyncio.run(run(send=args.send, ignore_quiet_hours=args.ignore_quiet_hours,
                    lead_days=args.lead_days))
