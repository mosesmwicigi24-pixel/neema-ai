"""The comments a credit outage left with a set reply — answered once, now.

Owner, 2026-11-26: "do a sweep of all flagged and not responded to … from
yesterday's credit outage. All messages responded to by set reply and not by
AI should be attended to. Ensure that all within the window are responded
to … not to repeat yourself."

On 2026-11-25 the AI account ran out of credit. Public comments heard a set
line ("one of our team will come back to you right here") and were flagged;
they were saved before a comment carried its reply state (services/
comment_ledger), so the sweep cannot see them. This finds them and writes
"owed" on them — nothing else. The ordinary sweep then does the rest, with
every guard it has: one combined reply per person per post under their
latest comment, no word about a delay, nothing under a deleted comment,
a colleague rung after a day.

Left alone, on purpose:
  * a person a colleague has replied to since — they have been attended to;
  * a person Neema has really answered since, under that post;
  * anything older than the 24-hour window — it stays with staff (it was
    flagged at the time);
  * private chats — the missed-reply sweeper already answers those when the
    model returns.

A one-off: it only ever looks at comments saved BEFORE `CUTOFF` (when the
reply state went live), so it stops by itself.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from app.services import comment_ledger as ledger

_log = logging.getLogger("neema.agent")

CUTOFF = datetime(2026, 11, 26, 5, 30, tzinfo=timezone.utc)   # comments saved after this carry their state
WINDOW_H = 24
LOOKBACK_H = 40
REASON = "outage"


def _norm(text: str) -> str:
    t = (text or "").lower().replace("hivi karibuni", " ").replace("shortly", " ")
    return " ".join(re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE).split())


_PATTERNS: list | None = None


def _patterns() -> list:
    """The set lines that only promise a person, as loose patterns: the
    name, the ask and the product are whatever they were."""
    global _PATTERNS
    if _PATTERNS is None:
        from app.agent import runtime as rt
        pools = (rt._NEUTRAL_ACK_POOL + rt._SW_NEUTRAL_ACK_POOL + rt._REQUEST_ACK_POOL
                 + rt._SW_REQUEST_ACK_POOL + rt._QUESTION_ACK_POOL + rt._SW_QUESTION_ACK_POOL
                 + rt._VERIFY_HOLD_POOL + rt._SW_VERIFY_HOLD_POOL
                 + rt._OVER_CAP_POOL + rt._SW_OVER_CAP_POOL)
        out = []
        for line in pools:
            parts = [_norm(p) for p in re.split(r"\{[a-z_]+\}", line)]
            parts = [re.escape(p) for p in parts if p]
            if parts:
                out.append(re.compile(r"^.*?" + r".*?".join(parts) + r".*$"))
        _PATTERNS = out
    return _PATTERNS


def is_set_reply(text: str) -> bool:
    """True for one of the stock lines sent when Neema could not answer."""
    t = _norm(text)
    return bool(t) and len(t) < 260 and any(p.match(t) for p in _patterns())


def _ts(v) -> float:
    if v is None:
        return 0.0
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.timestamp()


def select(rows: list, *, now: float, cutoff: float = CUTOFF.timestamp(),
           window_s: float = WINDOW_H * 3600) -> dict:
    """One commenter's rows (oldest first) → what to adopt. Pure.

    Each row: {dir, sender, cid, reply_to, post, text, at, has_state, note}.
    Returns {"adopt": {post_id: [comment ids]}, "skipped": {reason: n}}.
    """
    skipped = {"a_colleague_replied_since": 0, "neema_answered_since": 0, "older_than_the_window": 0}
    replies: dict = {}
    staff_at = 0.0
    for r in rows:
        if r.get("dir") != "outbound" or r.get("note"):
            continue
        if r.get("sender") == "human_agent":
            staff_at = max(staff_at, float(r.get("at") or 0))
        if r.get("reply_to"):
            replies.setdefault(str(r["reply_to"]), []).append(r)
    by_post: dict = {}
    for r in rows:
        if r.get("dir") == "inbound" and r.get("cid") and r.get("post"):
            by_post.setdefault(str(r["post"]), []).append(r)
    adopt: dict = {}
    for post, comments in by_post.items():
        kinds = []
        for c in comments:
            under = replies.get(str(c["cid"]), [])
            if any(u.get("sender") == "human_agent" for u in under):
                kind = "answered"
            elif any(not is_set_reply(u.get("text") or "") for u in under):
                kind = "answered"
            else:
                kind = "set" if under else "none"
            kinds.append(kind)
        firsts = [float(c["at"]) for c, k in zip(comments, kinds)
                  if k == "set" and not c.get("has_state") and float(c["at"]) <= cutoff]
        if not firsts:
            continue
        first = min(firsts)
        if staff_at > first:
            skipped["a_colleague_replied_since"] += 1
            continue
        if any(k == "answered" and float(c["at"]) >= first for c, k in zip(comments, kinds)):
            skipped["neema_answered_since"] += 1
            continue
        ids = [str(c["cid"]) for c, k in zip(comments, kinds)
               if k in ("set", "none") and not c.get("has_state")
               and first <= float(c["at"]) <= cutoff and now - float(c["at"]) <= window_s]
        if not ids:
            skipped["older_than_the_window"] += 1
            continue
        adopt[post] = ids
    return {"adopt": adopt, "skipped": skipped}


async def _commenters(since: datetime) -> list[tuple[str, str]]:
    """(channel, commenter) with a comment saved in the outage's stretch that
    carries no reply state."""
    from sqlalchemy import select as sel
    from app.database import AsyncSessionLocal
    from app.models.message import Message, MsgDirection
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            sel(Message.channel, Message.external_id).where(
                Message.direction == MsgDirection.inbound, Message.waba_msg_id.isnot(None),
                Message.comment_context.isnot(None),
                Message.created_at >= since, Message.created_at <= CUTOFF,
                Message.raw_meta[ledger.KEY]["state"].astext.is_(None))
            .distinct().limit(2000))).all()
    return [(str(c), str(e)) for c, e in rows if c and e]


async def _rows(channel: str, ext: str, since: datetime) -> list[dict]:
    from sqlalchemy import select as sel
    from app.database import AsyncSessionLocal
    from app.models.message import Message
    async with AsyncSessionLocal() as db:
        ms = (await db.execute(
            sel(Message).where(Message.channel == channel, Message.external_id == ext,
                               Message.created_at >= since)
            .order_by(Message.created_at.asc()).limit(400))).scalars().all()
    out = []
    for m in ms:
        ctx = m.comment_context if isinstance(m.comment_context, dict) else {}
        meta = m.raw_meta if isinstance(m.raw_meta, dict) else {}
        out.append({
            "dir": getattr(m.direction, "value", str(m.direction)),
            "sender": getattr(m.sender, "value", str(m.sender)),
            "cid": m.waba_msg_id, "reply_to": ctx.get("reply_to"), "post": ctx.get("post_id"),
            "text": m.text or "", "at": _ts(m.created_at),
            "has_state": bool((meta.get(ledger.KEY) or {}).get("state")),
            "note": m.media_type == "note"})
    return out


async def find(now: datetime | None = None) -> dict:
    """Everything the outage left with a set reply: who to adopt, and what
    was left alone and why. Reads only."""
    now = now or datetime.now(timezone.utc)
    since = min(now, CUTOFF) - timedelta(hours=LOOKBACK_H)
    keys, skipped = [], {"a_colleague_replied_since": 0, "neema_answered_since": 0,
                         "older_than_the_window": 0}
    for channel, ext in await _commenters(since):
        s = select(await _rows(channel, ext, since), now=now.timestamp())
        for k, v in s["skipped"].items():
            skipped[k] += v
        for post, ids in s["adopt"].items():
            keys.append({"channel": channel, "ext": ext, "post_id": post, "ids": ids})
    return {"keys": keys, "skipped": skipped}


async def _page_id(channel: str, ext: str):
    try:
        from sqlalchemy import select as sel
        from app.database import AsyncSessionLocal
        from app.models.person import Identity
        async with AsyncSessionLocal() as db:
            ident = (await db.execute(sel(Identity).where(
                Identity.channel == channel, Identity.external_id == ext))).scalar_one_or_none()
        return (getattr(ident, "raw_profile", None) or {}).get("page_id") if ident else None
    except Exception:
        return None


async def adopt(redis, *, limit: int = 200) -> int:
    """Write "owed" on the outage's comments. Returns how many comments were
    adopted. Stops by itself a day after the cutoff."""
    now = datetime.now(timezone.utc)
    if now > CUTOFF + timedelta(hours=WINDOW_H + 2):
        return 0
    try:
        found = await find(now)
    except Exception as exc:
        _log.info("outage backfill: nothing read this pass: %s", exc)
        return 0
    if not found["keys"]:
        return 0
    from app.routers.meta_webhook import _own_page_ids
    from app.services import comment_catchup as cc
    own = sorted(_own_page_ids())
    n = 0
    for k in found["keys"][:limit]:
        try:
            n += await ledger.mark(
                k["channel"], k["ext"], k["ids"], create=True, state=ledger.OWED, decided=True,
                reason=REASON, own_pages=own, page_id=await _page_id(k["channel"], k["ext"]),
                parent_id=None, post_id=k["post_id"])
            # they heard the set line yesterday: it is never said to them again
            await cc.hold_confirm(redis, cc.key_of(k["channel"], k["post_id"], k["ext"]))
        except Exception as exc:
            _log.info("outage backfill: %s not adopted: %s", k.get("post_id"), exc)
    if n:
        _log.info("outage backfill: %d comment(s) from the credit outage are now owed a reply "
                  "(%d commenter-posts; left alone: %s)", n, len(found["keys"][:limit]), found["skipped"])
    return n


async def counts() -> dict:
    """Counts only, for the owner: what the outage left and where it stands."""
    from sqlalchemy import func, select as sel
    from app.database import AsyncSessionLocal
    from app.models.intercept import Intercept
    from app.models.message import Message, MsgDirection
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=LOOKBACK_H)
    found = await find(now)
    state = Message.raw_meta[ledger.KEY]["state"].astext
    reason = Message.raw_meta[ledger.KEY]["reason"].astext
    by_state: dict = {}
    adopted: dict = {}
    async with AsyncSessionLocal() as db:
        for st, why in (await db.execute(
                sel(state, reason).where(
                    Message.direction == MsgDirection.inbound, Message.waba_msg_id.isnot(None),
                    Message.comment_context.isnot(None), Message.created_at >= since)
                .limit(20000))).all():
            by_state[st or "none"] = by_state.get(st or "none", 0) + 1
            if why == REASON:
                adopted[st or "none"] = adopted.get(st or "none", 0) + 1
        flags = (await db.execute(sel(func.count()).select_from(Intercept).where(
            Intercept.created_at >= since.replace(tzinfo=None),
            Intercept.note.like("%(no model)%")))).scalar() or 0
    dms = None
    try:
        from app.services.reply_sweeper import _unanswered_dms
        dms = len(await _unanswered_dms(now - timedelta(seconds=90), now - timedelta(hours=23), 500))
    except Exception:
        dms = None
    return {"hours_looked_back": LOOKBACK_H, "window_hours": WINDOW_H,
            "comments_by_reply_state": {str(k): int(v) for k, v in by_state.items()},
            "outage_comments_adopted_by_state_now": {str(k): int(v) for k, v in adopted.items()},
            "still_to_adopt": {"commenter_posts": len(found["keys"]),
                               "comments": sum(len(k["ids"]) for k in found["keys"])},
            "left_alone": found["skipped"],
            "no_model_flags_raised": int(flags),
            "messenger_instagram_chats_still_unanswered_within_23h": dms}
