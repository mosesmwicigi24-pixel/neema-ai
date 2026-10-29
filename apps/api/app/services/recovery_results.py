"""What the follow-ups actually achieved — one row per message sent, then a
read of what the customer did next.

The three daily sweeps (cart_recovery, payment_followup, reengage) used to
leave only a count per run in Redis, so "did anyone answer?" could only be
estimated from send windows. Now each message a sweep really sends writes one
`recovery_sends` row (job, thread, person, the cart / order it was about, when).
Quote follow-ups already keep a row each in agent_actions (status 'sent').

`results()` reads, for every send in the period:
  replied   — the customer wrote in that thread within REPLY_HOURS of it
  converted — cart / re-engage / quote: they placed an order within ORDER_DAYS;
              payment reminder: the order it was about is now paid
  waiting   — sent too recently for the reply window to have closed, so the
              rates are computed over the settled sends only

No handle, name or message text leaves this module — counts only.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text

_log = logging.getLogger("neema.recovery_results")

JOBS = ("cart_recovery", "payment_followup", "reengage", "quote_follow_up")
REPLY_HOURS = 72
ORDER_DAYS = 7
PAID_STATES = ("paid", "completed", "settled", "success", "successful", "complete")


async def record_send(job: str, conv, *, ref: str | None = None) -> bool:
    """Write one row for a message that WAS sent. Never raises: the message is
    already with the customer, so a failed write must not turn the run into a
    failure (or a retry that messages them twice) — it is logged as an error
    instead, so a gap in the results is visible in the logs."""
    import app.database as database
    try:
        async with database.AsyncSessionLocal() as db:
            await db.execute(text(
                "INSERT INTO recovery_sends (id, job, conversation_id, person_id, channel, ref, sent_at) "
                "VALUES (:id, :job, :conv, :person, :channel, :ref, now())"),
                {"id": uuid.uuid4(), "job": job, "conv": getattr(conv, "id", None),
                 "person": getattr(conv, "person_id", None),
                 "channel": (getattr(conv, "channel", None) or "whatsapp")[:20],
                 "ref": (ref or None) and str(ref)[:200]})
            await db.commit()
        return True
    except Exception as exc:
        _log.error("recovery send by %s was sent but NOT recorded (%s): %s",
                   job, type(exc).__name__, exc)
        return False


_RESULTS_SQL = """
WITH s AS (
    SELECT rs.job, rs.sent_at, rs.conversation_id, rs.person_id, rs.ref, c.wa_id
      FROM recovery_sends rs
      LEFT JOIN conversations c ON c.id = rs.conversation_id
     WHERE rs.sent_at >= now() - make_interval(days => :days)
    UNION ALL
    SELECT 'quote_follow_up', a.updated_at, a.conversation_id, c.person_id, NULL, c.wa_id
      FROM agent_actions a
      LEFT JOIN conversations c ON c.id = a.conversation_id
     WHERE a.kind = 'quote_follow_up' AND a.status = 'sent'
       AND a.updated_at >= now() - make_interval(days => :days)
), r AS (
    SELECT s.job,
           s.sent_at > now() - make_interval(hours => :reply_hours) AS waiting,
           EXISTS (
               SELECT 1 FROM messages m
                WHERE m.conversation_id = s.conversation_id
                  AND m.direction = 'inbound'
                  AND (m.media_type IS NULL OR m.media_type <> 'note')
                  AND m.created_at > s.sent_at
                  AND m.created_at <= s.sent_at + make_interval(hours => :reply_hours)
           ) AS replied,
           CASE WHEN s.job = 'payment_followup' THEN EXISTS (
               SELECT 1 FROM order_events o
                WHERE s.ref IS NOT NULL
                  AND o.hub_order_id::text = ANY (string_to_array(s.ref, ','))
                  AND (lower(coalesce(o.hub_payment_status, '')) = ANY (:paid)
                       OR lower(coalesce(o.payment_status, '')) = ANY (:paid))
           ) ELSE EXISTS (
               SELECT 1 FROM order_events o
                WHERE ((s.person_id IS NOT NULL AND o.person_id = s.person_id)
                       OR (s.wa_id IS NOT NULL AND o.wa_id = s.wa_id))
                  AND o.created_at > s.sent_at
                  AND o.created_at <= s.sent_at + make_interval(days => :order_days)
           ) END AS converted
      FROM s
)
SELECT job,
       count(*)                                          AS sent,
       count(*) FILTER (WHERE waiting)                   AS waiting,
       count(*) FILTER (WHERE NOT waiting AND replied)   AS replied,
       count(*) FILTER (WHERE NOT waiting AND converted) AS converted
  FROM r
 GROUP BY job
"""


def _rate(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


async def results(db, days: int = 30) -> dict:
    days = max(1, min(int(days), 180))
    rows = (await db.execute(text(_RESULTS_SQL), {
        "days": days, "reply_hours": REPLY_HOURS, "order_days": ORDER_DAYS,
        "paid": list(PAID_STATES)})).mappings().all()
    by_job = {r["job"]: r for r in rows}
    since = (await db.execute(text("SELECT min(sent_at) FROM recovery_sends"))).scalar()
    jobs = []
    for job in JOBS:
        r = by_job.get(job) or {}
        sent, waiting = int(r.get("sent") or 0), int(r.get("waiting") or 0)
        settled = sent - waiting
        replied, converted = int(r.get("replied") or 0), int(r.get("converted") or 0)
        jobs.append({"job": job, "sent": sent, "waiting": waiting, "settled": settled,
                     "replied": replied, "converted": converted,
                     "reply_rate": _rate(replied, settled),
                     "convert_rate": _rate(converted, settled)})
    return {"days": days, "reply_hours": REPLY_HOURS, "order_days": ORDER_DAYS,
            "tracking_since": since.isoformat() if since else None, "jobs": jobs}
