"""Every activity of every turn, written where a human can read it.

`run_turn` logs each tool call ("agent tool search_catalog(...) -> ...") into
the server log — invisible from the dashboard. The owner asked (2026-08-19)
for the Activity Log to capture every activity of the customer interaction,
so each tool call now also lands as an `agent_activities` row: a plain-English
line ("Showed product card(s)"), the specifics beneath it ("Aluminium 4
Stacked Communion Set + 3 gallery photos"), and a bounded echo of the call.

Written only by REAL turns — read-only drafts and scribe passes preview,
they don't act — and best-effort everywhere: the trail must never cost a
reply. Rendered by the same Activity Log ledger the pickups, check-ins,
deals, orders and calls already flow through.
"""
from __future__ import annotations

import json
import logging

from app.core import money

from sqlalchemy import or_, select

_log = logging.getLogger("neema.agent")


def _j(x, cap: int = 300) -> str:
    try:
        s = json.dumps(x, ensure_ascii=False, default=str)
    except Exception:
        s = str(x)
    return s[:cap]


def describe(tool: str, args: dict, out) -> tuple[str, str | None]:
    """(label, detail) — the plain-English line the Activity Log shows.

    Every tool gets a line; the ones a shopkeeper acts on read like a
    colleague's diary, and anything unrecognised falls back to the raw call
    so NOTHING the agent does goes unrecorded."""
    a = args if isinstance(args, dict) else {}
    o = out if isinstance(out, dict) else {}
    try:
        if tool == "search_catalog":
            q = (a.get("query") or "").strip()
            n = o.get("count", len(o.get("results") or []))
            return "Searched the catalogue", f"“{q}” → {n} result(s)"
        if tool == "send_product_cards":
            names = ", ".join(str(p) for p in (a.get("products") or [])[:6])
            extra = o.get("album_photos") or 0
            d = names + (f" (+{extra} gallery photo{'s' if extra != 1 else ''})" if extra else "")
            sent = o.get("sent_cards", 0)
            return ("Showed product card(s)" if sent else "Prepared product card(s)"), d or None
        if tool == "update_cart":
            act = a.get("action") or "update"
            item = a.get("product") or ""
            qty = a.get("quantity") or a.get("qty")
            total = o.get("total")
            ccy = o.get("currency") or ""
            d = " ".join(str(x) for x in (act, item, f"×{qty}" if qty else "") if x).strip()
            if total is not None:
                d += f" → total {ccy} {money.num(total)}" if isinstance(total, (int, float)) else f" → total {total}"
            return "Updated the cart", d or None
        if tool == "create_order":
            num = o.get("order_number") or ""
            total, ccy = o.get("total"), o.get("currency") or ""
            d = f"{num}" + (f" — {ccy} {money.num(total)}" if isinstance(total, (int, float)) else "")
            return "Created an order", d.strip(" —") or None
        if tool == "check_availability":
            return "Asked the team to confirm availability", (a.get("item") or a.get("query") or None)
        if tool == "save_measurements":
            mm = a.get("measurements") or {}
            return "Saved measurements", ", ".join(f"{k} {v}" for k, v in list(mm.items())[:6]) or None
        if tool in ("capture_contact", "capture_customer"):
            fields = ", ".join(k for k, v in a.items() if v) or None
            return "Saved customer details", fields
        if tool == "schedule_check_in":
            when = a.get("on_day") or (f"in {a.get('days_from_now')} day(s)"
                                       if a.get("days_from_now") is not None else "")
            return "Booked a check-in", " — ".join(x for x in (str(when), a.get("reason") or "") if x) or None
        if tool == "whatsapp_checkout_link":
            return "Shared the WhatsApp checkout link", None
        if tool == "share_catalog":
            return "Shared the catalogue link", (a.get("product") or None)
        if tool == "handoff_to_human":
            return "Handed the conversation to a human", (a.get("reason") or None)
        if tool == "pause_conversation":
            return "Paused the conversation (2h cooldown)", (a.get("reason") or None)
        if tool == "escalate_to_human":
            return "Escalated to a human", (a.get("reason") or None)
        if tool == "remember":
            return "Noted a durable fact", (a.get("fact") or a.get("note") or _j(a, 120))
        if tool == "set_lead_source":
            return "Recorded the lead source", (a.get("source") or None)
        if tool == "send_product_video":
            return "Sent a product video", (a.get("product") or None)
        if tool == "church_calendar":
            return "Checked the church calendar", None
    except Exception:
        pass
    # The fallback that keeps the promise: EVERY activity gets a row.
    return f"Agent step: {tool}", _j(a, 160) or None


async def record(db, *, channel: str, contact: str, tool: str,
                 args: dict, out) -> None:
    """Write one activity row. Best-effort — never raises into the turn."""
    try:
        from app.models.agent_activity import AgentActivity
        from app.models.conversation import Conversation

        label, detail = describe(tool, args, out)
        conv = (await db.execute(select(Conversation).where(
            Conversation.channel == channel,
            or_(Conversation.external_id == contact,
                Conversation.wa_id == contact)))).scalars().first()
        err = (out or {}).get("error") if isinstance(out, dict) else None
        db.add(AgentActivity(
            conversation_id=(conv.id if conv is not None else None),
            person_id=(getattr(conv, "person_id", None) if conv is not None else None),
            channel=channel, contact=(contact or "")[:128] or None,
            tool=tool[:40], summary=label,
            detail=(f"{detail} · failed: {_j(err, 80)}" if err and detail
                    else (f"failed: {_j(err, 80)}" if err else detail)),
            # Bounded per-value, never truncated mid-JSON: the echo must always
            # be storable, whatever a tool was called with.
            payload=({"args": {str(k)[:40]: _j(v, 150) for k, v in args.items()}}
                     if isinstance(args, dict) and args else None),
        ))
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        _log.warning("activity trail write failed for %s/%s (%s)",
                     channel, contact, tool, exc_info=False)
