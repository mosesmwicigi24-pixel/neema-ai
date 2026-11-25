"""One holding line, then one answer (owner, 2026-11-25).

When Neema cannot answer a public comment — the AI account is out of credit,
the turn failed, the reviewer held the draft, a cap was reached — the thread
heard the same stock line under every comment the person wrote: "Thank you
for reaching out … one of our team will come back to you" four times in
twenty minutes. That is the machine talking, and it tells the customer
nobody is reading.

So, per person per post:

  * THE HOLDING LINE IS SAID ONCE — and counted as said only when Meta took
    it. A short claim stops two sends at once; a send Meta REFUSED frees the
    claim so the next comment (or the sweep) may try again. A send whose
    outcome is UNKNOWN (the request left and no answer came back) may have
    posted: it is never resent, and a colleague is told to look.
  * WHAT THEY WROTE IS KEPT BY ID ONLY — the comment's id, when, and why it
    had no answer. Its words stay in the database and are read from there
    each time, so a deleted comment (a customer's data-deletion request) is
    gone from here too, and nothing is answered that no longer exists.
  * ONE ANSWER LATER. When the model can answer, everything outstanding is
    read together and answered in one reply under their latest comment. One
    claim is shared by the live handler and the sweep, so only one of them
    composes it. The ids are cleared only after the reply LANDS, and only
    the ids it covered: a comment that arrived meanwhile stays, a refused
    post keeps them all, an unknown outcome hands them to a colleague.
  * A COLLEAGUE'S REPLY ANSWERS THE COMMENT IT WAS MADE TO, and no other:
    not another post's, not the other questions under this one.
  * STAFF SEE EVERY UNANSWERED COMMENT IN ONE PLACE: one follow-up on the
    conversation's timeline, rewritten as comments arrive, saying plainly
    when Neema will not answer by herself, and closed when none is left.

Redis only for the waiting state, best-effort: with no redis the old
behaviour stands (the line goes out, the team is flagged per comment).
"""
from __future__ import annotations

import json
import logging
import time

_log = logging.getLogger("neema.agent")

WINDOW_S = 24 * 3600            # how long a comment may wait for the one answer
MIN_AGE_S = 90                  # let the live path finish before the sweep looks
CLAIM_S = 120                   # a holding-line send in flight
ANSWER_CLAIM_S = 180            # one composer of the combined reply at a time
BACKOFF_S = 600                 # between the sweep's tries for one person
MAX_TRIES = 3                   # failed catch-up answers before it is a colleague's
_INDEX = "comment:catchup:index"
MODEL = "model"                 # why a comment had no answer: the model call failed …
CAP = "cap"                     # … a cap stopped the call …
REVIEW = "review"               # … or the reviewer held the draft
UNKNOWN_WHY = ("a reply may already have posted — Meta did not confirm it; "
               "check the thread before answering")


def key_of(channel: str, post_id, ext) -> str:
    return f"{channel}:{post_id}:{ext}"


def post_of(comment: dict) -> str:
    return str(comment.get("post_id") or (comment.get("post_context") or {}).get("post_id") or "")


def _said(key: str) -> str:
    return f"comment:hold_said:{key}"


def _claim(key: str) -> str:
    return f"comment:hold_claim:{key}"


def _queue(key: str) -> str:
    return f"comment:catchup:q:{key}"


def _staff(key: str) -> str:
    return f"comment:catchup:staff:{key}"


def _tries(key: str) -> str:
    return f"comment:catchup:tries:{key}"


def _follow(key: str) -> str:
    return f"comment:catchup:followup:{key}"


def _answering(key: str) -> str:
    return f"comment:catchup:claim:{key}"


def _backoff(key: str) -> str:
    return f"comment:catchup:backoff:{key}"


def _s(v) -> str:
    return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)


# ── the holding line: claimed, sent, then counted ────────────────────────────
async def hold_state(redis, key: str) -> str:
    """"send" — say the line now (the caller holds the claim and must
    `hold_confirm` or `hold_release`); "said" — they have it; "busy" — a send
    is in flight elsewhere. No redis → "send", as before."""
    if redis is None:
        return "send"
    try:
        if await redis.get(_said(key)):
            return "said"
        return "send" if await redis.set(_claim(key), "1", nx=True, ex=CLAIM_S) else "busy"
    except Exception:
        return "send"


