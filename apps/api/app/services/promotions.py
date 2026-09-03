"""A discount the owner has actually given — named, priced, and time-boxed.

Neema may never discount on her own authority; that rule does not move. This
is the other case: an offer the owner declared, which she should then state
OUTRIGHT rather than hint at. The owner's words for it were "make it outright
the discount given" — name the offer, say the old price and the new one, and
say how long it runs. A customer who has to ask twice what the offer is has
been sold to badly.

Three decisions hold this together:

  · THE ARITHMETIC IS CODE'S, NOT THE MODEL'S. A language model doing money in
    its head is how a customer gets quoted 118 on a 10%-off 130. Every offer
    price in this file is Decimal, half-up, computed from the price the
    customer is actually being shown — so it is right in KES, USD and ZMW
    alike, with no double rounding.
  · IT EXPIRES BY ITSELF. A campaign carries its last day. Past it, nothing
    reaches the prompt and nothing is announced: a forgotten promotion cannot
    keep giving away margin.
  · THE ORDER CARRIES IT. Quoting 117 while the hub order says 130 is how you
    turn a discount into a complaint, so the campaign rides into the order
    notes for whoever applies it (see hub_client.push_pending_order).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.core import money

_log = logging.getLogger("neema.promotions")

CAMPAIGN_KEY = "sales_campaign"
CAMPAIGN_CACHE = "app:campaign"

MAX_PERCENT = 70          # past this it is not a promotion, it is a mistake
SCOPES = ("all", "category", "products")


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _clean_list(v) -> list[str]:
    out, seen = [], set()
    for x in (v or []):
        s = str(x or "").strip()
        k = s.lower()
        if s and k not in seen:
            seen.add(k)
            out.append(s)
    return out[:60]


def parse(raw) -> dict | None:
    """A stored campaign, validated — or None if there isn't a usable one.

    Deliberately strict and quiet: anything malformed reads as "no offer", so
    a bad row can never make Neema announce a discount nobody authorised.
    """
    if not raw:
        return None
    try:
        c = json.loads(raw) if isinstance(raw, (str, bytes)) else dict(raw)
    except Exception:
        return None
    if not isinstance(c, dict):
        return None

    name = str(c.get("name") or "").strip()[:60]
    try:
        percent = int(c.get("percent"))
    except (TypeError, ValueError):
        return None
    if not name or not (1 <= percent <= MAX_PERCENT):
        return None

    scope = str(c.get("scope") or "all").strip().lower()
    if scope not in SCOPES:
        return None
    categories = _clean_list(c.get("categories"))
    skus = _clean_list(c.get("skus"))
    if scope == "category" and not categories:
        return None
    if scope == "products" and not skus:
        return None

    try:
        ends_on = date.fromisoformat(str(c.get("ends_on")))
    except Exception:
        return None
    starts_on = None
    if c.get("starts_on"):
        try:
            starts_on = date.fromisoformat(str(c["starts_on"]))
        except Exception:
            starts_on = None

    return {"name": name, "percent": percent, "scope": scope,
            "categories": categories, "skus": skus,
            "starts_on": starts_on.isoformat() if starts_on else None,
            "ends_on": ends_on.isoformat()}


def is_running(c: dict | None, on: date | None = None) -> bool:
    """Is this campaign live today? Inclusive of its last day — an offer that
    says "until the 30th" is expected to work on the 30th."""
    if not c:
        return False
    day = on or _today()
    try:
        if c.get("starts_on") and day < date.fromisoformat(c["starts_on"]):
            return False
        return day <= date.fromisoformat(c["ends_on"])
    except Exception:
        return False


def applies_to(c: dict | None, item: dict) -> bool:
    """Does the campaign cover this catalogue row?

    Category and SKU matching are case-insensitive and trimmed, because the
    owner types "Gowns" into a box and the hub says "gowns".
    """
    if not c or not item:
        return False
    if c["scope"] == "all":
        return True
    if c["scope"] == "category":
        cat = str(item.get("category") or "").strip().lower()
        return bool(cat) and cat in {x.lower() for x in c["categories"]}
    sku = str(item.get("sku") or "").strip().lower()
    return bool(sku) and sku in {x.lower() for x in c["skus"]}


def offer_price(c: dict | None, price) -> int | float | None:
    """The price after the offer — Decimal, half-up to the cent, never the
    model's guess.

    Exact, because the hub is exact: it applies the percentage to ITS OWN
    figure and charges that (the order lines carry discount_type/value), so
    the number Neema says must be the number the hub bills — 10% off USD 45
    is 40.50, not 41. Whole-dollar rounding here was the last place a quote
    could disagree with the charge. Returns None when there is nothing to
    discount, and never returns a number equal to or above the original — an
    "offer" that saves nothing must not be announced as one.
    """
    if not c:
        return None
    try:
        p = Decimal(str(price))
    except Exception:
        return None
    if p <= 0:
        return None
    net = p * (Decimal(100 - c["percent"]) / Decimal(100))
    # To the cent, half-up — money's own granularity, and the hub's. Python's
    # round() is banker's rounding and would quietly hand the customer a cent
    # that isn't theirs on every half-cent price.
    out = money.exact(net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return out if out is not None and 0 < out < float(p) else None


def order_note(c: dict | None) -> str:
    """What the team reading the hub order needs to know.

    Order lines go to the hub at list price and a person applies the offer, so
    this line is the whole safety net between "quoted 45" and "charged 50".
    Only ever attached to an order whose conversation was actually GRANTED the
    offer (see was_granted) — a customer who happily paid list price must not
    be discounted by a note nobody meant.
    """
    if not is_running(c):
        return ""
    return (f"{c['name']}: {c['percent']}% off — quoted to the customer at the "
            f"offer price. APPLY before taking payment (offer ends {c['ends_on']}).")


def _human_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except Exception:
        return iso
    return f"{d.day} {d.strftime('%B %Y')}"


def describe(c: dict | None) -> str:
    """The offer, in the words Neema is told to use.

    Named, quantified, scoped and dated — the four things a customer needs and
    the four a vague "we have a discount" leaves out.
    """
    if not is_running(c):
        return ""
    if c["scope"] == "all":
        what = "everything in the catalogue"
    elif c["scope"] == "category":
        what = "our " + ", ".join(c["categories"])
    else:
        what = "selected items"
    return (f"{c['name']} — {c['percent']}% off {what}, "
            f"until {_human_date(c['ends_on'])}")


# ── who has actually been given it ───────────────────────────────────────────
# The offer is a CLOSING LEVER, not an announcement: most customers buy at the
# list price and never ask. So the discount is granted per conversation, by
# Neema, at the moment it buys her something — and only a conversation that was
# granted it carries the note telling the team to apply it. Without this the
# team would discount every order, including the ones the customer never asked
# to have discounted, which is the exact margin the holding-back protects.

_GRANT_TTL = 45 * 24 * 3600        # outlives any campaign; the order comes later


def _grant_key(channel: str, key: str) -> str:
    return f"offer:granted:{channel or 'whatsapp'}:{key}"


async def mark_granted(redis, channel: str, key: str, campaign) -> bool:
    """Record the TERMS this customer was promised — not merely that they were.

    A price you have quoted is a promise, and a promise does not expire because
    the campaign behind it did. Storing the name, the percentage and the day it
    was given means an order placed after the offer ends still carries what was
    actually said to them.
    """
    if redis is None or not key:
        return False
    c = campaign if isinstance(campaign, dict) else {"name": str(campaign or "")}
    promise = {"name": c.get("name") or "", "percent": c.get("percent"),
               "at": _today().isoformat()}
    # What the offer COVERS travels with it. The note a person reads before
    # taking payment used to say only "X% off — honour it", so an offer scoped
    # to one category read as an offer on the whole order. Carrying the scope
    # means the note can name its own limit.
    scope = c.get("scope")
    if scope in ("category", "products"):
        promise["scope"] = scope
        promise["covers"] = _clean_list(
            c.get("categories") if scope == "category" else c.get("skus"))
    try:
        await redis.set(_grant_key(channel, key), json.dumps(promise), ex=_GRANT_TTL)
        return True
    except Exception:
        # Losing this quietly is how a customer gets quoted 18,000 and billed
        # 20,000: the price was said out loud, and the only record that it was
        # said never got written. The caller refuses to quote when this returns
        # False — but somebody has to be able to see WHY afterwards.
        _log.exception("could not record a promised offer (%s / %s)", channel, key)
        return False


async def granted_promise(redis, channel: str, key: str) -> dict | None:
    """What this customer was promised, if anything.

    Tolerates the older format, which stored the campaign name as bare text:
    those still count as a promise, just without a percentage to quote back.
    """
    if redis is None or not key:
        return None
    try:
        raw = await redis.get(_grant_key(channel, key))
    except Exception:
        return None
    if not raw:
        return None
    s = raw.decode() if isinstance(raw, bytes) else str(raw)
    try:
        p = json.loads(s)
        if isinstance(p, dict) and p.get("name"):
            return p
    except Exception:
        pass
    return {"name": s, "percent": None, "at": None} if s and s != "1" else None


async def was_granted(redis, channel: str, key: str) -> bool:
    """Was it? Kept as the plain question; the terms are in granted_promise."""
    return bool(await granted_promise(redis, channel, key))


def promise_note(promise: dict | None) -> str:
    """The order note for a promise ALREADY MADE.

    Deliberately independent of whether the campaign still runs: withdrawing a
    price you already gave someone is how a discount turns into a complaint,
    and they never find out from us that the offer ended the day before.
    """
    if not promise or not promise.get("name"):
        return ""
    pct = promise.get("percent")
    size = f"{pct}% off" if pct else "the offer price"
    when = f" on {promise['at']}" if promise.get("at") else ""
    covers = promise.get("covers") or []
    if covers:
        what = ", ".join(covers[:8]) + ("…" if len(covers) > 8 else "")
        limit = (f" It covers ONLY {what} — charge full price for anything else "
                 f"on this order.")
    else:
        limit = ""
    return (f"{promise['name']}: {size} was QUOTED to this customer{when}. "
            f"Honour it — APPLY before taking payment, even if the offer has "
            f"since ended.{limit}")


def promise_covers(promise: dict | None, item: dict) -> bool:
    """Does a promise already made cover this order line?

    The promise records its own scope (see mark_granted), so this asks the
    question against WHAT THE CUSTOMER WAS TOLD rather than against whatever
    campaign happens to be running now. An older promise stored without a scope
    was, at the time, an offer on everything — honour it that way.
    """
    if not promise or not promise.get("name"):
        return False
    scope = promise.get("scope")
    if scope not in ("category", "products"):
        return True                      # 'all', or a promise from before scopes
    covers = {str(x).strip().lower() for x in (promise.get("covers") or [])}
    if not covers:
        return False
    field = "category" if scope == "category" else "sku"
    return str(item.get(field) or "").strip().lower() in covers


def applied_note(promise: dict | None, applied: int, pending: int) -> str:
    """The order note once the discount has been PUT ON THE ORDER as money.

    The old note said "APPLY before taking payment", which was right when the
    order always arrived at list price. Now that the covered lines carry the
    discount themselves, that same sentence would have a person discount the
    order a SECOND time. So the note has to say exactly what happened.
    """
    if not promise or not promise.get("name"):
        return ""
    pct = promise.get("percent")
    size = f"{pct}% off" if pct else "the offer price"
    when = f" on {promise['at']}" if promise.get("at") else ""

    if applied and not pending:
        return (f"{promise['name']}: {size} was quoted{when} and IS ALREADY ON "
                f"THIS ORDER. Do not apply it again.")
    if applied and pending:
        return (f"{promise['name']}: {size} was quoted{when}. It is already on "
                f"the stocked lines. The made-to-order line(s) still need it "
                f"applied by hand before payment.")
    if pending:
        return (f"{promise['name']}: {size} was quoted{when} and is NOT yet on "
                f"this order — apply it to the made-to-order line(s) before "
                f"taking payment.")
    return ""


def promise_line(promise: dict | None) -> str:
    """What Neema must be told, so she does not contradict her own quote.

    Without this she reads the catalogue's full price, sees no running offer,
    and quotes a higher number than she gave this same person yesterday.
    """
    if not promise or not promise.get("name"):
        return ""
    pct = promise.get("percent")
    size = f" ({pct}% off)" if pct else ""
    when = f" on {promise['at']}" if promise.get("at") else ""
    return (f"- You already gave this customer our {promise['name']}{size}"
            f"{when}. THAT PRICE STANDS: quote it again if they come back to "
            f"the same item, even if the offer has since ended — we do not take "
            f"back a price we have given. Do not deepen it, and do not offer it "
            f"a second time as though it were new.")


# ── storage (app_settings row, redis-cached like the other live settings) ────

async def active_campaign(db, redis) -> dict | None:
    """Today's offer, or None. Cache-first; any failure means no offer, which
    is the safe direction — silence never gives away margin."""
    if redis is not None:
        try:
            v = await redis.get(CAMPAIGN_CACHE)
            if v is not None:
                s = v.decode() if isinstance(v, bytes) else str(v)
                c = parse(s) if s and s != "-" else None
                return c if is_running(c) else None
        except Exception:
            pass
    try:
        from app.services.app_settings import get_value
        raw = await get_value(db, CAMPAIGN_KEY)
    except Exception:
        return None
    c = parse(raw)
    if redis is not None:
        try:
            await redis.set(CAMPAIGN_CACHE, json.dumps(c) if c else "-", ex=300)
        except Exception:
            pass
    return c if is_running(c) else None


async def campaign_now(redis) -> dict | None:
    """Today's offer, without borrowing the caller's session.

    Every caller sits on a hot path — a catalogue search, an order, the system
    prompt — and each holds a session that belongs to a customer's turn. A
    settings read must not consume, dirty or fail it. Redis answers the normal
    case; a cold cache opens a SHORT PRIVATE session; anything going wrong
    means no offer, which is the safe direction.
    """
    if redis is not None:
        try:
            v = await redis.get(CAMPAIGN_CACHE)
            if v is not None:
                s = v.decode() if isinstance(v, bytes) else str(v)
                c = parse(s) if s and s != "-" else None
                return c if is_running(c) else None
        except Exception:
            pass
    try:
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            return await active_campaign(db, redis)
    except Exception:
        return None


async def set_campaign(db, redis, campaign: dict | None, updated_by=None) -> dict | None:
    """Declare an offer, or end one by passing None. The cache is written with
    the row: ending a campaign has to stop it now, not in five minutes."""
    from sqlalchemy import select
    from app.models.app_setting import AppSetting

    c = parse(campaign) if campaign else None
    if campaign and not c:
        raise ValueError("a campaign needs a name, 1-70%, a scope with its "
                         "categories or SKUs, and an end date (YYYY-MM-DD)")
    val = json.dumps(c) if c else ""
    row = (await db.execute(select(AppSetting).where(
        AppSetting.id == CAMPAIGN_KEY))).scalar_one_or_none()
    if row is None:
        db.add(AppSetting(id=CAMPAIGN_KEY, value=val, updated_by=updated_by))
    else:
        row.value = val
        row.updated_by = updated_by
    await db.commit()
    if redis is not None:
        try:
            await redis.set(CAMPAIGN_CACHE, val or "-", ex=300)
        except Exception:
            pass
    _log.info("sales campaign %s", describe(c) if c else "ended")
    return c
