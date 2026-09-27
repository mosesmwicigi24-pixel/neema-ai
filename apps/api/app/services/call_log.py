"""The call lifecycle (WhatsApp, and Messenger when enabled): the one place a
call's status moves, and the one shape every client reads it in.

A row's `channel` says which platform carried it. WhatsApp rows key the
customer by `wa_id`; Messenger rows leave `wa_id` NULL and key them by the PSID
in `external_id`. Everything below is channel-blind except where it says so.

Statuses (models/call.py has the diagram):
  ringing    inbound ringing the team, or our outbound call ringing the customer
  answered   live
  completed  connected, now over          (legacy rows say `ended`)
  missed     inbound, nobody answered
  declined   inbound, an agent declined it
  callback   inbound, an agent declined it to call the customer back
  no_answer  outbound, the customer didn't pick up
  rejected   outbound, the customer declined our call (Meta's REJECTED status)
  cancelled  outbound, the agent hung up before the customer answered
  failed     outbound, the call could not be connected

Every transition is a conditional move from a live status, so a late or
repeated event (a Meta retry, two agents tapping at once, the stale sweep
racing the terminate webhook) can never rewrite a call that is already over.

Every change is also broadcast on `ws:channel:calls` ([publish]) so all agents'
phones and dashboards agree within a moment:
  incoming_call  {call_id, from, name, at, channel}
  call_answered  {call_id, agent_id, agent_name, direction}
  call_ended     {call_id, outcome, status (Meta's raw, when it gave one),
                  duration, agent_id, agent_name, direction}
  call_update    {call: <row>}      recording / transcript / insights moved
  call_permission{wa_id, status, expires_at, permanent, revoked}
                 (Messenger: wa_id null, channel "messenger", external_id = PSID)
  call_status    {call_id, status: "ringing"}   the customer's phone is ringing
  call_settings  {value}                         Meta says calling settings changed
  calling_restricted {event, reasons, value}     Meta restricted / flagged calling

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
TERMINAL = ("completed", "ended", "missed", "declined", "callback", "no_answer", "rejected",
            "cancelled", "failed")
# Outbound outcomes WhatsApp counts toward auto-revoking a permission (4 in a row).
UNANSWERED = ("no_answer", "rejected")
CONNECTED = ("answered", "completed", "ended")
# Outcomes that leave the team owing the customer a call.
FOLLOW_UP = ("missed", "callback")
# A call still "ringing" this long never got its terminate event.
RING_STALE_AFTER = timedelta(minutes=2)
# Meta keeps a call-permission grant for 7 days unless it is permanent.
PERMISSION_TTL = 7 * 86400
# A request expires 7 days after delivery with no answer.
PERMISSION_REQUESTED_TTL = 7 * 86400
# Meta's permission answer is cached briefly; a failed read is not retried for a moment.
PERMISSION_META_TTL = 60
PERMISSION_META_FAIL_TTL = 15


def normalize_status(status: str | None) -> str:
    return "completed" if status == "ended" else (status or "ringing")


MESSENGER = "messenger"


def perm_key(channel: str | None, wa_id: str | None = None, external_id: str | None = None) -> str:
    """The permission-store key: the number for WhatsApp, `messenger:<psid>`
    for Messenger (so the two never collide)."""
    if channel == MESSENGER:
        return f"{MESSENGER}:{external_id}" if external_id else ""
    return wa_id or ""


def _who(c) -> tuple[str, str] | None:
    """(channel, handle) of the customer on a call row — handle = wa_id or PSID."""
    ch = getattr(c, "channel", None) or "whatsapp"
    h = c.external_id if ch == MESSENGER else c.wa_id
    return (ch, h) if h else None


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


async def messenger_person_id(db, psid: str | None):
    """The person behind a Messenger PSID (created on first sight, like an
    inbound DM does). None when it can't be resolved."""
    if not psid:
        return None
    from app.services.identity import resolve_or_create_person
    try:
        ident = await resolve_or_create_person(db, MESSENGER, psid, source="messenger_call",
                                               confidence="deterministic")
        return ident.person_id
    except Exception:
        await db.rollback()
        return None


