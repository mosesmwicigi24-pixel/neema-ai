"""The WhatsApp call lifecycle: the one place a call's status moves, and the one
shape every client reads it in.

Statuses (models/call.py has the diagram):
  ringing    inbound ringing the team, or our outbound call ringing the customer
  answered   live
  completed  connected, now over          (legacy rows say `ended`)
  missed     inbound, nobody answered
  declined   inbound, an agent declined it
  callback   inbound, an agent declined it to call the customer back
  no_answer  outbound, the customer didn't pick up (or turned it down)
  cancelled  outbound, the agent hung up before the customer answered
  failed     outbound, the call could not be connected

Every transition is a conditional move from a live status, so a late or
repeated event (a Meta retry, two agents tapping at once, the stale sweep
racing the terminate webhook) can never rewrite a call that is already over.

Every change is also broadcast on `ws:channel:calls` ([publish]) so all agents'
phones and dashboards agree within a moment:
  incoming_call  {call_id, from, name, at, person_id, conversation_id}
  call_answered  {call_id, agent_id, agent_name, direction}
  call_ended     {call_id, outcome, status (Meta's raw, when it gave one),
                  duration, agent_id, agent_name, direction}
  call_update    {call: <row>}      recording / transcript / insights moved
  call_permission{wa_id, status, expires_at, permanent}

Best-effort throughout: a failure here must never break the call itself.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models.call import Call

_log = logging.getLogger("neema.wa")

CHANNEL = "ws:channel:calls"

LIVE = ("ringing", "answered")
TERMINAL = ("completed", "ended", "missed", "declined", "callback", "no_answer", "cancelled", "failed")
# Outcomes that leave the team owing the customer a call.
FOLLOW_UP = ("missed", "callback")
# A call still "ringing" this long never got its terminate event.
RING_STALE_AFTER = timedelta(minutes=2)
# Meta keeps a call-permission grant for 7 days unless it is permanent.
PERMISSION_TTL = 7 * 86400
PERMISSION_REQUESTED_TTL = 3 * 86400


def normalize_status(status: str | None) -> str:
    return "completed" if status == "ended" else (status or "ringing")


async def publish(redis, event: dict) -> None:
    """Tell every connected agent. Never raises."""
    if redis is None:
        return
    try:
        await redis.publish(CHANNEL, json.dumps(event, default=str))
    except Exception as exc:
        _log.warning("call event publish failed: %s", exc)


async def _agent_name(db, agent_id) -> str | None:
    if not agent_id:
        return None
    from app.models.agent import Agent
    return (await db.execute(select(Agent.name).where(Agent.id == agent_id))).scalar_one_or_none()


async def record_ringing(call_id: str, wa_id: str | None, name: str | None) -> dict:
    """Create the call row on `connect` (status=ringing). Resolves the person so
    the Calls view can link to the customer. Idempotent on call_id. Returns
    {person_id, conversation_id} for the ring event (empty on failure)."""
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c is None:
                person_id = None
                if wa_id:
                    from app.services.identity import resolve_person_id_for_wa_id
                    try:
                        person_id = await resolve_person_id_for_wa_id(db, wa_id, source="whatsapp_call")
                    except Exception:
                        person_id = None
                c = Call(call_id=call_id, wa_id=wa_id, caller_name=name,
                         status="ringing", person_id=person_id)
                db.add(c)
                await db.commit()
            conv = await conversation_ids_for(db, [c.wa_id] if c.wa_id else [])
            return {"person_id": str(c.person_id) if c.person_id else None,
                    "conversation_id": conv.get(c.wa_id or "")}
    except Exception as exc:
        _log.warning("call_log ringing failed: %s", exc)
        return {}


async def mark_answered(call_id: str, agent_id) -> dict | None:
    """ringing → answered. `agent_id` None (the customer answered OUR call) keeps
    the agent who placed it. Returns {agent_id, agent_name, direction} when this
    call moved, None when it was not ringing."""
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            values: dict = {"status": "answered", "answered_at": now}
            if agent_id is not None:
                values["agent_id"] = agent_id
            res = await db.execute(
                update(Call).where(Call.call_id == call_id, Call.status == "ringing")
                .values(**values).returning(Call.agent_id, Call.direction))
            row = res.first()
            await db.commit()
            if row is None:
                return None
            return {"agent_id": str(row.agent_id) if row.agent_id else None,
                    "agent_name": await _agent_name(db, row.agent_id),
                    "direction": row.direction}
    except Exception as exc:
        _log.warning("call_log answered failed: %s", exc)
        return None


async def _close(call_id: str, status: str, *, agent_id=None, duration: int | None = None,
                 only_if: tuple[str, ...] = LIVE) -> dict | None:
    """Move a live call to `status`. Returns the ended-event fields, or None when
    the call was not in `only_if` (already over, or unknown)."""
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(
                select(Call).where(Call.call_id == call_id).with_for_update())).scalar_one_or_none()
            if c is None or c.status not in only_if:
                return None
            c.ended_at = datetime.now(timezone.utc)
            if duration is not None:
                c.duration = int(duration)
            elif c.answered_at:
                c.duration = max(0, int((c.ended_at - c.answered_at).total_seconds()))
            c.status = status
            if agent_id is not None and status in ("declined", "callback", "cancelled"):
                c.agent_id = agent_id
            await db.commit()
            return {"call_id": call_id, "outcome": status,
                    "duration": c.duration, "direction": c.direction,
                    "agent_id": str(c.agent_id) if c.agent_id else None,
                    "agent_name": await _agent_name(db, c.agent_id),
                    "wa_id": c.wa_id}
    except Exception as exc:
        _log.warning("call_log close(%s) failed: %s", status, exc)
        return None


async def mark_declined(call_id: str, agent_id) -> dict | None:
    """An agent declined a ringing inbound call."""
    return await _close(call_id, "declined", agent_id=agent_id, only_if=("ringing",))


async def mark_callback(call_id: str, agent_id=None) -> dict | None:
    """The agent declined the ringing call to ring the customer back — an open
    follow-up in the Calls view."""
    return await _close(call_id, "callback", agent_id=agent_id, only_if=("ringing",))


async def mark_cancelled(call_id: str, agent_id=None) -> dict | None:
    """The agent hung up our outbound call before the customer answered."""
    return await _close(call_id, "cancelled", agent_id=agent_id, only_if=("ringing",))


async def mark_failed(call_id: str) -> dict | None:
    return await _close(call_id, "failed", only_if=("ringing",))


async def mark_ended(call_id: str, status: str | None = None, duration: int | None = None) -> dict | None:
    """Close the call on Meta's `terminate` (or our hang-up of a live call).
    Answered → completed; never answered → missed (inbound) / no_answer
    (outbound), unless `status` names one of our outcomes."""
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c is None or c.status not in LIVE:
                return None
            if c.answered_at or c.status == "answered":
                final = "completed"
            elif status in TERMINAL:
                final = status
            else:
                final = "no_answer" if c.direction == "outbound" else "missed"
    except Exception as exc:
        _log.warning("call_log ended failed: %s", exc)
        return None
    return await _close(call_id, final, duration=duration)


async def sweep_stale(db, redis=None) -> int:
    """Calls still ringing after [RING_STALE_AFTER] never got their terminate
    event: close them (missed / no_answer) and tell everyone, so no screen keeps
    ringing a call that is long gone. Returns how many were closed."""
    cutoff = datetime.now(timezone.utc) - RING_STALE_AFTER
    stale = (await db.execute(
        select(Call).where(Call.status == "ringing", Call.started_at < cutoff))).scalars().all()
    if not stale:
        return 0
    now = datetime.now(timezone.utc)
    events = []
    for s in stale:
        s.status = "no_answer" if s.direction == "outbound" else "missed"
        s.ended_at = now
        events.append({"type": "call_ended", "call_id": s.call_id, "outcome": s.status,
                       "duration": None, "direction": s.direction})
    await db.commit()
    for e in events:
        await publish(redis, e)
    return len(stale)


async def mark_follow_up_done(db, call_id: str) -> bool:
    c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
    if c is None:
        return False
    if c.follow_up_done_at is None:
        c.follow_up_done_at = datetime.now(timezone.utc)
        await db.commit()
    return True


# ── Reading ──────────────────────────────────────────────────────────────────

async def conversation_ids_for(db, wa_ids: list[str]) -> dict[str, str]:
    """wa_id → the customer's WhatsApp conversation id, for "open the chat"."""
    ids = sorted({w for w in wa_ids if w})
    if not ids:
        return {}
    from app.models.conversation import Conversation
    rows = (await db.execute(
        select(Conversation.id, Conversation.external_id)
        .where(Conversation.channel == "whatsapp", Conversation.external_id.in_(ids))
    )).all()
    return {r.external_id: str(r.id) for r in rows}


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def follow_up_open(c: Call, later_connected: set[tuple[str, datetime]] | None = None) -> bool:
    """A missed / callback call owes the customer a call until it is marked done
    or a later call with them connected."""
    if normalize_status(c.status) not in FOLLOW_UP or c.follow_up_done_at is not None:
        return False
    if later_connected and c.wa_id:
        for wa, at in later_connected:
            if wa == c.wa_id and c.started_at and at > c.started_at:
                return False
    return True


