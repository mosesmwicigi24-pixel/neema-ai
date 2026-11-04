"""Ask the colleague who holds a chat to hand it over (owner, 2026-11-04).

Only the super admin may take a chat someone else holds. Everyone else asks:
"a button that can request the other person who is holding that chat to
release it to this person. If that is granted on the other end, then that
will be transferred to this new person."

  ask      → one open request per chat; the holder (and the team) is told.
  accept   → the holder (or the super admin) hands it over: an ordinary
             transfer to the person who asked, noted in the timeline.
  decline  → the holder keeps it; the person who asked is told.

A request nobody answers lapses after HANDOVER_TTL, and the super admin can
always take the chat over meanwhile. A request also lapses the moment the chat
is no longer held by the person it was put to (released, transferred, taken
over).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models.agent import Agent
from app.models.conversation import Conversation, InterceptMode
from app.models.handover_request import HandoverRequest

HANDOVER_TTL = timedelta(hours=2)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(ts: datetime | None) -> datetime | None:
    if ts is not None and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def is_open(req: HandoverRequest | None, conv: Conversation | None) -> bool:
    """Pending, not lapsed, and the chat is still held by the person asked."""
    if req is None or conv is None or req.status != "pending":
        return False
    created = _aware(req.created_at)
    if created is not None and _now() - created > HANDOVER_TTL:
        return False
    return (conv.intercept_mode == InterceptMode.human
            and conv.assigned_agent_id is not None
            and str(conv.assigned_agent_id) == str(req.holder_agent_id))


def shape(req: HandoverRequest, from_name: str | None) -> dict:
    return {
        "id": str(req.id),
        "from_agent_id": str(req.from_agent_id),
        "from_agent_name": from_name or "A colleague",
        "holder_agent_id": str(req.holder_agent_id) if req.holder_agent_id else None,
        "at": _aware(req.created_at).isoformat() if req.created_at else None,
    }


async def open_requests(db, convs) -> dict[str, dict]:
    """{conversation id: request} for the chats in this page that have one open."""
    held = {str(c.id): c for c in convs
            if c.intercept_mode == InterceptMode.human and c.assigned_agent_id}
    if not held:
        return {}
    rows = (await db.execute(
        select(HandoverRequest, Agent.name)
        .join(Agent, Agent.id == HandoverRequest.from_agent_id, isouter=True)
        .where(HandoverRequest.conversation_id.in_(list(held)),
               HandoverRequest.status == "pending",
               HandoverRequest.created_at >= _now() - HANDOVER_TTL)
        .order_by(HandoverRequest.created_at.desc()))).all()
    out: dict[str, dict] = {}
    for req, name in rows:
        cid = str(req.conversation_id)
        if cid not in out and is_open(req, held.get(cid)):
            out[cid] = shape(req, name)
    return out


async def _conv(db, conv_id) -> Conversation:
    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


async def _latest_open(db, conv) -> HandoverRequest | None:
    req = (await db.execute(
        select(HandoverRequest)
        .where(HandoverRequest.conversation_id == conv.id, HandoverRequest.status == "pending")
        .order_by(HandoverRequest.created_at.desc()).limit(1))).scalar_one_or_none()
    return req if is_open(req, conv) else None


async def _notify(redis, conv, title: str, body: str, **extra) -> None:
    if not redis:
        return
    from app.services.n8n_bridge import _broadcast
    # "transfer" — both apps already refetch the inbox for it and file it under
    # the hand-over notification setting.
    await _broadcast(redis, "agents:all", {
        "event": "notification", "type": "transfer", "title": title, "body": body,
        "conversationId": str(conv.id), **extra,
    })


def _who(conv) -> str:
    return conv.wa_id or conv.external_id or "a customer"


async def ask(db, conv_id, agent, redis=None) -> dict:
    conv = await _conv(db, conv_id)
    if not (conv.intercept_mode == InterceptMode.human and conv.assigned_agent_id):
        raise HTTPException(status_code=400, detail="Nobody holds this chat — pick it up instead.")
    if str(conv.assigned_agent_id) == str(agent.id):
        raise HTTPException(status_code=400, detail="You already have this chat.")
    holder = await db.get(Agent, conv.assigned_agent_id)
    holder_name = holder.name if holder else "the agent"
    existing = await _latest_open(db, conv)
    if existing is not None:
        if str(existing.from_agent_id) == str(agent.id):
            return {"ok": True, "already": True, "request": shape(existing, agent.name)}
        asker = await db.get(Agent, existing.from_agent_id)
        raise HTTPException(status_code=409,
                            detail=f"{asker.name if asker else 'A colleague'} has already asked "
                                   f"{holder_name} for this chat.")
    req = HandoverRequest(conversation_id=conv.id, from_agent_id=agent.id,
                          holder_agent_id=conv.assigned_agent_id, status="pending",
                          created_at=_now())
    db.add(req)
    await db.commit()
    await _notify(redis, conv, f"🤝 {agent.name} asks {holder_name} for a chat",
                  f"{holder_name}: hand over the chat with {_who(conv)}, or keep it — "
                  f"open the chat to answer.",
                  forAgentId=str(conv.assigned_agent_id), fromAgentId=str(agent.id))
    return {"ok": True, "request": shape(req, agent.name)}


async def _answerable(db, conv_id, agent, request_id) -> tuple[Conversation, HandoverRequest]:
    conv = await _conv(db, conv_id)
    req = await _latest_open(db, conv)
    if req is None or (request_id and str(req.id) != str(request_id)):
        raise HTTPException(status_code=409, detail="That request has lapsed or was already answered.")
    if str(conv.assigned_agent_id) != str(agent.id) and not getattr(agent, "is_superuser", False):
        raise HTTPException(status_code=403,
                            detail="Only the person holding this chat (or the super admin) can answer.")
    return conv, req


async def accept(db, conv_id, agent, request_id=None, redis=None) -> dict:
    conv, req = await _answerable(db, conv_id, agent, request_id)
    asker = await db.get(Agent, req.from_agent_id)
    if asker is None:
        raise HTTPException(status_code=409, detail="The person who asked is no longer on the team.")
    from app.services.conversation import transfer_conversation
    # The holder hands it over (or the super admin, whose override this is):
    # the transfer first, so a failed one leaves the request open.
    out = await transfer_conversation(db, str(conv.id), agent, str(asker.id), redis)
    req.status, req.answered_at, req.answered_by = "accepted", _now(), agent.id
    await db.commit()
    await _notify(redis, conv, f"🤝 {agent.name} handed a chat to {asker.name}",
                  f"The chat with {_who(conv)} is now {asker.name}'s.",
                  forAgentId=str(asker.id))
    return {"ok": True, "transferred_to": str(asker.id), "transfer": out}


async def decline(db, conv_id, agent, request_id=None, redis=None) -> dict:
    conv, req = await _answerable(db, conv_id, agent, request_id)
    asker = await db.get(Agent, req.from_agent_id)
    req.status, req.answered_at, req.answered_by = "declined", _now(), agent.id
    await db.commit()
    asker_name = asker.name if asker else "The colleague"
    await _notify(redis, conv, f"{agent.name} is keeping a chat",
                  f"{asker_name}: {agent.name} is still handling the chat with {_who(conv)}.",
                  forAgentId=str(req.from_agent_id))
    return {"ok": True, "declined": True}


async def timeline_events(db, conv_id) -> list[dict]:
    """The asks and answers on this chat, for the thread's timeline."""
    rows = (await db.execute(
        select(HandoverRequest).where(HandoverRequest.conversation_id == conv_id)
        .order_by(HandoverRequest.created_at.desc()).limit(20))).scalars().all()
    if not rows:
        return []
    ids = {r.from_agent_id for r in rows} | {r.holder_agent_id for r in rows if r.holder_agent_id} \
        | {r.answered_by for r in rows if r.answered_by}
    names = {str(a.id): a.name for a in (await db.execute(
        select(Agent).where(Agent.id.in_(list(ids))))).scalars().all()}
    out = []
    for r in rows:
        asker = names.get(str(r.from_agent_id), "A colleague")
        holder = names.get(str(r.holder_agent_id), "the agent")
        out.append({"id": f"handover-{r.id}", "at": _aware(r.created_at),
                    "label": f"{asker} asked {holder} to hand over this chat", "agent": asker})
        if r.status == "declined" and r.answered_at:
            who = names.get(str(r.answered_by), holder)
            out.append({"id": f"handover-{r.id}-no", "at": _aware(r.answered_at),
                        "label": f"{who} kept the chat", "agent": who})
    return out