async def record_ringing(call_id: str, wa_id: str | None, name: str | None, *,
                         channel: str = "whatsapp", external_id: str | None = None) -> dict:
    """Create the call row on `connect` (status=ringing). Resolves the person so
    the Calls view can link to the customer. Idempotent on call_id. Returns
    {person_id, conversation_id} for the ring event (empty on failure)."""
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c is None:
                person_id = None
                if channel == MESSENGER:
                    person_id = await messenger_person_id(db, external_id)
                elif wa_id:
                    from app.services.identity import resolve_person_id_for_wa_id
                    try:
                        person_id = await resolve_person_id_for_wa_id(db, wa_id, source="whatsapp_call")
                    except Exception:
                        person_id = None
                c = Call(call_id=call_id, wa_id=wa_id, caller_name=name,
                         status="ringing", person_id=person_id, channel=channel or "whatsapp",
                         external_id=external_id)
                db.add(c)
                await db.commit()
            who = _who(c)
            conv = await conversation_ids_by_channel(db, [who] if who else [])
            return {"person_id": str(c.person_id) if c.person_id else None,
                    "conversation_id": conv.get(who) if who else None}
    except Exception as exc:
        _log.warning("call_log ringing failed: %s", exc)
        return {}


async def known_call(call_id: str) -> bool:
    """Whether this call is already logged — a `connect` for it is a redelivery.
    False when the database can't say (ringing beats staying silent)."""
    try:
        async with AsyncSessionLocal() as db:
            return (await db.execute(
                select(Call.id).where(Call.call_id == call_id))).first() is not None
    except Exception:
        return False


async def mark_answered(call_id: str, agent_id, redis=None) -> dict | None:
    """ringing → answered. `agent_id` None (the customer answered OUR call) keeps
    the agent who placed it. Returns {agent_id, agent_name, direction} when this
    call moved, None when it was not ringing. A connected call resets Meta's
    permission-request limits, so the cached permission answer is dropped."""
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            values: dict = {"status": "answered", "answered_at": now}
            if agent_id is not None:
                values["agent_id"] = agent_id
            res = await db.execute(
                update(Call).where(Call.call_id == call_id, Call.status == "ringing")
                .values(**values).returning(Call.agent_id, Call.direction, Call.wa_id,
                                            Call.channel, Call.external_id))
            row = res.first()
            await db.commit()
            if row is None:
                return None
            await forget_meta_permission(redis, perm_key(row.channel, row.wa_id, row.external_id))
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


async def mark_rejected(call_id: str) -> dict | None:
    """The customer declined our outbound call (Meta's REJECTED status). Also
    corrects a `no_answer` written by a terminate that beat the status."""
    return await _close(call_id, "rejected", only_if=("ringing", "no_answer"))


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
    ringing a call that is long gone. Returns how many were closed.

    Only `ringing` rows are touched — a live answered call is never swept — and
    each move is a conditional UPDATE, so an answer landing in the same instant
    wins instead of being overwritten. Cheap when nothing is stale (one indexed
    lookup on status)."""
    cutoff = datetime.now(timezone.utc) - RING_STALE_AFTER
    now = datetime.now(timezone.utc)
    events = []
    for direction, outcome in (("outbound", "no_answer"), (None, "missed")):
        cond = [Call.status == "ringing", Call.started_at < cutoff]
        cond.append(Call.direction == "outbound" if direction else
                    (Call.direction.is_(None) | (Call.direction != "outbound")))
        res = await db.execute(
            update(Call).where(*cond).values(status=outcome, ended_at=now)
            .returning(Call.call_id, Call.direction))
        for r in res.all():
            events.append({"type": "call_ended", "call_id": r.call_id, "outcome": outcome,
                           "duration": None, "direction": r.direction})
    if not events:
        await db.rollback()
        return 0
    await db.commit()
    for e in events:
        await publish(redis, e)
        if e.get("outcome") == "missed":
            from app.services import missed_call
            missed_call.schedule(redis, e["call_id"])
    return len(events)


# ── Webhooks that beat the row (Meta does not promise order) ─────────────────
# A `terminate` can land before the `connect` it closes, and the customer's
# answer to OUR call can land before /calls/connect has written its row. The
# event is parked here and applied the moment the row exists, so no call is
# left "ringing" (or rings a phone) after it is already over.

EARLY_TTL = 600


def _early_key(kind: str, call_id: str) -> str:
    return f"wa:call:early:{kind}:{call_id}"


async def note_early(redis, kind: str, call_id: str, data: dict | None = None) -> None:
    """Park an event (`answer` / `end`) for a call whose row isn't written yet."""
    if redis is None or not call_id:
        return
    data = dict(data or {})
    try:
        if kind == "end" and "outcome" not in data:
            # Meta's terminate after its REJECTED status: keep "rejected".
            prev = await redis.get(_early_key(kind, call_id))
            if prev and json.loads(prev).get("outcome"):
                data["outcome"] = json.loads(prev)["outcome"]
        await redis.set(_early_key(kind, call_id), json.dumps(data), ex=EARLY_TTL)
    except Exception as exc:
        _log.warning("call early-event park failed: %s", exc)