def serialize(c: Call, *, person=None, agent_name: str | None = None,
              conversation_id: str | None = None, follow_up: bool = False) -> dict:
    """The one row shape the Calls view, the phone and the thread read."""
    return {
        "id": str(c.id), "call_id": c.call_id, "wa_id": c.wa_id,
        "name": c.caller_name or (person.display_name if person is not None else None),
        "person_id": str(c.person_id) if c.person_id else None,
        "conversation_id": conversation_id,
        "channel": "whatsapp",
        "direction": c.direction or "inbound",
        "status": normalize_status(c.status),
        "duration": c.duration,
        "agent_id": str(c.agent_id) if c.agent_id else None,
        "agent_name": agent_name,
        "started_at": _iso(c.started_at),
        "answered_at": _iso(c.answered_at),
        "ended_at": _iso(c.ended_at),
        "summary": c.summary,
        "insights": c.insights,
        "transcript_status": c.transcript_status or "none",
        "has_recording": bool(c.recording_url),
        "follow_up_open": follow_up,
        "follow_up_done_at": _iso(c.follow_up_done_at),
    }


async def serialize_rows(db, rows: list[Call]) -> list[dict]:
    """[serialize] for many rows with their people, agents and chats batch-loaded."""
    from app.models.agent import Agent
    from app.models.person import Person
    person_ids = {c.person_id for c in rows if c.person_id}
    pmap = {}
    if person_ids:
        pmap = {p.id: p for p in (await db.execute(
            select(Person).where(Person.id.in_(person_ids)))).scalars().all()}
    agent_ids = {c.agent_id for c in rows if c.agent_id}
    amap = {}
    if agent_ids:
        amap = {a.id: a.name for a in (await db.execute(
            select(Agent).where(Agent.id.in_(agent_ids)))).scalars().all()}
    convs = await conversation_ids_for(db, [c.wa_id for c in rows if c.wa_id])
    # Later connected calls close a missed call's follow-up.
    wa_ids = {c.wa_id for c in rows if c.wa_id and normalize_status(c.status) in FOLLOW_UP}
    later: set = set()
    if wa_ids:
        later = {(r.wa_id, r.started_at) for r in (await db.execute(
            select(Call.wa_id, Call.started_at)
            .where(Call.wa_id.in_(wa_ids), Call.status.in_(("answered", "completed", "ended")))
        )).all() if r.started_at}
    return [serialize(c, person=pmap.get(c.person_id), agent_name=amap.get(c.agent_id),
                      conversation_id=convs.get(c.wa_id or ""),
                      follow_up=follow_up_open(c, later)) for c in rows]


