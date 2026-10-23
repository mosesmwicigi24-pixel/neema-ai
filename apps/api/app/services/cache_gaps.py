"""How long each prompt-cache entry waits between uses — the data behind a TTL.

A cache entry lives 5 minutes (or 1 hour) from its LAST use, and every use
refreshes it. So whether a longer TTL saves money or costs more is a question
of gaps, not of code:

  under 5 min  → the 5-minute entry was still there: read at 0.1×.
  5 min – 1 h  → the 5-minute entry had expired: the prefix was RE-WRITTEN at
                 1.25×; a 1-hour entry would have been read at 0.1×.
  over 1 h     → both TTLs had expired; a 1-hour write (2×) bought nothing.

Two clocks are kept, per PURPOSE, per UTC day:

  rules         the shared rules prefix (tools + the first system block, which
                carries the 1h breakpoint): the time since ANY call used the
                same rules. Sparse purposes (public comments) can find it gone.
  conversation  one conversation's prefix (rules + the customer's block + the
                transcript's first message): the time since the last call on
                it, sampled on each turn's OPENING call — a tool-loop call is
                seconds after the last and says nothing about the customer's
                pace — with the prompt tokens that call carried, so the tokens
                a 1-hour entry would have read instead of re-written can be
                counted.

/api/health → spend.cache_gaps. Best-effort, like the meter: a redis hiccup
costs a sample, never a reply.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

_TTL = 3 * 86400            # the day's tally, kept for post-mortems
_SEEN_TTL = 26 * 3600       # last-use stamps: long enough to tell "over 1 h" from "new"

BUCKETS = ("under_5m", "5m_1h", "over_1h", "new")


def bucket(gap: float | None) -> str:
    if gap is None:
        return "new"
    if gap < 300:
        return "under_5m"
    if gap < 3600:
        return "5m_1h"
    return "over_1h"


def _digest(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(p if isinstance(p, bytes) else
                 json.dumps(p, sort_keys=True, default=str, ensure_ascii=False).encode())
        h.update(b"\x00")
    return h.hexdigest()[:20]


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return json.dumps([{k: v for k, v in b.items() if k != "cache_control"}
                           if isinstance(b, dict) else b for b in content],
                          sort_keys=True, default=str, ensure_ascii=False)
    return str(content or "")


def _is_opener(messages: list) -> bool:
    """A turn's first call ends on the customer's words; the tool loop's later
    calls end on tool results (a user message of tool_result blocks)."""
    if not messages:
        return False
    last = messages[-1]
    if last.get("role") != "user":
        return False
    c = last.get("content")
    return not (isinstance(c, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in c))


def keys_for(system, messages: list, tools: list) -> tuple[str, str | None]:
    """(rules key, conversation key) for one call — hashes of exactly the
    prefixes the two cache breakpoints cover. No conversation without a
    transcript."""
    blocks = [system] if isinstance(system, str) else [s for s in (system or []) if s]
    rules = _digest(tools or [], blocks[0] if blocks else "")
    conv = _digest(rules, blocks, _content_text(messages[0].get("content"))) if messages else None
    return rules, conv


def _day(now: float) -> str:
    return "ai:gaps:" + datetime.fromtimestamp(now, timezone.utc).strftime("%Y%m%d")


def _slug(s: str | None) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "-"
                   for ch in str(s or "other").lower())[:40] or "other"


async def _gap(r, key: str, now: float) -> float | None:
    """Seconds since `key` was last used (None the first time), stamping now."""
    last = None
    try:
        raw = await r.get(key)
        if raw is not None:
            last = float(raw.decode() if isinstance(raw, bytes) else raw)
    except (TypeError, ValueError):
        last = None
    await r.set(key, repr(now), ex=_SEEN_TTL)
    return None if last is None else max(0.0, now - last)


async def record(purpose: str, system, messages: list, tools: list, usage: dict | None,
                 redis=None, now: float | None = None) -> None:
    """One cached model call: its gap on each clock into today's tally."""
    from app.services import ai_budget
    r = redis if redis is not None else ai_budget._sink
    if r is None:
        return
    now = time.time() if now is None else now
    try:
        rules, conv = keys_for(system, messages, tools)
        p, day = _slug(purpose), _day(now)
        b = bucket(await _gap(r, f"cachegap:r:{rules}", now))
        await r.hincrby(day, f"rules:{p}:{b}:calls", 1)
        if conv:
            gap = await _gap(r, f"cachegap:c:{conv}", now)   # every call refreshes it
            if _is_opener(messages):
                u = usage or {}
                prompt = sum(int(u.get(k) or 0) for k in
                             ("input_tokens", "cache_read_tokens", "cache_write_tokens"))
                cb = bucket(gap)
                await r.hincrby(day, f"conversation:{p}:{cb}:calls", 1)
                if prompt:
                    await r.hincrby(day, f"conversation:{p}:{cb}:tokens", prompt)
        await r.expire(day, _TTL)
    except Exception:
        pass                     # a sample, never a reply


async def read_gaps(redis=None, now: float | None = None) -> dict:
    """Today's tally: {clock: {purpose: {bucket: {"calls", "tokens"?}}}}, every
    bucket present for each purpose seen. {} when redis cannot say."""
    from app.services import ai_budget
    r = redis if redis is not None else ai_budget._sink
    if r is None:
        return {}
    try:
        raw = await r.hgetall(_day(time.time() if now is None else now)) or {}
    except Exception:
        return {}
    out: dict = {}
    for k, v in raw.items():
        k = k.decode() if isinstance(k, bytes) else str(k)
        try:
            clock, purpose, b, field = k.split(":")
            n = int(float(v.decode() if isinstance(v, bytes) else v))
        except (ValueError, TypeError):
            continue
        per = out.setdefault(clock, {}).setdefault(
            purpose, {x: ({"calls": 0, "tokens": 0} if clock == "conversation" else {"calls": 0})
                      for x in BUCKETS})
        if b in per and field in per[b]:
            per[b][field] = n
    return out
