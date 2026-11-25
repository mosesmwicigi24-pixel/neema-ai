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
  * WHO OWES THE REPLY IS WRITTEN ON THE COMMENT ITSELF, in the database
    (services/comment_ledger): owed by Neema, a colleague's, to be verified,
    or resolved. The webhook stamps "owed" in the commit that saves the
    comment, so a restart before the reply was even scheduled loses nothing,
    and nothing here runs out — Redis only spaces the attempts. No copy of
    a comment's words is kept anywhere else: a deleted comment (a customer's
    data-deletion request) is gone from here too.
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

Redis holds only the said-once mark, the claims and the retry spacing.
"""
from __future__ import annotations

import json
import logging
import time

from app.services import comment_ledger as ledger
from app.services.comment_ledger import OWED, STAFF as L_STAFF, VERIFY, RESOLVED

_log = logging.getLogger("neema.agent")

WINDOW_S = 24 * 3600            # how long Neema may still answer by herself
MIN_AGE_S = 90                  # let the live path finish before the sweep looks
ORPHAN_AGE_S = 600              # a comment no handler ever decided on (a restart)
CLAIM_S = 120                   # a holding-line send in flight
ANSWER_CLAIM_S = 180            # one composer of the combined reply at a time
BACKOFF_S = 600                 # between the sweep's tries for one person
MAX_TRIES = 3                   # catch-up tries before it is a colleague's
MODEL = "model"                 # why a comment had no answer: the model call failed …
CAP = "cap"                     # … a cap stopped the call …
REVIEW = "review"               # … or the reviewer held the draft
MISSED = "missed"               # … or no handler ever reached it
WHY = {CAP: "a reply limit was reached", REVIEW: "the reply reviewer held the draft"}
UNKNOWN_WHY = ("a reply may already have posted — Meta did not confirm it; "
               "check the thread before answering")


def key_of(channel: str, post_id, ext) -> str:
    return f"{channel}:{post_id}:{ext}"


def post_of(comment: dict) -> str:
    return str(comment.get("post_id") or (comment.get("post_context") or {}).get("post_id") or "")


def _parts(key: str) -> tuple[str, str, str]:
    channel, post_id, ext = key.split(":", 2)
    return channel, post_id, ext


def _said(key: str) -> str:
    return f"comment:hold_said:{key}"


def _claim(key: str) -> str:
    return f"comment:hold_claim:{key}"


def _tries(key: str) -> str:
    return f"comment:catchup:tries:{key}"


def _answering(key: str) -> str:
    return f"comment:catchup:claim:{key}"


def _backoff(key: str) -> str:
    return f"comment:catchup:backoff:{key}"


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


async def tried(redis, key: str) -> int:
    """Count one catch-up try; returns the count so far."""
    if redis is None:
        return 1
    try:
        n = int(await redis.incr(_tries(key)))
        await redis.expire(_tries(key), WINDOW_S)
        return n
    except Exception:
        return 1


# ── what is waiting: read from the comments themselves ───────────────────────
def _item(row: dict, ext: str) -> dict:
    return dict(row, comment={
        "comment_id": row["cid"], "from_id": ext, "text": row.get("text") or "",
        "post_id": row.get("post_id"), "page_id": row.get("page_id"),
        "parent_id": row.get("parent_id"), "post_context": dict(row.get("post_context") or {})})


async def waiting(redis, key: str) -> list[dict]:
    """This person's unresolved comments under this post (owed, a colleague's,
    or to be verified), oldest first, with their words as the database holds
    them now. [] when the record cannot be read."""
    channel, post_id, ext = _parts(key)
    try:
        return [_item(r, ext) for r in await ledger.unresolved(channel, ext, post_id)]
    except Exception as exc:
        _log.info("comment catch-up: record unreadable for %s: %s", key, exc)
        return []


async def keep(redis, channel: str, comment: dict, own_pages, reason: str) -> bool:
    """The handler looked at this comment and it has no answer: say so on the
    comment. A failed model call stays Neema's; a cap or a held draft is a
    colleague's from the start."""
    ext, cid = str(comment.get("from_id") or ""), str(comment.get("comment_id") or "")
    if not (post_of(comment) and ext and cid):
        return False
    try:
        return bool(await ledger.mark(
            channel, ext, [cid], create=True, decided=True, reason=reason,
            state=OWED if reason in (MODEL, MISSED) else L_STAFF, why=WHY.get(reason, ""),
            own_pages=sorted(own_pages or []), page_id=comment.get("page_id"),
            parent_id=comment.get("parent_id")))
    except Exception as exc:
        _log.info("comment catch-up: could not record %s: %s", cid, exc)
        return False


async def settle(channel: str, ext, cid) -> None:
    """The handler finished with this comment without leaving it waiting: it
    is resolved (answered, or deliberately left). A comment the handler never
    finished — a restart, a crash — is NOT settled and stays owed."""
    try:
        await ledger.mark(channel, str(ext or ""), [cid], only_undecided=True,
                          state=RESOLVED, by="handled", decided=True)
    except Exception as exc:
        _log.info("comment catch-up: could not settle %s: %s", cid, exc)


