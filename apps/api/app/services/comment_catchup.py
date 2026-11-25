"""One holding line, then one answer (owner, 2026-11-25).

When Neema cannot answer a public comment — the AI account is out of credit,
the turn failed — the thread heard the same stock line under every comment the
person wrote: "Thank you for reaching out … one of our team will come back to
you" four times in twenty minutes. That is the machine talking, and it tells
the customer nobody is reading.

So, per person per post:

  * the holding line is said ONCE. Every later comment while we still cannot
    answer gets the Page's Like (it was seen) and no words;
  * what they wrote while we could not answer is KEPT, in order;
  * when the model answers again, everything they wrote is read together and
    answered in ONE reply under their latest comment — the conversation
    starts again from there. Nothing older than 24 hours is revived: by then
    it is a colleague's (the team was told at the first comment).

Redis only, best-effort: with no redis the old behaviour stands.
"""
from __future__ import annotations

import json
import logging
import time

_log = logging.getLogger("neema.agent")

WINDOW_S = 24 * 3600            # how long a holding line stands, and how old a comment may be revived
MIN_AGE_S = 90                  # let the live path finish before the catch-up looks
_INDEX = "comment:catchup:index"


def _k(channel: str, post_id: str, ext: str) -> str:
    return f"{channel}:{post_id}:{ext}"


def _said_key(key: str) -> str:
    return f"comment:hold_said:{key}"


def _queue_key(key: str) -> str:
    return f"comment:catchup:q:{key}"


async def first_hold(redis, channel: str, post_id: str, ext: str) -> bool:
    """True when the holding line has NOT yet been said to this person under
    this post (and marks it said). No redis, no post id → True: the line goes
    out, as before."""
    if redis is None or not (post_id and ext):
        return True
    try:
        return bool(await redis.set(_said_key(_k(channel, post_id, ext)), "1",
                                    nx=True, ex=WINDOW_S))
    except Exception:
        return True


async def keep(redis, channel: str, comment: dict, own_pages) -> None:
    """Keep a comment we could not answer, for the one answer later."""
    post_id = str(comment.get("post_id") or (comment.get("post_context") or {}).get("post_id") or "")
    ext = str(comment.get("from_id") or "")
    if redis is None or not (post_id and ext and comment.get("comment_id")):
        return
    key = _k(channel, post_id, ext)
    item = {"at": time.time(), "own_pages": sorted(own_pages or []),
            "comment": {k: v for k, v in comment.items() if k != "catch_up"}}
    try:
        await redis.rpush(_queue_key(key), json.dumps(item, default=str))
        await redis.expire(_queue_key(key), WINDOW_S)
        await redis.sadd(_INDEX, key)
    except Exception as exc:
        _log.info("comment catch-up: could not keep %s: %s", comment.get("comment_id"), exc)


async def clear(redis, channel: str, post_id: str, ext: str) -> None:
    """Answered: the wait is over, and a later outage may say the line again."""
    if redis is None:
        return
    key = _k(channel, post_id, ext)
    try:
        await redis.delete(_queue_key(key), _said_key(key))
        await redis.srem(_INDEX, key)
    except Exception:
        pass


async def drop_kept(redis, channel: str, post_id: str, ext: str) -> None:
    """Stop trying: the kept comments go, the holding line stays said (so it
    is not repeated) — a colleague has the thread."""
    if redis is None:
        return
    key = _k(channel, post_id, ext)
    try:
        await redis.delete(_queue_key(key))
        await redis.srem(_INDEX, key)
    except Exception:
        pass


def combine(items: list, now: float | None = None) -> dict | None:
    """The kept comments of one person under one post → the ONE comment to
    answer: the latest, carrying everything they wrote (oldest first) as
    `catch_up`. None when nothing is young enough, or the newest is too fresh
    for the live path to have finished. Pure."""
    now = time.time() if now is None else now
    live = [i for i in items if isinstance(i, dict) and isinstance(i.get("comment"), dict)
            and now - float(i.get("at") or 0) <= WINDOW_S]
    if not live or now - float(live[-1].get("at") or 0) < MIN_AGE_S:
        return None
    said, seen = [], set()
    for i in live:
        t = " ".join(str(i["comment"].get("text") or "").split())
        if t and t.lower() not in seen:          # the same words sent twice are read once
            seen.add(t.lower())
            said.append(t)
    if not said:
        return None
    last = dict(live[-1]["comment"])
    last["catch_up"] = said
    return {"comment": last, "own_pages": set(live[-1].get("own_pages") or [])}


def catch_up_prompt(said: list[str]) -> str:
    """What the model is handed in place of one comment's words."""
    if len(said) == 1:
        return said[0]
    lines = "\n".join(f"{n}. {t}" for n, t in enumerate(said, 1))
    return ("(This person wrote several comments under this post before we could answer. "
            "Read them TOGETHER as one request and give ONE reply that answers all of it. "
            "Do not answer them one by one, do not mention any delay or technical problem, "
            "and do not repeat a thank-you they already heard.)\n" + lines)


async def sweep(redis, *, limit: int = 15) -> int:
    """Answer what was kept, once the model can answer. Returns how many
    people were answered."""
    if redis is None:
        return 0
    from app.services.agent_health import ai_down
    try:
        if await ai_down(redis):
            return 0                              # still cannot answer: keep waiting
        keys = list(await redis.smembers(_INDEX))[:200]
    except Exception:
        return 0
    done = 0
    for raw in keys:
        if done >= limit:
            break
        key = raw.decode() if isinstance(raw, bytes) else str(raw)
        try:
            rows = await redis.lrange(_queue_key(key), 0, -1)
            if not rows:
                await redis.srem(_INDEX, key)
                await redis.delete(_said_key(key))
                continue
            items = []
            for r in rows:
                try:
                    items.append(json.loads(r))
                except ValueError:
                    continue
            one = combine(items)
            if one is None:
                if all(time.time() - float(i.get("at") or 0) > WINDOW_S for i in items):
                    await redis.delete(_queue_key(key), _said_key(key))
                    await redis.srem(_INDEX, key)
                continue
            if not await redis.set(f"comment:catchup:lock:{key}", "1", nx=True, ex=600):
                continue
            channel = key.split(":", 1)[0]
            from app.agent.runtime import _run_comment_engage
            await _run_comment_engage(redis, channel, one["comment"], one["own_pages"])
            done += 1
        except Exception as exc:
            _log.warning("comment catch-up failed for %s: %s", key, exc)
    if done:
        _log.info("comment catch-up: answered %d waiting commenter(s)", done)
    return done