async def hold_confirm(redis, key: str) -> None:
    """Meta took the line — or MAY have (an unknown outcome): it is said, for
    the window, and never sent again."""
    if redis is None:
        return
    try:
        await redis.set(_said(key), "1", ex=WINDOW_S)
        await redis.delete(_claim(key))
    except Exception:
        pass


async def hold_release(redis, key: str) -> None:
    """Meta REFUSED the send: free the claim so it may be tried again."""
    if redis is None:
        return
    try:
        await redis.delete(_claim(key))
    except Exception:
        pass


# ── one composer of the combined reply ───────────────────────────────────────
async def claim_answer(redis, key: str) -> bool:
    """The live handler and the sweep share this: whoever holds it composes
    the one reply; the other leaves the waiting comments alone."""
    if redis is None:
        return False
    try:
        return bool(await redis.set(_answering(key), "1", nx=True, ex=ANSWER_CLAIM_S))
    except Exception:
        return False


async def release_answer(redis, key: str) -> None:
    if redis is None:
        return
    try:
        await redis.delete(_answering(key))
    except Exception:
        pass


# ── what is waiting: ids, never words ────────────────────────────────────────
async def _rows(redis, key: str) -> list[tuple[str, dict]]:
    out = []
    for raw in await redis.lrange(_queue(key), 0, -1):
        try:
            out.append((_s(raw), json.loads(raw)))
        except ValueError:
            continue
    return out


async def keep(redis, channel: str, comment: dict, own_pages, reason: str) -> bool:
    """Keep a comment that had no answer — its id and where it sits, never
    its words or the commenter's name. Idempotent by comment id."""
    post_id, ext = post_of(comment), str(comment.get("from_id") or "")
    cid = str(comment.get("comment_id") or "")
    if redis is None or not (post_id and ext and cid):
        return False
    key = key_of(channel, post_id, ext)
    try:
        if any(str(i.get("cid")) == cid for _r, i in await _rows(redis, key)):
            return True
        item = {"at": time.time(), "cid": cid, "reason": reason,
                "own_pages": sorted(own_pages or []), "post_id": post_id,
                "page_id": comment.get("page_id"), "parent_id": comment.get("parent_id")}
        await redis.rpush(_queue(key), json.dumps(item, default=str))
        await redis.expire(_queue(key), WINDOW_S)
        await redis.sadd(_INDEX, key)          # AFTER the push: see `resolve`
        return True
    except Exception as exc:
        _log.info("comment catch-up: could not keep %s: %s", cid, exc)
        return False


async def waiting_ids(redis, key: str) -> list[dict]:
    """The kept ids, oldest first ([] on any doubt)."""
    if redis is None:
        return []
    try:
        return [i for _r, i in await _rows(redis, key)]
    except Exception:
        return []


async def load_records(channel: str, ext: str, ids) -> dict:
    """The comments as the database holds them NOW: {comment id → {"text",
    "post_context"}}. An id with no row is a comment that was deleted."""
    ids = [str(i) for i in (ids or []) if i]
    if not ids:
        return {}
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.message import Message, MsgDirection
    out = {}
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Message.waba_msg_id, Message.text, Message.comment_context, Message.raw_meta)
            .where(Message.channel == channel, Message.external_id == ext,
                   Message.direction == MsgDirection.inbound,
                   Message.waba_msg_id.in_(ids)))).all()
    for cid, text, ctx, meta in rows:
        wordless = isinstance(meta, dict) and meta.get("kind") == "comment_media"
        out[str(cid)] = {"text": "" if wordless else (text or ""),
                         "post_context": ctx if isinstance(ctx, dict) else {}}
    return out