async def _tidy(redis, key: str) -> int:
    """How many are still unresolved; when none, the wait is over and a later
    outage may say the holding line again."""
    left = len(await waiting(redis, key))
    if not left and redis is not None:
        try:
            await redis.delete(_said(key), _tries(key), _backoff(key))
        except Exception:
            pass
    return left


async def resolve(redis, key: str, ids, by: str = "neema") -> int:
    """These comments are answered: say so on exactly them. Returns how many
    of this person's comments here are still unresolved."""
    channel, _post, ext = _parts(key)
    try:
        await ledger.mark(channel, ext, ids, state=RESOLVED, by=by, decided=True)
    except Exception as exc:
        _log.info("comment catch-up: resolve failed for %s: %s", key, exc)
    return await _tidy(redis, key)


async def hand_to_staff(redis, key: str, why: str, ids=None) -> None:
    """What Neema still owed here is a colleague's now, with why."""
    channel, _post, ext = _parts(key)
    try:
        if ids is None:
            ids = [i["cid"] for i in await waiting(redis, key) if i.get("state") == OWED]
        await ledger.mark(channel, ext, ids, state=L_STAFF, why=why, decided=True)
        if redis is not None:
            await redis.delete(_tries(key))
    except Exception as exc:
        _log.info("comment catch-up: hand-over failed for %s: %s", key, exc)


async def needs_verify(redis, key: str, ids, why: str = UNKNOWN_WHY) -> None:
    """A reply to these may have posted: nobody posts another; a colleague looks."""
    channel, _post, ext = _parts(key)
    try:
        await ledger.mark(channel, ext, ids, state=VERIFY, why=why, decided=True)
    except Exception as exc:
        _log.info("comment catch-up: verify mark failed for %s: %s", key, exc)