async def _take_early(redis, kind: str, call_id: str) -> dict | None:
    if redis is None:
        return None
    try:
        raw = await redis.get(_early_key(kind, call_id))
        if raw is None:
            return None
        await redis.delete(_early_key(kind, call_id))
        return json.loads(raw) if raw else {}
    except Exception:
        return None


async def ended_before_ring(redis, call_id: str) -> dict | None:
    """The parked terminate for a call whose `connect` came after it, if any."""
    if redis is None:
        return None
    try:
        raw = await redis.get(_early_key("end", call_id))
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def apply_early(redis, call_id: str) -> None:
    """The row now exists: replay any answer / terminate that arrived first,
    and tell everyone (the placing phone reads the row and follows)."""
    ans = await _take_early(redis, "answer", call_id)
    if ans is not None:
        moved = await mark_answered(call_id, None, redis)
        if moved is not None:
            await publish(redis, {"type": "call_answered", "call_id": call_id, **moved})
    end = await _take_early(redis, "end", call_id)
    if end is not None:
        info = await mark_ended(call_id, status=end.get("outcome"), duration=end.get("duration"))
        if info is not None:
            info.pop("wa_id", None)
            await publish(redis, {"type": "call_ended", **info, "status": end.get("status")})


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


async def conversation_ids_by_channel(db, pairs) -> dict[tuple[str, str], str]:
    """(channel, handle) → the customer's conversation id on that channel."""
    want = {(ch, h) for ch, h in (p for p in pairs if p) if h}
    if not want:
        return {}
    from app.models.conversation import Conversation
    out: dict[tuple[str, str], str] = {}
    for ch in {ch for ch, _ in want}:
        ids = sorted(h for c2, h in want if c2 == ch)
        rows = (await db.execute(
            select(Conversation.id, Conversation.external_id)
            .where(Conversation.channel == ch, Conversation.external_id.in_(ids))
        )).all()
        out.update({(ch, r.external_id): str(r.id) for r in rows})
    return out


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def follow_up_open(c: Call, later_connected: set[tuple[str, datetime]] | None = None) -> bool:
    """A missed / callback call owes the customer a call until it is marked done
    or a later call with them connected."""
    if normalize_status(c.status) not in FOLLOW_UP or c.follow_up_done_at is not None:
        return False
    who = _who(c)
    if later_connected and who:
        for key, at in later_connected:
            if key in (who, who[1]) and c.started_at and at > c.started_at:
                return False
    return True