def hydrate(channel: str, ext: str, items: list, records: dict) -> tuple[list, list]:
    """Kept ids + their records → (items carrying the comment to answer, the
    ids whose record is gone). Pure."""
    live, gone = [], []
    for i in items:
        rec = records.get(str(i.get("cid")))
        if rec is None:
            gone.append(str(i.get("cid")))
            continue
        ctx = dict(rec.get("post_context") or {})
        live.append(dict(i, comment={
            "comment_id": str(i.get("cid")), "from_id": ext, "text": rec.get("text") or "",
            "post_id": i.get("post_id") or ctx.get("post_id"), "page_id": i.get("page_id"),
            "parent_id": i.get("parent_id"), "post_context": ctx}))
    return live, gone


async def waiting(redis, key: str) -> list[dict]:
    """The kept comments WITH their words, read from the database now. A
    comment whose record is gone is dropped here, for good."""
    items = await waiting_ids(redis, key)
    if not items:
        return []
    channel, _post, ext = key.split(":", 2)
    try:
        records = await load_records(channel, ext, [i.get("cid") for i in items])
    except Exception as exc:
        _log.info("comment catch-up: records unreadable for %s: %s", key, exc)
        return []                               # unreadable is not "deleted": keep the ids, say nothing
    live, gone = hydrate(channel, ext, items, records)
    if gone:
        _log.info("comment catch-up: %d kept comment(s) no longer exist — dropped", len(gone))
        await resolve(redis, key, gone)
    return live


async def resolve(redis, key: str, ids) -> int:
    """These comment ids are done with: remove exactly them. Returns how many
    are still kept.

    Race-free without a transaction: only the named values are removed (a
    comment pushed meanwhile is never touched — the list itself is never
    deleted), the count is read AFTER the removal, and the index entry is
    put back if a comment arrived between the count and its removal (`keep`
    adds to the index after it pushes)."""
    if redis is None:
        return 0
    ids = {str(i) for i in (ids or [])}
    try:
        for raw, item in await _rows(redis, key):
            if str(item.get("cid")) in ids:
                await redis.lrem(_queue(key), 0, raw)
        left = int(await redis.llen(_queue(key)) or 0)
        if not left:
            await redis.delete(_said(key), _staff(key), _tries(key), _backoff(key))
            await redis.srem(_INDEX, key)
            if int(await redis.llen(_queue(key)) or 0):
                await redis.sadd(_INDEX, key)
        return left
    except Exception as exc:
        _log.info("comment catch-up: resolve failed for %s: %s", key, exc)
        return 0


async def staff_only(redis, key: str) -> float:
    """The instant up to which the kept comments are a colleague's (0 = none)."""
    if redis is None:
        return 0.0
    try:
        return float(_s(await redis.get(_staff(key)) or 0))
    except Exception:
        return 0.0


async def hand_to_staff(redis, key: str) -> None:
    """Everything kept so far is a colleague's: no more automatic tries."""
    if redis is None:
        return
    try:
        await redis.set(_staff(key), str(time.time()), ex=WINDOW_S)
        await redis.delete(_tries(key))
    except Exception:
        pass


async def tried(redis, key: str) -> int:
    """Count one failed catch-up answer; returns the count so far."""
    if redis is None:
        return MAX_TRIES
    try:
        n = int(await redis.incr(_tries(key)))
        await redis.expire(_tries(key), WINDOW_S)
        return n
    except Exception:
        return MAX_TRIES


