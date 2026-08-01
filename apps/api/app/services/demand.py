"""Record and aggregate unmet demand — the shop's most valuable unlogged data.

Every "do you have…?" that the catalogue can't answer is a real customer, with a
real need, in their own words. Today those requests disappear into the chat. Here
they become evidence: what to stock, what to make, and who to tell when we do.

Recording is BEST-EFFORT by design — a demand log must never break a sale.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.demand_signal import DemandSignal

_log = logging.getLogger("neema.demand")

KINDS = ("no_match", "out_of_catalogue", "sourcing_gap", "availability_check")

# Noise that would otherwise dominate the report — greetings and bare pleasantries
# are not product demand.
_STOPWORDS = {"hi", "hello", "hey", "habari", "sasa", "thanks", "thank you", "ok",
              "okay", "yes", "no", "please", "asante", "amen", "hallo", "test"}


def normalise(q: str | None) -> str:
    """Lowercase, strip punctuation and collapse whitespace, so 'Purple Chasuble?'
    and 'purple  chasuble' are counted as the SAME request."""
    s = re.sub(r"[^\w\s]", " ", (q or "").lower())
    return re.sub(r"\s+", " ", s).strip()[:200]


def is_meaningful(q: str) -> bool:
    """Worth logging as demand? Not a greeting, not a single stray character."""
    n = normalise(q)
    return bool(n) and len(n) >= 3 and n not in _STOPWORDS


async def record(db: AsyncSession, query: str, *, kind: str = "no_match",
                 channel: str | None = None, wa_id: str | None = None,
                 person_id=None, detail: str | None = None) -> bool:
    """Log one unmet request. Never raises — a demand log must not break a sale."""
    try:
        if kind not in KINDS or not is_meaningful(query):
            return False
        db.add(DemandSignal(
            query=normalise(query), raw_query=(query or "")[:1000], kind=kind,
            channel=channel, wa_id=(wa_id or None), person_id=person_id,
            detail=(detail or None)))
        await db.commit()
        return True
    except Exception as exc:
        _log.warning("demand record failed for %r: %s", query, exc)
        try:
            await db.rollback()
        except Exception:
            pass
        return False


async def top_demand(db: AsyncSession, days: int = 30, limit: int = 25,
                     kind: str | None = None) -> list[dict]:
    """What people keep asking for and we keep not having, most-wanted first.

    Ranked by DISTINCT PEOPLE, not raw hits: twelve different parishes asking for
    a cope is a product decision; one person asking twelve times is a conversation.
    """
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (select(DemandSignal.query,
                func.count().label("requests"),
                func.count(func.distinct(func.coalesce(
                    func.cast(DemandSignal.person_id, __import__("sqlalchemy").String),
                    DemandSignal.wa_id))).label("people"),
                func.max(DemandSignal.created_at).label("last_asked"),
                func.min(DemandSignal.raw_query).label("example"))
         .where(DemandSignal.created_at >= since)
         .group_by(DemandSignal.query)
         .order_by(func.count(func.distinct(func.coalesce(
             func.cast(DemandSignal.person_id, __import__("sqlalchemy").String),
             DemandSignal.wa_id))).desc(), func.count().desc())
         .limit(max(1, min(limit, 200))))
    if kind:
        q = q.where(DemandSignal.kind == kind)
    rows = (await db.execute(q)).all()
    return [{
        "query": r.query,
        "requests": int(r.requests or 0),
        "people": int(r.people or 0),
        "last_asked": r.last_asked.isoformat() if r.last_asked else None,
        "example": r.example,
    } for r in rows]
