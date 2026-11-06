"""Why did Neema message this customer — or not? A read-only trace.

    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.outreach_trace 254712345678 [--days 7]

Prints, for one WhatsApp number (or a conversation id), the last N days of
the thread's traffic with each outbound row's ORIGIN (the stamp every
unprompted sender now leaves in messages.raw_meta), its delivery status where
Meta reported one, the planned actions on the conversation in every status,
the deal's state (open team check, blocking, next action), the customer's
contact preferences, and the redis guards that explain a skip. Nothing is
written. The number is masked in the heading; the thread text is shown
because the person running this is reading the thread anyway.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.database import AsyncSessionLocal


def _mask(s: str | None) -> str:
    s = str(s or "")
    return f"…{s[-4:]}" if len(s) > 4 else "…"


def _fmt(dt) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + timedelta(hours=3)).strftime("%a %d %b %H:%M")      # Nairobi


def _origin(m) -> str:
    meta = m.raw_meta if isinstance(m.raw_meta, dict) else {}
    kind = meta.get("kind")
    if kind == "outreach":
        bits = [meta.get("source") or "?", meta.get("class") or ""]
        if meta.get("action_kind"):
            bits.append(meta["action_kind"])
        if meta.get("template"):
            bits.append(f"template:{(meta['template'] or {}).get('template')}")
        return " ".join(b for b in bits if b)
    if kind == "template":
        return f"template:{meta.get('template')} ({meta.get('purpose')})"
    if kind == "hold_line":
        return "hold line (turn failed)"
    sender = getattr(m.sender, "value", str(m.sender or ""))
    if m.media_type == "note":
        return "internal note"
    if sender == "human_agent":
        return "colleague"
    if (m.text or "").startswith("[template "):
        return "template (legacy marker)"
    return "live reply" if sender == "ai" else sender


def _delivery(m) -> str:
    meta = m.raw_meta if isinstance(m.raw_meta, dict) else {}
    d = meta.get("delivery") or {}
    if not d:
        return "accepted" if m.waba_msg_id else ""
    return d.get("status") or "" + (f" ({d.get('error')})" if d.get("error") else "")


async def trace(handle: str, days: int = 7) -> None:
    import importlib
    import pkgutil
    import app.models as models_pkg
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{mod.name}")
    from app.models.agent_action import AgentAction
    from app.models.conversation import Conversation
    from app.models.deal import Deal
    from app.models.intercept import Intercept
    from app.models.message import Message
    from app.models.person import Person
    from app.services.deals import team_check_open
    from app.services.intent import preferences

    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        conv = None
        try:
            conv = await db.get(Conversation, uuid.UUID(handle))
        except (ValueError, AttributeError):
            pass
        if conv is None:
            conv = (await db.execute(select(Conversation).where(
                Conversation.wa_id == handle.lstrip("+")))).scalar_one_or_none()
        if conv is None:
            print("no conversation for", _mask(handle))
            return
        key = conv.wa_id or conv.external_id
        print(f"\n=== {conv.channel} {_mask(key)} · conversation {conv.id} · mode "
              f"{getattr(conv.intercept_mode, 'value', conv.intercept_mode)} · status "
              f"{getattr(conv.status, 'value', conv.status)} ===")

        person = await db.get(Person, conv.person_id) if conv.person_id else None
        prefs = preferences(person) if person is not None else {}
        print("contact preferences:", json.dumps(prefs, ensure_ascii=False) if prefs else "none")

        deals = (await db.execute(select(Deal).where(Deal.conversation_id == conv.id)
                                  .order_by(Deal.updated_at.desc()).limit(3))).scalars().all()
        for d in deals:
            tc = team_check_open(d)
            print(f"deal {str(d.id)[:8]} · {d.status}/{d.stage} · {d.title or ''}"
                  f"{' · TEAM CHECK OPEN: ' + tc if tc else ''}"
                  f"{' · blocking: ' + d.blocking if d.blocking else ''}"
                  f"{' · next: ' + json.dumps(d.next_action, ensure_ascii=False) if d.next_action else ''}")

        print(f"\n--- thread, last {days} days (Nairobi time) ---")
        rows = (await db.execute(select(Message).where(
            Message.conversation_id == conv.id, Message.created_at >= since)
            .order_by(Message.created_at))).scalars().all()
        for m in rows:
            arrow = "←" if getattr(m.direction, "value", m.direction) == "inbound" else "→"
            text = " ".join((m.text or "").split())[:110]
            origin = "" if arrow == "←" else f"  [{_origin(m)}]"
            deliv = f"  <{_delivery(m)}>" if arrow == "→" and _delivery(m) else ""
            print(f"{_fmt(m.created_at)} {arrow} {text}{origin}{deliv}")

        print("\n--- planned actions (all statuses, newest first) ---")
        acts = (await db.execute(select(AgentAction).where(
            AgentAction.conversation_id == conv.id)
            .order_by(AgentAction.created_at.desc()).limit(25))).scalars().all()
        if not acts:
            print("none")
        for a in acts:
            print(f"{_fmt(a.created_at)} · {a.kind:<16} {a.status:<14} due {_fmt(a.due_at)} · "
                  f"{' '.join((a.reason or '').split())[:140]}")

        print("\n--- activity flags, last 30 days ---")
        flags = (await db.execute(select(Intercept).where(
            Intercept.conversation_id == conv.id,
            Intercept.created_at >= datetime.now(timezone.utc) - timedelta(days=30))
            .order_by(Intercept.created_at.desc()).limit(15))).scalars().all()
        for f in flags:
            print(f"{_fmt(f.created_at)} · {getattr(f.action, 'value', f.action)} · "
                  f"{' '.join((f.note or '').split())[:120]}")

    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True,
                              socket_connect_timeout=5, socket_timeout=5)
        try:
            print("\n--- redis guards ---")
            for label, k in [("opt-out", f"agent:optout:{conv.channel}:{key}"),
                             ("paused", f"agent:pause:{conv.channel}:{key}"),
                             ("guard pause", f"guard:pause:{conv.channel}:{key}"),
                             ("in flight", f"agent:inflight:{conv.channel}:{key}"),
                             ("hold line", f"agent:holdline:{conv.channel}:{key}"),
                             ("silenced", f"agent:silenced:{conv.channel}:{key}")]:
                v = await r.get(k)
                if v:
                    ttl = await r.ttl(k)
                    print(f"{label}: {v} (ttl {ttl}s)")
        finally:
            await r.aclose()
    except Exception as exc:
        print("redis not reachable:", type(exc).__name__)


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Why did Neema message this customer, or not?")
    ap.add_argument("handle", help="WhatsApp number (digits) or conversation id")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    asyncio.run(trace(args.handle, args.days))


if __name__ == "__main__":
    _cli()


async def collect(db, redis, handle: str, days: int = 7) -> dict | None:
    """The same facts as `trace()` prints, as JSON for the admin endpoint
    (routers/crm.py). The contact is masked in the heading; the thread text is
    included because the reader is an admin who can open the thread anyway.
    None when no conversation matches."""
    import importlib
    import pkgutil
    import app.models as models_pkg
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{mod.name}")
    from app.models.agent_action import AgentAction
    from app.models.conversation import Conversation
    from app.models.deal import Deal
    from app.models.intercept import Intercept
    from app.models.message import Message
    from app.models.person import Person
    from app.services.deals import team_check_open
    from app.services.intent import preferences

    since = datetime.now(timezone.utc) - timedelta(days=days)
    conv = None
    try:
        conv = await db.get(Conversation, uuid.UUID(handle))
    except (ValueError, AttributeError):
        pass
    if conv is None:
        conv = (await db.execute(select(Conversation).where(
            Conversation.wa_id == handle.lstrip("+")))).scalar_one_or_none()
    if conv is None:
        conv = (await db.execute(select(Conversation).where(
            Conversation.external_id == handle))).scalars().first()
    if conv is None:
        return None
    key = conv.wa_id or conv.external_id
    person = await db.get(Person, conv.person_id) if conv.person_id else None
    out: dict = {
        "conversation_id": str(conv.id), "channel": conv.channel, "contact": _mask(key),
        "mode": getattr(conv.intercept_mode, "value", conv.intercept_mode),
        "status": getattr(conv.status, "value", conv.status),
        "contact_preferences": preferences(person) if person is not None else {},
        "customer_state": ((person.state or {}).get("customer_state") if person is not None else None),
        "days": days, "deals": [], "thread": [], "actions": [], "flags": [], "redis": {},
    }
    deals = (await db.execute(select(Deal).where(Deal.conversation_id == conv.id)
                              .order_by(Deal.updated_at.desc()).limit(3))).scalars().all()
    for d in deals:
        out["deals"].append({"id": str(d.id), "status": d.status, "stage": d.stage, "title": d.title,
                             "team_check_open": team_check_open(d), "blocking": d.blocking,
                             "next_action": d.next_action})
    rows = (await db.execute(select(Message).where(
        Message.conversation_id == conv.id, Message.created_at >= since)
        .order_by(Message.created_at))).scalars().all()
    for m in rows:
        inbound = getattr(m.direction, "value", m.direction) == "inbound"
        out["thread"].append({
            "at": _fmt(m.created_at), "direction": "in" if inbound else "out",
            "sender": getattr(m.sender, "value", m.sender),
            "text": " ".join((m.text or "").split())[:300],
            "media_type": m.media_type,
            "origin": None if inbound else _origin(m),
            "delivery": None if inbound else (_delivery(m) or None),
            "waba_msg_id": bool(m.waba_msg_id),
        })
    acts = (await db.execute(select(AgentAction).where(
        AgentAction.conversation_id == conv.id)
        .order_by(AgentAction.created_at.desc()).limit(40))).scalars().all()
    for a in acts:
        out["actions"].append({"created": _fmt(a.created_at), "kind": a.kind, "status": a.status,
                               "due": _fmt(a.due_at), "source": a.source, "dedupe_key": a.dedupe_key,
                               "reason": " ".join((a.reason or "").split())[:300],
                               "has_draft": bool(a.draft)})
    flags = (await db.execute(select(Intercept).where(
        Intercept.conversation_id == conv.id,
        Intercept.created_at >= datetime.now(timezone.utc) - timedelta(days=30))
        .order_by(Intercept.created_at.desc()).limit(15))).scalars().all()
    for f in flags:
        out["flags"].append({"at": _fmt(f.created_at), "action": getattr(f.action, "value", f.action),
                             "note": " ".join((f.note or "").split())[:200]})
    if redis is not None:
        for label, k in [("opt_out", f"agent:optout:{conv.channel}:{key}"),
                         ("paused", f"agent:pause:{conv.channel}:{key}"),
                         ("guard_pause", f"guard:pause:{conv.channel}:{key}"),
                         ("in_flight", f"agent:inflight:{conv.channel}:{key}"),
                         ("hold_line", f"agent:holdline:{conv.channel}:{key}"),
                         ("silenced", f"agent:silenced:{conv.channel}:{key}")]:
            try:
                v = await redis.get(k)
                if v:
                    out["redis"][label] = {"value": v.decode() if isinstance(v, bytes) else str(v),
                                           "ttl": await redis.ttl(k)}
            except Exception:
                pass
    return out