def plan(items: list, *, now: float | None = None, min_age: float = MIN_AGE_S,
         orphan_age: float = ORPHAN_AGE_S) -> dict:
    """What to do with one person's unresolved comments under one post. Pure.

      expired — owed ids past the window: a colleague's now
      orphans — owed ids no handler ever decided on, old enough to be sure
                (a restart between the save and the reply)
      answer  — the ONE comment to answer (the latest answerable one, with
                `catch_up` = every answerable text oldest first and
                `catch_up_ids`), or None: Neema owes nothing here that she
                can still answer, or the newest is too fresh
      outstanding — everything unresolved, whoever owns it
    """
    now = time.time() if now is None else now
    expired, orphans, due, mine = [], [], [], []
    for i in items:
        if not (isinstance(i, dict) and isinstance(i.get("comment"), dict)):
            continue
        age = now - float(i.get("at") or 0)
        if i.get("state") != OWED:
            if i.get("state") == L_STAFF:
                mine.append(i)                   # a colleague's, but one reply may cover it too
            continue
        if age > WINDOW_S:
            expired.append(str(i.get("cid")))
        elif i.get("decided"):
            due.append(i)
        elif age >= orphan_age:
            orphans.append(str(i.get("cid")))
            due.append(i)
    out = {"expired": expired, "orphans": orphans, "outstanding": list(items),
           "owed": due, "answer": None}
    if not due or now - max(float(i.get("at") or 0) for i in due) < min_age:
        return out
    cover = sorted(due + [i for i in mine if now - float(i.get("at") or 0) <= WINDOW_S],
                   key=lambda i: float(i.get("at") or 0))
    said, ids, seen = [], [], set()
    for i in cover:
        ids.append(str(i.get("cid")))
        t = " ".join(str(i["comment"].get("text") or "").split())
        if t and t.lower() not in seen:           # the same words sent twice are read once
            seen.add(t.lower())
            said.append(t)
    if not said:
        return out
    last = dict(cover[-1]["comment"])
    last["catch_up"], last["catch_up_ids"], last["catch_up_claimed"] = said, ids, True
    out["answer"] = {"comment": last, "own_pages": set(cover[-1].get("own_pages") or [])}
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
    questions under the same post, stay as they are. True when it was open."""
    cid = str(comment_id or "")
    if not (cid and ext):
        return False
    try:
        st = await ledger.state_of(channel, str(ext), cid)
    except Exception:
        return False
    if not st or st.get("state") == RESOLVED:
        return False
    key = key_of(channel, st.get("post_id") or "", ext)
    await resolve(redis, key, [cid], by="staff")
    await refresh_followup(redis, key)
    return True


# ── the one follow-up staff see ──────────────────────────────────────────────
WAITING, STAFF, CLOSED = "waiting", "staff", "closed"


def followup_note(items: list, state: str, why: str = "") -> str:
    """The follow-up's words. Pure."""
    if state == CLOSED or not items:
        return "PUBLIC COMMENTS — answered. No comment from this person is waiting under this post."
    lines = "\n".join(
        f"{n}. {' '.join(str(i['comment'].get('text') or '').split())[:300]}"
        + (" — CHECK THE THREAD: a reply may already be there" if i.get("state") == VERIFY else "")
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


async def refresh_followup(redis, key: str, why: str = "", ring: bool = False) -> str | None:
    """Rewrite the follow-up from what the comments say now: closed when
    nothing is unresolved, the colleague's when Neema owes nothing more."""
    channel, _post, ext = _parts(key)
    items = await waiting(redis, key)
    if not items:
        return await followup(redis, channel, ext, key, [], CLOSED)
    auto = any(i.get("state") == OWED for i in items)
    if not auto and not why:
        why = next((i.get("why") for i in reversed(items) if i.get("why")), "")
    return await followup(redis, channel, ext, key, items, WAITING if auto else STAFF, why, ring=ring)


async def followup(redis, channel: str, ext: str, key: str, items: list, state: str,
                   why: str = "", ring: bool = False) -> str | None:
    """Write (or rewrite) the ONE follow-up for this person under this post on
    the conversation's timeline. Its id is kept on the comments themselves.
    Returns "new" when it was just created, "updated", or None when it could
    not be written. The team is rung when it is new, and when `ring`."""
    try:
        import uuid
        from sqlalchemy import select
        from app.database import AsyncSessionLocal
        from app.models.conversation import Conversation
        from app.models.intercept import Intercept, InterceptAction
        _channel, post_id, _ext = _parts(key)
        note = followup_note(items, state, why)
        fid = await ledger.followup_id(channel, ext, post_id)
        made, conv_id = False, None
        async with AsyncSessionLocal() as db:
            row = None
            if fid:
                try:
                    row = await db.get(Intercept, uuid.UUID(str(fid)))
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
                made = True
            else:
                row.note = note
            conv_id, fid = str(row.conversation_id), str(row.id)
            await db.commit()
        if made:
            await ledger.mark(channel, ext, [items[-1]["cid"]], followup=fid)
        if (made or ring) and redis is not None:
            try:
                await redis.publish("ws:channel:agents:all", json.dumps({
                    "event": "notification", "type": "draft_ready",
                    "title": f"{channel.title()} comment needs you",
                    "body": ("A commenter is waiting for an answer only a colleague can give."
                             if state == STAFF else
                             "A commenter is waiting for an answer Neema could not give."),
                    "conv_id": conv_id, "wa_id": ext}))
            except Exception:
                pass
        return "new" if made else "updated"
    except Exception as exc:
        _log.info("comment follow-up not written for %s: %s", key, exc)
        return None


# ── the sweep ────────────────────────────────────────────────────────────────
async def sweep(redis, *, limit: int = 15) -> int:
    """Every comment Neema still owes, read from the comments themselves:
    answer what can be answered, say the holding line that was never said,
    pick up what no handler reached, and hand a colleague what has waited a
    day. Returns how many people it tried to answer."""
    from app.services.agent_health import ai_down
    try:
        down = bool(await ai_down(redis))
        keys = await ledger.keys_owed()
    except Exception as exc:
        _log.info("comment catch-up: nothing read this pass: %s", exc)
        return 0
    done = 0
    for channel, ext, post_id in keys:
        if done >= limit:
            break
        key = key_of(channel, post_id, ext)
        try:
            from app.agent import runtime as rt
            items = await waiting(redis, key)
            p = plan(items)
            if p["orphans"]:
                # no handler ever reached these: a reply already under one settles
                # it; the rest are Neema's to answer now
                had = await ledger.replied_ids(channel, ext, p["orphans"])
                if had:
                    await ledger.mark(channel, ext, list(had), state=RESOLVED, by="replied", decided=True)
                await ledger.mark(channel, ext, [i for i in p["orphans"] if i not in had],
                                  decided=True, reason=MISSED)
                if had:
                    items = await waiting(redis, key)
                    p = plan(items)
            if p["expired"]:
                await hand_to_staff(redis, key, "more than a day has passed", ids=p["expired"])
                await refresh_followup(redis, key, ring=True)
                items = await waiting(redis, key)
                p = plan(items)
            if not p["owed"]:
                continue
            if down:
                # still cannot answer: make sure they heard the one line
                if await hold_state(redis, key) == "send":
                    last = p["owed"][-1]
                    sent = await rt._post_hold_ack(redis, channel, last["comment"],
                                                   set(last.get("own_pages") or []))
                    if sent is False:                  # Meta refused: may be tried again
                        await hold_release(redis, key)
                    else:                              # landed, or unknown: never resent
                        await hold_confirm(redis, key)
                    await refresh_followup(
                        redis, key, "the holding line may or may not have posted — "
                        "Meta did not confirm it" if sent is None else "")
                continue
            if p["answer"] is None or redis is None:
                continue
            if await redis.get(_backoff(key)) or not await claim_answer(redis, key):
                continue                               # tried lately, or the live handler has it
            try:
                await redis.set(_backoff(key), "1", ex=BACKOFF_S)
                if await tried(redis, key) > MAX_TRIES:
                    await hand_to_staff(redis, key, "three tries to answer did not succeed")
                    await refresh_followup(redis, key, ring=True)
                    continue
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