def plan(items: list, *, now: float | None = None, staff_cut: float = 0.0,
         min_age: float = MIN_AGE_S) -> dict:
    """What to do with one person's kept comments under one post. Pure.

      expired — ids past the window
      answer  — the ONE comment to answer (the latest, with `catch_up` = every
                outstanding text oldest first and `catch_up_ids`), or None:
                nothing eligible, a colleague's by `staff_cut`, or the newest
                is too fresh for the live path to have finished
      outstanding — what is still unanswered
    """
    now = time.time() if now is None else now
    live, expired = [], []
    for i in items:
        if not (isinstance(i, dict) and isinstance(i.get("comment"), dict)):
            continue
        if now - float(i.get("at") or 0) > WINDOW_S:
            expired.append(str(i.get("cid")))
        else:
            live.append(i)
    out = {"expired": expired, "outstanding": live, "answer": None}
    # an automatic answer needs a comment whose MODEL call failed, newer than
    # anything already handed to a colleague
    eligible = [i for i in live if i.get("reason") == MODEL and float(i.get("at") or 0) > staff_cut]
    if not eligible or now - float(live[-1].get("at") or 0) < min_age:
        return out
    said, ids, seen = [], [], set()
    for i in live:
        ids.append(str(i.get("cid")))
        t = " ".join(str(i["comment"].get("text") or "").split())
        if t and t.lower() not in seen:           # the same words sent twice are read once
            seen.add(t.lower())
            said.append(t)
    if not said:
        return out
    last = dict(live[-1]["comment"])
    last["catch_up"], last["catch_up_ids"], last["catch_up_claimed"] = said, ids, True
    out["answer"] = {"comment": last, "own_pages": set(live[-1].get("own_pages") or [])}
    return out


def catch_up_prompt(said: list[str]) -> str:
    """What the model is handed in place of one comment's words."""
    if len(said) == 1:
        return said[0]
    lines = "\n".join(f"{n}. {t}" for n, t in enumerate(said, 1))
    return ("(This person wrote several comments under this post before we could answer. "
            "Read them TOGETHER as one request and give ONE reply that answers all of it — "
            "what they are asking for is in THEIR words, even where the post shows another item. "
            "Do not answer them one by one, do not mention any delay or technical problem, "
            "and do not repeat a thank-you they already heard.)\n" + lines)


# ── a colleague replied to ONE comment ───────────────────────────────────────
async def staff_replied(redis, channel: str, ext: str, comment_id) -> bool:
    """A colleague's public reply went out under `comment_id`: that comment —
    and only that one — is answered. Other posts, and this person's other
    questions under the same post, stay waiting. True when it was a kept one."""
    cid = str(comment_id or "")
    if redis is None or not (cid and ext):
        return False
    try:
        keys = [_s(k) for k in await redis.smembers(_INDEX)]
    except Exception:
        return False
    for key in keys:
        if not (key.startswith(channel + ":") and key.endswith(":" + str(ext))):
            continue
        if any(str(i.get("cid")) == cid for i in await waiting_ids(redis, key)):
            await resolve(redis, key, [cid])
            left = await waiting(redis, key)
            cut = await staff_only(redis, key)
            auto = any(i.get("reason") == MODEL and float(i.get("at") or 0) > cut for i in left)
            await followup(redis, channel, str(ext), key, left,
                           CLOSED if not left else (WAITING if auto else STAFF))
            return True
    return False


# ── the one follow-up staff see ──────────────────────────────────────────────
WAITING, STAFF, CLOSED = "waiting", "staff", "closed"


def followup_note(items: list, state: str, why: str = "") -> str:
    """The follow-up's words. Pure."""
    if state == CLOSED or not items:
        return "PUBLIC COMMENTS — answered. No comment from this person is waiting under this post."
    lines = "\n".join(f"{n}. {' '.join(str(i['comment'].get('text') or '').split())[:300]}"
                      for n, i in enumerate(items, 1))
    head = (f"PUBLIC COMMENTS WAITING FOR AN ANSWER ({len(items)}) — this person was told a "
            "colleague will come back to them, once.")
    if state == STAFF:
        tail = ("Neema will NOT answer these by herself" + (f" ({why})" if why else "") +
                ": a colleague must reply in the thread.")
    else:
        tail = ("Neema will answer them together, in one reply, as soon as she can. "
                "A colleague's reply under one of them answers that one.")
        if why:
            tail += f" NOTE: {why}."
    return f"{head}\n{lines}\n{tail}"