async def row(db, call_id: str) -> dict | None:
    c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
    if c is None:
        return None
    return (await serialize_rows(db, [c]))[0]


async def publish_update(redis, call_id: str) -> None:
    """Broadcast a call's current row (recording / transcript / insights moved)."""
    if redis is None:
        return
    try:
        async with AsyncSessionLocal() as db:
            r = await row(db, call_id)
        if r is not None:
            await publish(redis, {"type": "call_update", "call": r})
    except Exception as exc:
        _log.warning("call update publish failed: %s", exc)


# ── Call permission (WhatsApp: a business may call only someone who allowed it) ──

def _perm_key(wa_id: str) -> str:
    return f"wa:call:perm:{wa_id}"


async def permission(redis, wa_id: str) -> dict:
    """{status: granted | denied | requested | unknown, expires_at, permanent}.
    `unknown` means we have never asked: a call may still go through (the
    customer may have allowed it in WhatsApp) — the connect answer is the truth."""
    out = {"wa_id": wa_id, "status": "unknown", "expires_at": None, "permanent": False}
    if redis is None or not wa_id:
        return out
    try:
        raw = await redis.get(_perm_key(wa_id))
    except Exception:
        return out
    if not raw:
        return out
    try:
        data = json.loads(raw)
    except Exception:
        return out
    out.update({k: data.get(k, out[k]) for k in ("status", "expires_at", "permanent")})
    exp = out.get("expires_at")
    if out["status"] == "granted" and exp and not out["permanent"]:
        try:
            if datetime.fromisoformat(exp) <= datetime.now(timezone.utc):
                out.update(status="unknown", expires_at=None)
        except Exception:
            pass
    return out


async def set_permission(redis, wa_id: str, status: str, *, expires_at: datetime | None = None,
                         permanent: bool = False) -> dict:
    data = {"wa_id": wa_id, "status": status, "permanent": permanent,
            "expires_at": _iso(expires_at),
            "at": datetime.now(timezone.utc).isoformat()}
    if redis is not None and wa_id:
        ttl = PERMISSION_REQUESTED_TTL if status == "requested" else PERMISSION_TTL
        if status == "granted" and expires_at is not None and not permanent:
            ttl = max(60, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
        if status == "granted" and permanent:
            ttl = 365 * 86400
        try:
            await redis.set(_perm_key(wa_id), json.dumps(data), ex=ttl)
        except Exception as exc:
            _log.warning("call permission store failed: %s", exc)
    return data


async def note_permission_reply(redis, wa_id: str, reply: dict) -> dict | None:
    """A customer's answer to our call-permission request (the interactive
    `call_permission_reply` message). Stores it and tells every agent."""
    if not wa_id or not isinstance(reply, dict):
        return None
    granted = str(reply.get("response") or "").lower() in ("accept", "accepted", "allow", "allowed")
    permanent = bool(reply.get("is_permanent"))
    expires = None
    ts = reply.get("expiration_timestamp")
    if granted and ts and not permanent:
        try:
            expires = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except Exception:
            expires = None
    if granted and expires is None and not permanent:
        expires = datetime.now(timezone.utc) + timedelta(seconds=PERMISSION_TTL)
    data = await set_permission(redis, wa_id, "granted" if granted else "denied",
                                expires_at=expires, permanent=permanent)
    await publish(redis, {"type": "call_permission", **data})
    return data
