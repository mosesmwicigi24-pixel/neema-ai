"""Who owes this comment a reply — written on the comment itself.

Third review, 2026-11-25. Two ways a commenter could be lost even with the
reply logic right:

  * the webhook saved a comment and THEN scheduled its reply in memory: a
    restart in that gap left a comment in the inbox that nothing would ever
    answer or recover;
  * the waiting state lived in Redis with a 24-hour life: when it ran out the
    comment silently left recovery while the staff timeline still read
    "Neema will answer".

So the state is durable and lives where the comment does: the inbound
comment's own row (`messages.raw_meta["reply"]`), keyed by the comment id the
row already carries. The live handler, the sweep and the staff follow-up all
read and write THIS:

    owed     — Neema owes a reply (stamped by the webhook in the same commit
               that saves the comment; `decided` turns true once the handler
               has looked at it and it still has no answer)
    staff    — a colleague owns it, with why (a cap, the reviewer, three
               failed tries, a day gone by)
    verify   — a reply may have posted; Meta did not confirm it
    resolved — answered (by Neema, by a colleague), deliberately left
               unanswered by the handler, or no longer needed

Redis only schedules attempts (claims, back-off, the said-once mark). Nothing
here expires: a comment leaves `owed` only by a recorded decision.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

_log = logging.getLogger("neema.agent")

OWED, STAFF, VERIFY, RESOLVED = "owed", "staff", "verify", "resolved"
OPEN = (OWED, STAFF, VERIFY)
KEY = "reply"                    # raw_meta["reply"]


def opening(own_pages=None, page_id=None, parent_id=None, post_id=None) -> dict:
    """What the webhook stamps on a comment as it saves it. The post id is
    the webhook's own — the enriched post context is looked up separately and
    can fail, and a comment must be found for recovery either way."""
    return {"state": OWED, "decided": False, "own_pages": sorted(own_pages or []),
            "page_id": page_id, "parent_id": parent_id,
            "post_id": str(post_id) if post_id else None}


def _post_col():
    """The comment's post: the webhook's id on the reply state, else the one
    in the enriched context (rows saved before the state carried it)."""
    from sqlalchemy import func
    from app.models.message import Message
    return func.coalesce(Message.raw_meta[KEY]["post_id"].astext,
                         Message.comment_context["post_id"].astext)


def _block(meta) -> dict | None:
    b = meta.get(KEY) if isinstance(meta, dict) else None
    return b if isinstance(b, dict) and b.get("state") else None


def _row(m) -> dict:
    b = _block(m.raw_meta) or {}
    ctx = m.comment_context if isinstance(m.comment_context, dict) else {}
    at = m.created_at
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    wordless = isinstance(m.raw_meta, dict) and m.raw_meta.get("kind") == "comment_media"
    return {"cid": str(m.waba_msg_id), "at": at.timestamp() if at else 0.0,
            "state": b.get("state"), "decided": bool(b.get("decided")),
            "reason": b.get("reason") or "", "why": b.get("why") or "",
            "followup": b.get("followup"), "own_pages": list(b.get("own_pages") or []),
            "page_id": b.get("page_id"), "parent_id": b.get("parent_id"),
            "post_id": str(b.get("post_id") or ctx.get("post_id") or ""),
            "text": "" if wordless else (m.text or ""), "post_context": dict(ctx)}


def _comments(channel: str, ext: str):
    from sqlalchemy import select
    from app.models.message import Message, MsgDirection
    return select(Message).where(
        Message.channel == channel, Message.external_id == ext,
        Message.direction == MsgDirection.inbound, Message.waba_msg_id.isnot(None))


async def mark(channel: str, ext: str, ids, *, create: bool = False,
               only_undecided: bool = False, **fields) -> int:
    """Merge `fields` into the reply state of these comment ids. Rows with no
    state are left alone unless `create` (a comment saved before the state
    existed). `only_undecided`: touch only comments the handler has not yet
    decided on. Returns how many rows changed."""
    ids = [str(i) for i in (ids or []) if i]
    if not ids:
        return 0
    from app.database import AsyncSessionLocal
    from app.models.message import Message
    n = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(_comments(channel, ext).where(
            Message.waba_msg_id.in_(ids)))).scalars().all()
        for m in rows:
            b = _block(m.raw_meta)
            if b is None and not create:
                continue
            if only_undecided and (b is None or b.get("decided") or b.get("state") != OWED):
                continue
            meta = dict(m.raw_meta) if isinstance(m.raw_meta, dict) else {}
            meta[KEY] = {**(b or {}), **fields, "at": datetime.now(timezone.utc).isoformat()}
            m.raw_meta = meta                      # a new dict: JSONB change is seen
            n += 1
        if n:
            await db.commit()
    return n


async def unresolved(channel: str, ext: str, post_id: str, *, days: float = 3.0) -> list[dict]:
    """This person's comments under this post that are not resolved, oldest
    first, with their words as the database holds them now."""
    from app.database import AsyncSessionLocal
    from app.models.message import Message
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            _comments(channel, ext).where(
                Message.created_at >= since,
                Message.raw_meta[KEY]["state"].astext.in_(OPEN),
                _post_col() == str(post_id))
            .order_by(Message.created_at.asc()).limit(60))).scalars().all()
    return [_row(m) for m in rows]


async def keys_owed(*, days: float = 3.0, limit: int = 300) -> list[tuple[str, str, str]]:
    """(channel, commenter, post) for every comment Neema still owes."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.message import Message, MsgDirection
    since = datetime.now(timezone.utc) - timedelta(days=days)
    post = _post_col()
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Message.channel, Message.external_id, post).where(
                Message.direction == MsgDirection.inbound, Message.created_at >= since,
                Message.waba_msg_id.isnot(None),
                Message.raw_meta[KEY]["state"].astext == OWED)
            .distinct().limit(limit))).all()
    return [(str(c), str(e), str(p)) for c, e, p in rows if c and e and p]


