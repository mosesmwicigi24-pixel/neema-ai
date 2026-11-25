"""One holding line, then one answer (owner, 2026-11-25).

When Neema cannot answer a public comment — the AI account is out of credit,
the turn failed, the reviewer held the draft, a cap was reached — the thread
heard the same stock line under every comment the person wrote: "Thank you
for reaching out … one of our team will come back to you" four times in
twenty minutes. That is the machine talking, and it tells the customer
nobody is reading.

So, per person per post:

  * THE HOLDING LINE IS SAID ONCE — and counted as said only when Meta took
    it. A short claim stops two sends at once; a refused send frees the claim
    so the next comment (or the sweep) may try again.
  * WHAT THEY WROTE IS KEPT, by comment id, with why it had no answer. Every
    later comment while it is still waiting gets the Page's Like and no words.
  * ONE ANSWER LATER. When the model can answer, everything outstanding is
    read together and answered in one reply under their latest comment. The
    kept comments are cleared only after that reply LANDS, and only the ids
    it covered: a comment that arrived meanwhile stays, a refused post keeps
    them all for the next pass.
  * A COLLEAGUE WHO ANSWERED FIRST HAS ANSWERED. Comments older than a staff
    reply in that thread are theirs and are dropped, never answered twice.
  * STAFF SEE EVERY UNANSWERED COMMENT IN ONE PLACE: one follow-up on the
    conversation's timeline, rewritten as comments arrive, saying plainly
    when Neema will not answer by herself (a cap, the reviewer, three failed
    tries, a day gone by), and closed when nothing is outstanding.

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
MAX_TRIES = 3                   # failed catch-up answers before it is a colleague's
_INDEX = "comment:catchup:index"
MODEL = "model"                 # why a comment had no answer: the model call failed …
CAP = "cap"                     # … a cap stopped the call …
REVIEW = "review"               # … or the reviewer held the draft


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
    """Meta took the line: it is said, for the window."""
    if redis is None:
        return
    try:
        await redis.set(_said(key), "1", ex=WINDOW_S)
        await redis.delete(_claim(key))
    except Exception:
        pass


async def hold_release(redis, key: str) -> None:
    """The send was refused: free the claim so it may be tried again."""
    if redis is None:
        return
    try:
        await redis.delete(_claim(key))
    except Exception:
        pass


# ── what is waiting ──────────────────────────────────────────────────────────
async def _rows(redis, key: str) -> list[tuple[str, dict]]:
    out = []
    for raw in await redis.lrange(_queue(key), 0, -1):
        try:
            out.append((_s(raw), json.loads(raw)))
        except ValueError:
            continue
    return out


async def keep(redis, channel: str, comment: dict, own_pages, reason: str) -> bool:
    """Keep a comment that had no answer. Idempotent by comment id."""
    key = key_of(channel, post_of(comment), comment.get("from_id") or "")
    cid = str(comment.get("comment_id") or "")
    if redis is None or not (post_of(comment) and comment.get("from_id") and cid):
        return False
    try:
        if any(str(i.get("cid")) == cid for _r, i in await _rows(redis, key)):
            return True
        item = {"at": time.time(), "cid": cid, "reason": reason,
                "own_pages": sorted(own_pages or []),
                "comment": {k: v for k, v in comment.items()
                            if k not in ("catch_up", "catch_up_ids")}}
        await redis.rpush(_queue(key), json.dumps(item, default=str))
        await redis.expire(_queue(key), WINDOW_S)
        await redis.sadd(_INDEX, key)
        return True
    except Exception as exc:
        _log.info("comment catch-up: could not keep %s: %s", cid, exc)
        return False


async def waiting(redis, key: str) -> list[dict]:
    """The kept comments, oldest first ([] on any doubt)."""
    if redis is None:
        return []
    try:
        return [i for _r, i in await _rows(redis, key)]
    except Exception:
        return []


async def resolve(redis, key: str, ids) -> list[dict]:
    """These comment ids are answered: remove exactly them. Returns what is
    still waiting. When nothing is, the wait is over — a later outage may say
    the holding line again."""
    if redis is None:
        return []
    ids = {str(i) for i in (ids or [])}
    left = []
    try:
        for raw, item in await _rows(redis, key):
            if str(item.get("cid")) in ids:
                await redis.lrem(_queue(key), 0, raw)      # by value: a comment pushed meanwhile stays
            else:
                left.append(item)
        if not left:
            await redis.delete(_queue(key), _said(key), _staff(key), _tries(key))
            await redis.srem(_INDEX, key)
    except Exception as exc:
        _log.info("comment catch-up: resolve failed for %s: %s", key, exc)
    return left


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
         human_cut: float = 0.0, min_age: float = MIN_AGE_S) -> dict:
    """What to do with one person's kept comments under one post. Pure.

      covered — ids a colleague's reply already answered (older than it)
      expired — ids past the window
      answer  — the ONE comment to answer (the latest, with `catch_up` = every
                outstanding text oldest first and `catch_up_ids`), or None:
                nothing eligible, a colleague's by `staff_cut`, or the newest
                is too fresh for the live path to have finished
      outstanding — what is still unanswered after covered/expired
    """
    now = time.time() if now is None else now
    live, covered, expired = [], [], []
    for i in items:
        if not (isinstance(i, dict) and isinstance(i.get("comment"), dict)):
            continue
        at = float(i.get("at") or 0)
        if human_cut and at <= human_cut:
            covered.append(str(i.get("cid")))
        elif now - at > WINDOW_S:
            expired.append(str(i.get("cid")))
        else:
            live.append(i)
    out = {"covered": covered, "expired": expired, "outstanding": live, "answer": None}
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
    last["catch_up"], last["catch_up_ids"] = said, ids
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
                "A colleague who replies in the thread first has answered them.")
    return f"{head}\n{lines}\n{tail}"


async def followup(redis, channel: str, ext: str, key: str, items: list, state: str,
                   why: str = "") -> str | None:
    """Write (or rewrite) the ONE follow-up for this person under this post on
    the conversation's timeline. Returns "new" when it was just created (the
    caller rings the team), "updated", or None when it could not be written."""
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
    the holding line that Meta refused earlier. Returns how many people were
    answered."""
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
            channel, post_id, ext = key.split(":", 2)
            items = await waiting(redis, key)
            if not items:
                await resolve(redis, key, [])
                continue
            from app.agent import runtime as rt
            human_cut = await rt._staff_answered_at(channel, ext, post_id)
            p = plan(items, staff_cut=await staff_only(redis, key), human_cut=human_cut)
            if p["expired"]:
                # a day has gone by: they stay on the follow-up as a colleague's
                gone = [i for i in items if str(i.get("cid")) in set(p["expired"])]
                await followup(redis, channel, ext, key, gone + p["outstanding"], STAFF,
                               "more than a day has passed")
            if p["covered"] or p["expired"]:
                left = await resolve(redis, key, p["covered"] + p["expired"])
                if not left and not p["expired"]:
                    await followup(redis, channel, ext, key, [], CLOSED)
            if not p["outstanding"]:
                continue
            if down:
                # still cannot answer: make sure they heard the one line
                if await hold_state(redis, key) == "send":
                    last = p["outstanding"][-1]
                    ok = await rt._post_hold_ack(redis, channel, last["comment"],
                                                 set(last.get("own_pages") or []))
                    await (hold_confirm if ok else hold_release)(redis, key)
                continue
            if p["answer"] is None:
                continue
            if not await redis.set(f"comment:catchup:lock:{key}", "1", nx=True, ex=600):
                continue
            await rt._run_comment_engage(redis, channel, p["answer"]["comment"],
                                         p["answer"]["own_pages"])
            done += 1
        except Exception as exc:
            _log.warning("comment catch-up failed for %s: %s", key, exc)
    if done:
        _log.info("comment catch-up: tried %d waiting commenter(s)", done)
    return done