async def followup(redis, channel: str, ext: str, key: str, items: list, state: str,
                   why: str = "") -> str | None:
    """Write (or rewrite) the ONE follow-up for this person under this post on
    the conversation's timeline. Returns "new" when it was just created (the
    team is rung), "updated", or None when it could not be written."""
    if redis is None:
        return None
    try:
        import uuid
        from sqlalchemy import select
        from app.database import AsyncSessionLocal
        from app.models.conversation import Conversation
        from app.models.intercept import Intercept, InterceptAction
        note = followup_note(items, state, why)
        fid = await redis.get(_follow(key))
        async with AsyncSessionLocal() as db:
            row = None
            if fid:
                try:
                    row = await db.get(Intercept, uuid.UUID(_s(fid)))
                except Exception:
                    row = None
            if row is None:
                if state == CLOSED or not items:
                    return None                       # nothing was ever opened
                conv = (await db.execute(select(Conversation).where(
                    Conversation.channel == channel,
                    Conversation.external_id == ext))).scalar_one_or_none()
                if conv is None:
                    return None
                row = Intercept(id=uuid.uuid4(), conversation_id=conv.id,
                                action=InterceptAction.flag, note=note)
                db.add(row)
                await db.commit()
                await redis.set(_follow(key), str(row.id), ex=WINDOW_S * 2)
                try:
                    await redis.publish("ws:channel:agents:all", json.dumps({
                        "event": "notification", "type": "draft_ready",
                        "title": f"{channel.title()} comment needs you",
                        "body": "A commenter is waiting for an answer Neema could not give.",
                        "conv_id": str(conv.id), "wa_id": ext}))
                except Exception:
                    pass
                return "new"
            row.note = note
            await db.commit()
        if state == CLOSED or not items:
            await redis.delete(_follow(key))
        return "updated"
    except Exception as exc:
        _log.info("comment follow-up not written for %s: %s", key, exc)
        return None


# ── the sweep ────────────────────────────────────────────────────────────────
async def sweep(redis, *, limit: int = 15) -> int:
    """Answer what was kept, once the model can answer; while it cannot, say
    the holding line that Meta refused earlier. Returns how many people it
    tried to answer."""
    if redis is None:
        return 0
    from app.services.agent_health import ai_down
    try:
        down = bool(await ai_down(redis))
        keys = [_s(k) for k in list(await redis.smembers(_INDEX))[:200]]
    except Exception:
        return 0
    done = 0
    for key in keys:
        if done >= limit:
            break
        try:
            channel, _post_id, ext = key.split(":", 2)
            if not await waiting_ids(redis, key):
                await resolve(redis, key, [])          # an empty wait: tidy the index
                continue
            from app.agent import runtime as rt
            items = await waiting(redis, key)          # words read from the database now
            p = plan(items, staff_cut=await staff_only(redis, key))
            if p["expired"]:
                # a day has gone by: a colleague's, said so on the follow-up
                gone = [i for i in items if str(i.get("cid")) in set(p["expired"])]
                await followup(redis, channel, ext, key, gone + p["outstanding"], STAFF,
                               "more than a day has passed")
                await resolve(redis, key, p["expired"])
            if not p["outstanding"]:
                continue
            if down:
                # still cannot answer: make sure they heard the one line
                if await hold_state(redis, key) == "send":
                    last = p["outstanding"][-1]
                    sent = await rt._post_hold_ack(redis, channel, last["comment"],
                                                   set(last.get("own_pages") or []))
                    if sent is False:                  # Meta refused: may be tried again
                        await hold_release(redis, key)
                    else:                              # landed, or unknown: never resent
                        await hold_confirm(redis, key)
                        if sent is None:
                            await followup(redis, channel, ext, key, p["outstanding"], WAITING,
                                           "the holding line may or may not have posted — "
                                           "Meta did not confirm it")
                continue
            if p["answer"] is None:
                continue
            if await redis.get(_backoff(key)) or not await claim_answer(redis, key):
                continue                               # tried lately, or the live handler has it
            try:
                await redis.set(_backoff(key), "1", ex=BACKOFF_S)
                await rt._run_comment_engage(redis, channel, p["answer"]["comment"],
                                             p["answer"]["own_pages"])
                done += 1
            finally:
                await release_answer(redis, key)
        except Exception as exc:
            _log.warning("comment catch-up failed for %s: %s", key, exc)
    if done:
        _log.info("comment catch-up: tried %d waiting commenter(s)", done)
    return done