async def state_of(channel: str, ext: str, cid) -> dict | None:
    """One comment's reply state, or None when it carries none (or is gone)."""
    from app.database import AsyncSessionLocal
    from app.models.message import Message
    async with AsyncSessionLocal() as db:
        m = (await db.execute(_comments(channel, ext).where(
            Message.waba_msg_id == str(cid)).limit(1))).scalar_one_or_none()
    return _row(m) if m is not None and _block(m.raw_meta) else None


async def existing(channel: str, ext: str, ids) -> set:
    """Which of these comment ids still have a record."""
    ids = [str(i) for i in (ids or []) if i]
    if not ids:
        return set()
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.message import Message, MsgDirection
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Message.waba_msg_id).where(
            Message.channel == channel, Message.external_id == ext,
            Message.direction == MsgDirection.inbound,
            Message.waba_msg_id.in_(ids)))).all()
    return {str(r[0]) for r in rows}


async def replied_ids(channel: str, ext: str, ids, *, staff_only: bool = False) -> set:
    """Which of these comments already have a public reply threaded under
    them (`comment_context.reply_to`) — by a colleague only, or by anyone."""
    ids = {str(i) for i in (ids or []) if i}
    if not ids:
        return set()
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.message import Message, MsgDirection, MsgSender
    q = select(Message.comment_context, Message.raw_meta).where(
        Message.channel == channel, Message.external_id == ext,
        Message.direction == MsgDirection.outbound,
        Message.comment_context.isnot(None),
        Message.media_type.is_(None) | (Message.media_type != "note"))
    if staff_only:
        q = q.where(Message.sender == MsgSender.human_agent)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(q.order_by(Message.created_at.desc()).limit(300))).all()
    return {str((r[0] or {}).get("reply_to")) for r in rows
            if isinstance(r[0], dict)
            and not (isinstance(r[1], dict) and r[1].get("delivery") == "unknown")} & ids


async def followup_id(channel: str, ext: str, post_id: str, *, days: float = 3.0) -> str | None:
    """The id of this person's one follow-up under this post, if one was opened."""
    from app.database import AsyncSessionLocal
    from app.models.message import Message
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            _comments(channel, ext).where(
                Message.created_at >= since,
                _post_col() == str(post_id),
                Message.raw_meta[KEY]["followup"].astext.isnot(None))
            .order_by(Message.created_at.desc()).limit(1))).scalars().all()
    for m in rows:
        fid = (_block(m.raw_meta) or {}).get("followup")
        if fid:
            return str(fid)
    return None