def serialize(c: Call, *, person=None, agent_name: str | None = None,
              conversation_id: str | None = None, follow_up: bool = False) -> dict:
    """The one row shape the Calls view, the phone and the thread read."""
    return {
        "id": str(c.id), "call_id": c.call_id, "wa_id": c.wa_id,
        "external_id": getattr(c, "external_id", None) or c.wa_id,
        "name": c.caller_name or (person.display_name if person is not None else None),
        "person_id": str(c.person_id) if c.person_id else None,
        "conversation_id": conversation_id,
        "channel": getattr(c, "channel", None) or "whatsapp",
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
        "has_voicemail": bool(getattr(c, "voicemail_message_id", None)),
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
    convs = await conversation_ids_by_channel(db, [_who(c) for c in rows])
    # Later connected calls (same customer, same channel) close a missed call's follow-up.
    owed = {_who(c) for c in rows if _who(c) and normalize_status(c.status) in FOLLOW_UP}
    later: set = set()
    wa_ids = {h for ch, h in owed if ch != MESSENGER}
    psids = {h for ch, h in owed if ch == MESSENGER}
    if wa_ids:
        later |= {(("whatsapp", r.wa_id), r.started_at) for r in (await db.execute(
            select(Call.wa_id, Call.started_at)
            .where(Call.wa_id.in_(wa_ids), Call.status.in_(("answered", "completed", "ended")))
        )).all() if r.started_at}
    if psids:
        later |= {((MESSENGER, r.external_id), r.started_at) for r in (await db.execute(
            select(Call.external_id, Call.started_at)
            .where(Call.channel == MESSENGER, Call.external_id.in_(psids),
                   Call.status.in_(("answered", "completed", "ended")))
        )).all() if r.started_at}
    return [serialize(c, person=pmap.get(c.person_id), agent_name=amap.get(c.agent_id),
                      conversation_id=convs.get(_who(c)) if _who(c) else None,
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


# ── Outbound rows: written by /calls/connect or, when Meta is faster, by the
# first webhook that carries our `biz_opaque_callback_data` ──────────────────

async def upsert_outbound(call_id: str, wa_id: str | None, *, agent_id=None, name: str | None = None,
                          person_id=None, channel: str = "whatsapp",
                          external_id: str | None = None) -> bool:
    """Create our outbound row if it isn't there yet; fill blanks if it is.
    Safe against the webhook and the route racing (INSERT … ON CONFLICT).
    Returns True when this call created the row."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    import uuid as _uuid
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                pg_insert(Call).values(
                    id=_uuid.uuid4(), call_id=call_id, wa_id=wa_id, caller_name=name,
                    direction="outbound", status="ringing", person_id=person_id,
                    agent_id=agent_id, started_at=datetime.now(timezone.utc),
                    transcript_status="none", channel=channel or "whatsapp",
                    external_id=external_id)
                .on_conflict_do_nothing(index_elements=["call_id"]).returning(Call.id))
            created = res.first() is not None
            if not created:
                c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
                if c is not None:
                    c.wa_id = c.wa_id or wa_id
                    c.external_id = c.external_id or external_id
                    c.caller_name = c.caller_name or name
                    c.person_id = c.person_id or person_id
                    c.agent_id = c.agent_id or agent_id
            await db.commit()
            return created
    except Exception as exc:
        _log.warning("call_log outbound upsert failed: %s", exc)
        return False


async def row_from_opaque(call_id: str, wa_id: str | None, raw_opaque) -> bool:
    """A status / connect / terminate webhook for OUR call beat /calls/connect's
    row: write it from the opaque data (the agent who placed it is kept).
    False when the data isn't ours or the row already exists."""
    from app.services.wa_calling import parse_opaque
    data = parse_opaque(raw_opaque)
    if not data or not call_id:
        return False
    agent_id = None
    try:
        import uuid as _uuid
        agent_id = _uuid.UUID(str(data.get("agent_id"))) if data.get("agent_id") else None
    except ValueError:
        agent_id = None
    if await known_call(call_id):
        return False
    return await upsert_outbound(call_id, wa_id, agent_id=agent_id)


async def unanswered_streak(db, wa_id: str) -> int:
    """Our latest outbound calls to this customer that went unanswered or were
    rejected, since their last connected call (either direction). WhatsApp
    nudges the customer at 2 and revokes the permission at 4."""
    if not wa_id:
        return 0
    from sqlalchemy import func
    last_connected = (await db.execute(
        select(func.max(Call.started_at)).where(Call.wa_id == wa_id, Call.status.in_(CONNECTED))
    )).scalar_one_or_none()
    q = select(func.count()).select_from(Call).where(
        Call.wa_id == wa_id, Call.direction == "outbound", Call.status.in_(UNANSWERED))
    if last_connected is not None:
        q = q.where(Call.started_at > last_connected)
    return int((await db.execute(q)).scalar_one() or 0)


async def in_service_window(db, wa_id: str) -> bool:
    """Inside WhatsApp's 24 h customer-service window: their last inbound
    WhatsApp message, or their last inbound call (answered or not — Meta's
    pricing: an inbound call opens / refreshes the window), within 24 h."""
    if not wa_id:
        return False
    from sqlalchemy import func, or_
    from app.models.message import Message, MsgDirection
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    last_msg = (await db.execute(
        select(func.max(Message.created_at)).where(
            Message.direction == MsgDirection.inbound,
            Message.channel == "whatsapp",
            or_(Message.wa_id == wa_id, Message.external_id == wa_id))
    )).scalar_one_or_none()
    if last_msg is not None:
        if last_msg.tzinfo is None:
            last_msg = last_msg.replace(tzinfo=timezone.utc)
        if last_msg >= since:
            return True
    last_call = (await db.execute(
        select(func.max(Call.started_at)).where(
            Call.wa_id == wa_id,
            Call.direction.is_(None) | (Call.direction != "outbound"))
    )).scalar_one_or_none()
    if last_call is not None:
        if last_call.tzinfo is None:
            last_call = last_call.replace(tzinfo=timezone.utc)
        return last_call >= since
    return False


async def link_voicemail(redis, call_id: str, message_id: str, wa_id: str | None) -> bool:
    """A voicemail (inbound audio whose id is the call's WACID) → its call row.
    A voicemail for a call we never logged still gets a (missed) row so the
    Calls view shows it — and a late `connect` for it then never rings."""
    try:
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c is None:
                now = datetime.now(timezone.utc)
                c = Call(call_id=call_id, wa_id=wa_id, direction="inbound", status="missed",
                         ended_at=now, voicemail_message_id=message_id)
                db.add(c)
            elif c.voicemail_message_id == message_id:
                return False
            else:
                c.voicemail_message_id = message_id
            await db.commit()
    except Exception as exc:
        _log.warning("call_log voicemail link failed: %s", exc)
        return False
    await publish_update(redis, call_id)
    return True


# ── Call permission (WhatsApp: a business may call only someone who allowed it) ──
# Meta's `GET call_permissions` is the truth (cached ~60 s); our own store —
# what we asked and what the customer replied — fills in what Meta can't say
# (requested, declined) and stands in when Meta can't be reached.

def _perm_key(wa_id: str) -> str:
    return f"wa:call:perm:{wa_id}"


def _meta_key(wa_id: str) -> str:
    return f"wa:call:permmeta:{wa_id}"


def _meta_fail_key(wa_id: str) -> str:
    return f"wa:call:permmeta:fail:{wa_id}"


async def forget_meta_permission(redis, wa_id: str | None) -> None:
    """Drop the cached Meta answer (a reply / connected call just changed it)."""
    if redis is None or not wa_id:
        return
    try:
        await redis.delete(_meta_key(wa_id))
        await redis.delete(_meta_fail_key(wa_id))
    except Exception:
        pass


async def stored_permission(redis, wa_id: str) -> dict:
    """Our own record: {status: granted | denied | requested | unknown,
    expires_at, permanent, revoked, requested_at}."""
    out = {"wa_id": wa_id, "status": "unknown", "expires_at": None, "permanent": False,
           "revoked": False, "requested_at": None}
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
    out.update({k: data.get(k, out[k]) for k in ("status", "expires_at", "permanent", "revoked")})
    if out["status"] == "requested":
        out["requested_at"] = data.get("at")
    exp = out.get("expires_at")
    if out["status"] == "granted" and exp and not out["permanent"]:
        try:
            if datetime.fromisoformat(exp) <= datetime.now(timezone.utc):
                out.update(status="unknown", expires_at=None)
        except Exception:
            pass
    return out


def _store_shape(st: dict) -> dict:
    """The enriched fields, derived from our store alone (Meta unreachable)."""
    status = st["status"]
    return {"wa_id": st["wa_id"], "status": status, "expires_at": st["expires_at"],
            "permanent": bool(st["permanent"]), "revoked": bool(st.get("revoked")),
            "meta_status": None, "can_call": status in ("granted", "unknown"),
            "can_request": status in ("unknown", "denied"),
            "request_available_at": None, "calls_left_today": None, "source": "store"}


async def cached_meta_permission(redis, wa_id: str) -> dict | None:
    """Meta's answer if we hold a fresh one — never asks Meta."""
    if redis is None or not wa_id:
        return None
    try:
        raw = await redis.get(_meta_key(wa_id))
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _meta_permission(redis, wa_id: str) -> dict | None:
    """Meta's normalised answer, cache-first. None when Meta can't say."""
    from app.services import wa_calling
    if redis is not None:
        try:
            raw = await redis.get(_meta_key(wa_id))
            if raw:
                return json.loads(raw)
            if await redis.get(_meta_fail_key(wa_id)):
                return None
        except Exception:
            pass
    try:
        if wa_id.startswith(MESSENGER + ":"):
            from app.services import messenger_calling
            meta = await messenger_calling.get_call_permission(wa_id.split(":", 1)[1])
        else:
            meta = await wa_calling.get_call_permission(wa_id)
    except Exception as exc:
        _log.warning("call permission read from Meta failed for %s: %s", wa_id, exc)
        if redis is not None:
            try:
                await redis.set(_meta_fail_key(wa_id), "1", ex=PERMISSION_META_FAIL_TTL)
            except Exception:
                pass
        return None
    if redis is not None:
        try:
            await redis.set(_meta_key(wa_id), json.dumps(meta), ex=PERMISSION_META_TTL)
        except Exception:
            pass
    return meta


async def permission(redis, wa_id: str, *, ask_meta: bool = True) -> dict:
    """{status: granted | denied | requested | unknown, expires_at, permanent,
    meta_status, can_call, can_request, request_available_at, calls_left_today,
    revoked, source: meta | store}.
    `unknown` = nobody knows of a permission: a call may still go through."""
    st = await stored_permission(redis, wa_id)
    meta = await _meta_permission(redis, wa_id) if (ask_meta and wa_id) else None
    if meta is None:
        return _store_shape(st)
    out = {"wa_id": wa_id, **meta, "revoked": False, "source": "meta"}
    if meta["status"] != "granted":
        # Meta: no permission. Our store knows whether we asked or they said no.
        if st["status"] == "denied":
            out.update(status="denied", revoked=bool(st.get("revoked")))
        elif st["status"] == "requested" and st.get("requested_at"):
            try:
                at = datetime.fromisoformat(st["requested_at"])
                if datetime.now(timezone.utc) - at < timedelta(seconds=PERMISSION_REQUESTED_TTL):
                    out["status"] = "requested"
            except Exception:
                pass
    return out


async def set_permission(redis, wa_id: str, status: str, *, expires_at: datetime | None = None,
                         permanent: bool = False, revoked: bool = False) -> dict:
    data = {"wa_id": wa_id, "status": status, "permanent": permanent,
            "expires_at": _iso(expires_at), "revoked": revoked,
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
        await forget_meta_permission(redis, wa_id)
    return data


async def note_permission_reply(redis, wa_id: str, reply: dict, *,
                                channel: str = "whatsapp") -> dict | None:
    """A customer's answer to our call-permission request (the interactive
    `call_permission_reply` message), a grant from their business profile, or
    WhatsApp's automatic revoke after 4 unanswered calls
    (`response: reject, response_source: automatic`). Stores it and tells
    every agent. Messenger (`channel="messenger"`, `wa_id` = the PSID): the
    `call_permission_reply` webhook, `response: approve | reject`, stored under
    `messenger:<psid>`."""
    if not wa_id or not isinstance(reply, dict):
        return None
    messenger = channel == MESSENGER
    psid = wa_id
    if messenger:
        wa_id = perm_key(MESSENGER, external_id=psid)
    ok = ("approve", "approved") if messenger else ("accept", "accepted", "allow", "allowed")
    granted = str(reply.get("response") or "").lower() in ok
    revoked = (not granted) and str(reply.get("response_source") or "").lower() == "automatic"
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
                                expires_at=expires, permanent=permanent, revoked=revoked)
    if messenger:
        data = messenger_permission_shape(data, psid)
    event = {"type": "call_permission", **data}
    if revoked:
        event["reason"] = "automatic"
    await publish(redis, event)
    return data


def messenger_permission_shape(data: dict, psid: str) -> dict:
    """A permission record / answer stored under `messenger:<psid>`, as clients
    read it: no wa_id, the channel and the PSID instead."""
    return {**data, "wa_id": None, "channel": MESSENGER, "external_id": psid}
