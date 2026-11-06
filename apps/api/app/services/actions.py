"""The initiative engine — planned actions with a veto window (plan B2).

Neema's follow-ups are visible rows FIRST (agent_actions), executed by a
leader-locked 60s loop. Routine ones fire on their own; sensitive ones flip to
needs_approval and wait for the operator's one tap.

The sensitivity gate (conservative on purpose):
  · deal total > KES 50,000
  · the conversation is human-held
  · the thread was flagged for the team in the last 7 days (an open
    complaint, a failed reply, a sourcing gap — never nudge into a grievance)
  · ≥2 follow-ups already sent on this deal
  · outside the 24h messaging window (a free-form send would breach policy)

Sending only happens when AGENT_INITIATIVE=1; with the flag off the queue
still fills — the operator sees what Neema WOULD do, before trusting her to.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func as sa_func

from app.core.config import settings

_log = logging.getLogger("neema.actions")

LEADER_KEY = "agentactions:leader"
SENSITIVE_TOTAL_KES = 50_000
MAX_AUTO_NUDGES = 2

# WHY an action waits for a human (2026-10-10: 133 follow_up + 93
# replenishment rows sat in needs_approval and nothing said why — the gate's
# answer went only into a passing notification). Stored on the row itself, at
# the end of `reason`, as one marker: no migration, and every surface that
# already shows `reason` (web, Android) shows it. The list endpoint also
# returns it on its own as `approval_reason`.
_HOLD_RE = re.compile(r"\s*\[needs approval: [^\]]*\]")

# Sales follow-ups nobody asked for, versus a check-in on a day someone named,
# versus care about their own order. One customer, one routine message per
# tick; a promise or a care message is deferred rather than merged.
ROUTINE_KINDS = frozenset({"follow_up", "customer_promise", "quote_follow_up",
                           "buying_follow_up", "check_in", "replenishment"})
CARE_KINDS = frozenset({"fit_check", "payment_reminder"})
# Rows whose text was composed in code when they were planned (figures never
# drift): sent as their draft, never re-composed by the model.
CODE_COMPOSED_KINDS = frozenset({"quote_follow_up", "payment_reminder"})


def message_class(action) -> str:
    from app.services import outreach_log as ol
    kind = getattr(action, "kind", "") or ""
    reason = getattr(action, "reason", "") or ""
    if kind in CARE_KINDS:
        return ol.TRANSACTIONAL
    if kind in ("check_in", "replenishment", "customer_promise") or \
            reason.startswith(("Customer-agreed", "Supplies check-in", "Delivery check-in")):
        return ol.PROMISE
    return ol.ROUTINE


def template_purpose(action) -> str | None:
    """Which approved template may carry this action once the window has
    closed — or None (a person sends it). A customer still DECIDING gets the
    follow-up template, never the order/replenishment one (owner, 2026-11-05)."""
    kind = getattr(action, "kind", "") or ""
    reason = getattr(action, "reason", "") or ""
    if kind == "fit_check":
        return "care"
    if kind == "replenishment" and reason.startswith("Supplies check-in"):
        return "replenishment"
    if kind in ("check_in", "replenishment", "customer_promise"):
        return "check_in"
    return None


def with_hold_reason(reason: str | None, why: str) -> str:
    """`reason` with ONE needs-approval marker — any older one replaced."""
    base = _HOLD_RE.sub("", reason or "").rstrip()
    return f"{base} [needs approval: {why}]".strip()


def hold_reason(reason: str | None) -> str | None:
    found = re.findall(r"\[needs approval: ([^\]]*)\]", reason or "")
    return found[-1] if found else None


OPEN_STATUSES = ("planned", "needs_approval", "sending")
_ORDER_IN_REASON_RE = re.compile(r"\b(?:order|#)\s*#?([A-Z]{1,6}-?\d{1,8}|\d{3,10})\b", re.IGNORECASE)


def dedupe_key_for(kind: str, *, deal_id=None, conversation_id=None, reason: str | None = None,
                   reference: str | None = None) -> str:
    """The commitment's identity — what makes two planned rows THE SAME
    matter (audit, 2026-11-05). Mirrored in alembic e8a1c3d5f7b9's backfill.

    One buying decision per deal (a quote nudge and a cart nudge are the same
    moment), one promise per deal, one check-in per purpose, one care check
    per order, one payment reminder per set of orders. Distinct orders,
    purposes and deals stay distinct rows."""
    base = str(deal_id or conversation_id or "")
    r = reason or ""
    if kind in ("quote_follow_up", "buying_follow_up"):
        return f"buying:{base}"
    if kind == "follow_up":
        return f"promise:{base}"
    if kind == "customer_promise":
        return f"customer_promise:{base}"
    if kind == "check_in":
        return "check_in:delivery" if r.startswith("Delivery check-in") else "check_in:purchase_decision"
    if kind == "replenishment":
        return "check_in:supplies" if r.startswith("Supplies check-in") else "check_in:purchase_decision"
    if kind == "fit_check":
        m = _ORDER_IN_REASON_RE.search(r)
        return f"care:{reference or (m.group(1) if m else base)}"
    if kind == "payment_reminder":
        return f"payment:{reference or base}"
    return f"{kind}:{reference or base}"[:80]


async def open_row(db, conversation_id, dedupe_key: str):
    from app.models.agent_action import AgentAction
    return (await db.execute(select(AgentAction).where(
        AgentAction.conversation_id == conversation_id,
        AgentAction.dedupe_key == dedupe_key,
        AgentAction.status.in_(OPEN_STATUSES)).limit(1))).scalar_one_or_none()


async def plan(db, *, conversation_id, kind: str, due_at: datetime, reason: str, source: str,
               deal_id=None, draft: str | None = None, reference: str | None = None,
               dedupe_key: str | None = None, move: bool = True):
    """File — or refresh — the ONE open row for this commitment. Returns
    (row, created). A row already being sent is left alone (returned, not
    changed). Two workers planning the same matter at once: the unique index
    rejects the second insert, which then updates the first. Commits."""
    from sqlalchemy.exc import IntegrityError
    from app.models.agent_action import AgentAction
    key = (dedupe_key or dedupe_key_for(kind, deal_id=deal_id, conversation_id=conversation_id,
                                        reason=reason, reference=reference))[:80]

    def _refresh(row):
        if row.status == "sending":
            return row
        if move:
            row.due_at = due_at
        row.kind = kind
        row.reason = reason[:500]
        row.source = source
        if draft is not None or row.kind != kind:
            row.draft = draft
        row.status = "planned"
        return row

    existing = await open_row(db, conversation_id, key)
    if existing is not None:
        _refresh(existing)
        await db.commit()
        return existing, False
    row = AgentAction(deal_id=deal_id, conversation_id=conversation_id, due_at=due_at,
                      kind=kind, reason=reason[:500], draft=draft, source=source,
                      dedupe_key=key)
    db.add(row)
    try:
        await db.commit()
        return row, True
    except IntegrityError:
        await db.rollback()
        existing = await open_row(db, conversation_id, key)
        if existing is None:
            raise
        _refresh(existing)
        await db.commit()
        return existing, False


async def upsert_follow_up(db, deal, *, due_at: datetime, kind: str,
                           reason: str) -> None:
    """One open scribe row per deal — a newer promise reschedules or replaces
    the older one instead of stacking nags. The replaced row is vetoed with
    the reason, so the record shows what superseded what."""
    from app.models.agent_action import AgentAction
    key = dedupe_key_for(kind, deal_id=deal.id, reason=reason)
    rows = (await db.execute(select(AgentAction).where(
        AgentAction.deal_id == deal.id,
        AgentAction.status.in_(("planned", "needs_approval"))))).scalars().all()
    same = next((r for r in rows if (r.dedupe_key or dedupe_key_for(
        r.kind, deal_id=deal.id, reason=r.reason)) == key), None)
    for r in rows:
        if r is not same and r.kind in ("follow_up", "customer_promise", "quote_follow_up",
                                        "buying_follow_up"):
            r.status = "vetoed"
            r.reason = f"{r.reason or ''} [superseded by a newer {kind}]"[:1000]
    if same is not None and same.kind == "quote_follow_up":
        same.draft = None                     # a re-quote is composed afresh
    if same is not None and same.dedupe_key != key:
        same.dedupe_key = key                 # a row from before identities existed
    # One path files every commitment (Stage 6): plan() finds the open row by
    # its identity, refreshes it, or inserts under the unique index.
    await plan(db, conversation_id=deal.conversation_id, deal_id=deal.id, kind=kind,
               due_at=due_at, reason=reason, source="scribe", dedupe_key=key)


async def withdraw_routine(db, conversation_id, *, why: str) -> int:
    """Veto this conversation's pending ROUTINE rows (quote nudges, Neema's own
    promise follow-ups): the customer or a colleague has moved the thread on.
    A check-in on a day the customer named, and care about their order, stay.
    Commits. Returns the number withdrawn."""
    from app.models.agent_action import AgentAction
    rows = (await db.execute(select(AgentAction).where(
        AgentAction.conversation_id == conversation_id,
        AgentAction.status.in_(("planned", "needs_approval")),
        AgentAction.kind.in_(("follow_up", "quote_follow_up"))))).scalars().all()
    n = 0
    for row in rows:
        row.status = "vetoed"
        row.reason = f"{row.reason or ''} [{why}]"[:1000]
        n += 1
    if n:
        await db.commit()
    return n


def deal_total(deal) -> float:
    total = 0.0
    for i in (deal.items_snapshot or []):
        try:
            total += float(i.get("price") or 0) * float(i.get("qty") or 1)
        except (TypeError, ValueError):
            pass
    return total


async def needs_approval(db, deal, conv, in_window: bool) -> str | None:
    """The reason this action must wait for a human — None when safe to auto-send."""
    from app.models.agent_action import AgentAction
    from app.models.conversation import InterceptMode
    if not in_window:
        return "outside the 24h messaging window"
    if conv is not None and conv.intercept_mode == InterceptMode.human:
        return "conversation is human-held"
    # "Never sell into displeasure" binds the scheduler exactly as it binds a
    # live turn: a thread flagged for the team in the last 7 days (a complaint,
    # a failed reply, a sourcing gap) gets NO automatic refill/fit-check/nudge —
    # the action waits in the approval queue for a human's one tap instead.
    if conv is not None and getattr(conv, "id", None) is not None:
        from app.models.intercept import Intercept, InterceptAction
        flagged = (await db.execute(select(sa_func.count()).select_from(Intercept).where(
            Intercept.conversation_id == conv.id,
            Intercept.action.in_((InterceptAction.flag, InterceptAction.escalated)),
            Intercept.created_at >= datetime.now(timezone.utc) - timedelta(days=7),
        ))).scalar_one()
        if flagged:
            return "conversation was flagged for the team in the last 7 days"
    if deal is not None and deal_total(deal) > SENSITIVE_TOTAL_KES:
        return f"deal total above KES {SENSITIVE_TOTAL_KES:,}"
    if deal is not None:
        sent = (await db.execute(select(sa_func.count()).select_from(AgentAction).where(
            AgentAction.deal_id == deal.id,
            AgentAction.status == "sent"))).scalar_one()
        if (sent or 0) >= MAX_AUTO_NUDGES:
            return f"already nudged {sent} times"
    return None


async def _contact_name(db, conv) -> str | None:
    """The customer's name as we know it: the conversation's, else the
    WhatsApp profile (users), else the person record."""
    name = getattr(conv, "contact_name", None)
    if name:
        return name
    try:
        from app.models.user import User
        if getattr(conv, "wa_id", None):
            u = (await db.execute(select(User).where(User.wa_id == conv.wa_id))).scalar_one_or_none()
            if u is not None and u.name:
                return u.name
        if getattr(conv, "person_id", None) is not None:
            from app.models.person import Person
            p = await db.get(Person, conv.person_id)
            if p is not None and p.display_name:
                return p.display_name
    except Exception:
        pass
    return None


# ── The contextual decision (Stage 2, audit §6) ─────────────────────────────
# One question before any unprompted message: would an attentive Bethany
# House representative send THIS, NOW? The rules here read the conversation's
# own facts. They are shadow-able (settings.outreach_mode) for the comparison
# week; the Stage 1 safety rules above them are not.

def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _latest_turns(db, conv):
    """(newest customer message at, newest colleague message at)."""
    from app.models.message import Message, MsgDirection, MsgSender
    last_in = (await db.execute(select(sa_func.max(Message.created_at)).where(
        Message.conversation_id == conv.id, Message.direction == MsgDirection.inbound))).scalar()
    last_human = (await db.execute(select(sa_func.max(Message.created_at)).where(
        Message.conversation_id == conv.id, Message.direction == MsgDirection.outbound,
        Message.sender == MsgSender.human_agent,
        Message.media_type.is_(None) | (Message.media_type != "note")))).scalar()
    return _aware(last_in), _aware(last_human)


async def _routine_sent_today(db, conv, now: datetime) -> int:
    """Unprompted SALES messages this customer already received today
    (Nairobi day), read from the origin stamp on the rows."""
    from app.models.message import Message, MsgDirection
    nbo = now + timedelta(hours=3)
    day_start = nbo.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3)
    n = (await db.execute(select(sa_func.count()).select_from(Message).where(
        Message.conversation_id == conv.id, Message.direction == MsgDirection.outbound,
        Message.created_at >= day_start,
        Message.raw_meta["kind"].astext == "outreach",
        Message.raw_meta["class"].astext == "routine"))).scalar()
    return int(n or 0)


async def decide(db, conv, action, *, now: datetime) -> tuple[str, str]:
    """('go' | 'suppress' | 'defer', why) for a due row that passed the
    safety rules. Only unprompted SALES messages (class routine) are judged
    here: a kept promise and care about an order have their own reasons to
    exist, and a reply the customer is owed never comes through this loop."""
    if message_class(action) != "routine":
        return "go", ""
    created = _aware(getattr(action, "created_at", None))
    try:
        last_in, last_human = await _latest_turns(db, conv)
    except Exception as exc:
        _log.info("decide: turns unreadable for %s: %s", getattr(conv, "id", "?"), exc)
        return "go", ""
    if created is not None and last_in is not None and last_in > created:
        return "suppress", "the customer wrote after this was planned — the live reply answered them"
    if created is not None and last_human is not None and last_human > created:
        return "suppress", "a colleague replied after this was planned"
    try:
        if await _routine_sent_today(db, conv, now) >= 1:
            return "defer", "one unprompted sales message a day"
    except Exception as exc:
        _log.info("decide: today's count unreadable for %s: %s", getattr(conv, "id", "?"), exc)
    return "go", ""


def rule_of(why: str) -> str:
    """Which contextual rule a decide() verdict came from — the unit the
    rollout is switched on by (services/app_settings.OUTREACH_RULES)."""
    w = (why or "").lower()
    if "colleague" in w:
        return "colleague_replied"
    if "customer wrote" in w:
        return "customer_replied"
    if "a day" in w:
        return "daily_cap"
    return "other"


async def _control(db, redis) -> dict:
    """The rollout control: mode and the rules enforced while in shadow —
    the dashboard's rows, else the environment."""
    from app.services import app_settings
    try:
        return await app_settings.get_outreach_control(db, redis)
    except Exception:
        return app_settings._default_outreach_control()


async def _shadow_count(redis, verdict: str) -> None:
    """The comparison week's tally, read by the 08:00 standup."""
    if redis is None:
        return
    try:
        key = "outreach:shadow:" + (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y%m%d")
        await redis.hincrby(key, verdict, 1)
        await redis.expire(key, 14 * 86400)
    except Exception:
        pass


async def _send_followup_template(db, redis, conv, action, purpose: str | None = None) -> bool:
    """Send a due action as its approved template (services/templates.py) once
    the window has closed. True when it went out. Raises TemplateRefused when
    no template fits or a parameter would read as nonsense, and
    SendOutcomeUnknown when Meta's answer never came — the caller parks the
    row for a person in both cases; nothing is ever sent "approximately"."""
    import re
    from app.services import messaging as svc
    from app.services import outreach_log as ol
    from app.services import templates
    purpose = purpose or template_purpose(action)
    if purpose is None:
        raise templates.TemplateRefused(f"a {action.kind} is never sent as a template")
    first = templates.first_name_param(await _contact_name(db, conv))
    if purpose == "check_in":
        params = [first]
    else:
        m = re.search(r"\b(?:order|#)\s*#?([A-Z]{1,6}-?\d{3,}|\d{3,})\b", action.reason or "", re.IGNORECASE)
        number = templates.order_number_param(
            m.group(1) if m else None,
            fallback="your supplies" if purpose == "replenishment" else "your recent order")
        phrase = (("the check-in you asked for — about time for the next round? "
                   "Reply here and we'll plan your delivery")
                  if purpose == "replenishment" else
                  ("delivered a few days ago — how is it fitting? If anything "
                   "needs adjusting, we're glad to help"))
        params = [first, number, phrase]
    rendered, wamid, tpl = await templates.send(conv.wa_id, purpose, params)
    await svc.save_outbound_message(
        db, redis, conv.wa_id, rendered, waba_msg_id=wamid,
        raw_meta=ol.stamp("actions", message_class(action), action_id=getattr(action, "id", None),
                          kind=action.kind, template=templates.meta(tpl, params)))
    await finish(db, action, "sent", draft=rendered)
    _log.info("%s sent via template %s for %s", action.kind, tpl.name, conv.wa_id)
    return True


async def _last_outbound_at(db, conv):
    from app.models.message import Message, MsgDirection
    return (await db.execute(
        select(sa_func.max(Message.created_at)).where(
            Message.conversation_id == conv.id,
            Message.direction == MsgDirection.outbound,
            Message.media_type.is_(None) | (Message.media_type != "note")))).scalar()


async def _compose_follow_up(db, redis, conv, reason: str) -> str:
    from app.agent import runtime
    from app.agent.composer import CONTINUATION_NOTE, recently_spoke, strip_repeated_greeting
    key = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
    text = ("[SCHEDULED FOLLOW-UP — not a customer message. Time to keep the "
            f"commitment: {reason}. FIRST re-read the conversation above: if a "
            "human colleague (lines marked [TEAM — a human colleague sent "
            "this]) has already answered part or all of it, their answer "
            "STANDS — repeat its substance as the update and only chase what "
            "genuinely remains open. Compose the ONE short message to send "
            "them now. If the commitment was to confirm something nobody has "
            "confirmed yet, be honest and say you're still on it — once. Never "
            "repeat a message already sent; never pressure.] " + CONTINUATION_NOTE)
    out = (await runtime.run_turn(
        db, redis, wa_id=key, user_text=text, llm=runtime.build_llm(purpose="follow-up"),
        channel=conv.channel,
        external_id=(None if conv.channel == "whatsapp" else conv.external_id),
        read_only=True)).strip()
    try:
        recent = recently_spoke(await _last_outbound_at(db, conv))
    except Exception:
        recent = True
    return strip_repeated_greeting(out, recent=recent)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


async def _repeats_earlier(db, conv, text: str, *, look_back: int = 6,
                           exact_only: bool = False) -> bool:
    """True when this follow-up is essentially something we already said.

    `exact_only`: a quote follow-up restates the quote BY DESIGN (the item and
    its figure, then the question), so only a word-for-word repeat — the same
    nudge already sent — counts for it.

    A promise like "let me check on that for you" is exactly the phrasing the
    composer is most likely to echo — and re-sending the stall hours later is
    worse than silence: it tells the customer we still haven't moved. The
    persona forbids it, but a prompt is not a guarantee, so this enforces it.
    """
    from app.models.message import Message, MsgDirection
    rows = (await db.execute(
        select(Message.text)
        .where(Message.conversation_id == conv.id,
               Message.direction == MsgDirection.outbound)
        .order_by(Message.created_at.desc())
        .limit(look_back)
    )).scalars().all()

    t = _norm(text)
    if not t:
        return True
    tw = set(t.split())
    for prev in rows:
        p = _norm(prev)
        if not p:
            continue
        if p == t:
            return True
        if exact_only:
            continue
        pw = set(p.split())
        if not pw or not tw:
            continue
        # Containment, not Jaccard: a short stall repeated inside a slightly
        # longer one is still the same non-answer.
        if len(tw & pw) / min(len(tw), len(pw)) >= 0.8:
            return True
    return False


async def _send(db, redis, conv, text: str, action=None, shadow: list | None = None) -> None:
    """Deliver, then record. Raises only when delivery failed: once the
    message is out, a failure to record it is logged, never raised — a raise
    there would put the action back in the queue and send it twice. An
    UNKNOWN outcome (SendOutcomeUnknown) is recorded as such and re-raised
    for the caller to park the action — never to retry it."""
    from app.services import messaging as svc
    from app.services import outreach_log as ol
    recipient = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
    meta = ol.stamp("actions", message_class(action) if action is not None else ol.ROUTINE,
                    action_id=getattr(action, "id", None), kind=getattr(action, "kind", None),
                    reference=(getattr(action, "dedupe_key", None) or None))
    if shadow:
        meta["shadow"] = list(shadow)          # what enforce mode would have done
    if getattr(action, "source", None):
        meta["planner"] = action.source
    if conv.channel == "whatsapp":
        try:
            wamid = await svc._send_waba(recipient, text)
        except svc.SendOutcomeUnknown as exc:
            meta["delivery"] = {"status": "unknown", "error": str(exc)[:120]}
            try:
                await svc.save_outbound_message(db, redis, recipient, text,
                                                waba_msg_id=None, raw_meta=meta)
            except Exception as rec_exc:
                _log.error("unknown-outcome follow-up to %s not recorded: %s", recipient, rec_exc)
            raise
        record = svc.save_outbound_message(db, redis, recipient, text, waba_msg_id=wamid,
                                           raw_meta=meta)
    else:
        from app.services.meta_send import send_to_channel
        await send_to_channel(conv.channel, recipient, text)
        record = svc.save_outbound_channel_message(db, redis, conv.channel, recipient, text,
                                                   raw_meta=meta)
    try:
        await record
    except Exception as exc:
        _log.error("follow-up delivered to %s but not recorded: %s", recipient, exc)
        try:
            await db.rollback()
        except Exception:
            pass


async def _notify(redis, title: str, body: str, conv=None) -> None:
    if redis is None:
        return
    payload = {"event": "notification", "type": "planned_action",
               "title": title, "body": body[:200]}
    if conv is not None:
        payload["conv_id"] = str(conv.id)
        payload["wa_id"] = conv.wa_id or conv.external_id
    try:
        await redis.publish("ws:channel:agents:all", json.dumps(payload))
    except Exception:
        pass


# ── Claiming an action ────────────────────────────────────────────────────────
# Sending takes seconds (a model turn composes the text, then Meta answers).
# Checking the status first and writing "sent" after let two senders both
# pass the check — an operator's Send racing the scheduler, or a double tap —
# and let a veto made meanwhile be overwritten by "sent" (the message went
# out anyway). Every send now CLAIMS the row first with one conditional
# UPDATE: only the caller that moves it out of the expected status sends.

PENDING = ("planned", "needs_approval")


async def claim(db, action, from_statuses, to_status: str = "sending") -> bool:
    """Atomically move [action] from one of [from_statuses] to [to_status]
    and commit. False when someone else got there first (or it is gone).
    The in-memory row follows without being marked dirty, so no later
    commit writes a stale status back."""
    from sqlalchemy import update
    from app.models.agent_action import AgentAction
    res = await db.execute(
        update(AgentAction)
        .where(AgentAction.id == action.id,
               AgentAction.status.in_(tuple(from_statuses)))
        .values(status=to_status)
        .execution_options(synchronize_session=False))
    await db.commit()
    won = (res.rowcount or 0) == 1
    if won:
        _mirror(action, status=to_status)
    return won


async def finish(db, action, status: str, draft: str | None = None,
                 reason: str | None = None) -> None:
    """Settle a claimed action (sent / failed / back to where it was)."""
    from sqlalchemy import update
    from app.models.agent_action import AgentAction
    values = {"status": status}
    if draft is not None:
        values["draft"] = draft
    if reason is not None:
        values["reason"] = reason
    await db.execute(update(AgentAction).where(AgentAction.id == action.id)
                     .values(**values).execution_options(synchronize_session=False))
    await db.commit()
    _mirror(action, **values)


def _mirror(action, **values) -> None:
    try:
        from sqlalchemy.orm.attributes import set_committed_value
        for k, v in values.items():
            set_committed_value(action, k, v)
    except Exception:
        for k, v in values.items():
            setattr(action, k, v)


async def _recover_interrupted(db, now: datetime) -> int:
    """A send cut off mid-way (process restart, cancelled request) leaves its
    claim in `sending`, out of every queue. After ten minutes it comes back
    for a human — who checks the thread first: it may have gone out."""
    from sqlalchemy import update
    from app.models.agent_action import AgentAction
    try:
        res = await db.execute(
            update(AgentAction)
            .where(AgentAction.status == "sending",
                   AgentAction.updated_at < now - timedelta(minutes=10))
            .values(status="needs_approval",
                    reason=sa_func.concat(sa_func.coalesce(AgentAction.reason, ""),
                                          " [needs approval: send interrupted — check "
                                          "the thread before sending]"))
            .execution_options(synchronize_session=False))
        await db.commit()
        return res.rowcount or 0
    except Exception as exc:
        _log.warning("could not recover interrupted sends: %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass
        return 0


async def process_due(db, redis, *, now: datetime | None = None, limit: int = 10) -> int:
    """Execute every due planned action: gate → auto-send or needs_approval."""
    from app.models.agent_action import AgentAction
    from app.models.conversation import Conversation
    from app.models.deal import Deal
    from app.services import deals as _deals
    from app.services import intent as _intent
    from app.services import outreach_log as ol
    from app.services import quote_followup
    from app.services import templates as _templates
    from app.services.hub_events import _within_window, is_quiet_hours
    from app.services.messaging import SendOutcomeUnknown

    now = now or datetime.now(timezone.utc)
    await _recover_interrupted(db, now)
    if is_quiet_hours(now):
        return 0
    rows = list((await db.execute(select(AgentAction).where(
        AgentAction.status == "planned",
        AgentAction.due_at <= now,
    ).order_by(AgentAction.due_at).limit(limit))).scalars().all())
    # A kept promise or care about an order goes before a sales nudge: when
    # one customer has both due, the one message this tick is the promise.
    from app.services import outreach_log as _ol_order
    rows.sort(key=lambda a: (1 if message_class(a) == _ol_order.ROUTINE else 0,
                             getattr(a, "due_at", now) or now))

    done = 0
    spoken_to: set = set()          # conversations that got a message this tick
    control = await _control(db, redis)
    for action in rows:
        try:
            conv = (await db.get(Conversation, action.conversation_id)
                    if action.conversation_id else None)
            deal = (await db.get(Deal, action.deal_id)
                    if action.deal_id else None)
            if conv is None:
                action.status = "failed"
                action.reason = (action.reason or "") + " [no conversation]"
                await db.commit()
                continue
            who = conv.wa_id or conv.external_id
            # ONE message per customer per tick (audit A, 2026-11-05): a
            # second sales or promise row due at the same time is merged away
            # (Judas's three "Good morning"s were three such rows); care
            # about their order waits for tomorrow morning instead.
            if conv.id in spoken_to:
                if message_class(action) != ol.TRANSACTIONAL:
                    if await claim(db, action, ("planned",), "vetoed"):
                        await finish(db, action, "vetoed",
                                     reason=f"{action.reason or ''} [merged: another message "
                                            "went to this customer in the same tick]")
                        ol.decision("actions", conv.channel, who, "suppress",
                                    "merged into the message already sent this tick",
                                    kind=getattr(action, "kind", None), action=getattr(action, "id", None))
                else:
                    from app.services.hub_events import next_morning_utc
                    action.due_at = next_morning_utc(now)
                    await db.commit()
                    ol.decision("actions", conv.channel, who, "defer",
                                "another message went to this customer in the same tick",
                                kind=getattr(action, "kind", None), action=getattr(action, "id", None))
                continue
            # The customer asked not to be messaged: routine rows end here;
            # a promise or care row waits for a person's judgement.
            if await _intent.opted_out(db, redis, conv):
                if message_class(action) == ol.ROUTINE:
                    if await claim(db, action, ("planned",), "vetoed"):
                        await finish(db, action, "vetoed",
                                     reason=f"{action.reason or ''} [customer asked not to be messaged]")
                else:
                    if await claim(db, action, ("planned",), "needs_approval"):
                        await finish(db, action, "needs_approval",
                                     reason=with_hold_reason(action.reason,
                                                             "customer asked not to be messaged"))
                ol.decision("actions", conv.channel, who, "suppress",
                            "customer opted out", kind=getattr(action, "kind", None), action=getattr(action, "id", None))
                continue
            # The team owes this customer a confirmation (check_availability):
            # no sales follow-up until it arrives — a quote nudge is withdrawn,
            # a promise waits visibly for a person.
            _check_deal = deal
            if _check_deal is None:
                try:
                    _check_deal = await _deals.open_deal_for(db, conversation_id=conv.id)
                except Exception:
                    _check_deal = None
            _open_item = _deals.team_check_open(_check_deal, now=now) if _check_deal is not None else None
            if _open_item and action.kind in ROUTINE_KINDS:
                if action.kind == quote_followup.QUOTE_KIND:
                    if await claim(db, action, ("planned",), "vetoed"):
                        await finish(db, action, "vetoed",
                                     reason=f"{action.reason or ''} [team check open: {_open_item}]")
                elif await claim(db, action, ("planned",), "needs_approval"):
                    await finish(db, action, "needs_approval",
                                 reason=with_hold_reason(action.reason,
                                                         f"team still confirming: {_open_item}"))
                ol.decision("actions", conv.channel, who, "hold",
                            f"team check open: {_open_item}", kind=getattr(action, "kind", None), action=getattr(action, "id", None))
                await _shadow_count(redis, "hold_team_check")
                continue
            # The deal may have closed since (paid, lost) — a follow-up on a
            # settled deal is noise, not initiative.
            if deal is not None and deal.status != "open":
                action.status = "vetoed"
                action.reason = (action.reason or "") + " [deal closed]"
                await db.commit()
                continue

            # Bounded attempts (cost-surprise probe, 2026-08-18): an action
            # whose compose is BILLED but whose send then raises used to stay
            # `planned` — recomposed every 60s tick, the dearest possible loop
            # in the system (a full model turn a minute, forever). Three
            # attempts, then it parks in needs_approval where a human sends,
            # rewords or discards it. Fail-open: no redis, no counter — the
            # tick cadence still paces it.
            tries = 0
            if redis is not None:
                try:
                    tries = int(await redis.incr(f"actions:tries:{action.id}"))
                    if tries == 1:
                        await redis.expire(f"actions:tries:{action.id}", 7 * 86400)
                except Exception:
                    tries = 0
            if tries > 3:
                action.status = "needs_approval"
                action.reason = with_hold_reason(action.reason,
                                                 "auto-send failed 3× — needs a human")
                await db.commit()
                _log.warning("planned action %s parked after 3 failed attempts",
                             action.id)
                await _notify(redis, "⏳ Follow-up parked after 3 failed tries",
                              (action.reason or "")[:120], conv)
                continue

            in_window = await _within_window(db, conv)
            # A quote follow-up is a nudge on a fresh quote, not a commitment:
            # once the customer has spoken, ordered, gone to a human or the
            # window has shut, it is withdrawn — never parked for a tap.
            is_quote = getattr(action, "kind", None) == quote_followup.QUOTE_KIND
            if is_quote:
                stale = await quote_followup.stale_reason(db, conv, action,
                                                          in_window=in_window, now=now)
                if stale:
                    if await claim(db, action, ("planned",), "vetoed"):
                        await finish(db, action, "vetoed",
                                     reason=f"{action.reason or ''} [{stale}]")
                        _log.info("quote follow-up %s withdrawn: %s", action.id, stale)
                    continue
            # A payment reminder never chases money that has landed: the hub is
            # re-read live at send time; an unconfirmable status waits a day.
            if getattr(action, "kind", None) == "payment_reminder":
                from app.jobs import payment_followup as _pay
                verdict = await _pay.live_verdict(redis, action)
                if verdict == "paid":
                    if await claim(db, action, ("planned",), "vetoed"):
                        await finish(db, action, "vetoed",
                                     reason=f"{action.reason or ''} [paid — nothing to remind]")
                    ol.decision("actions", conv.channel, who, "suppress", "order paid",
                                kind="payment_reminder", action=getattr(action, "id", None))
                    continue
                if verdict == "unknown":
                    from app.services.hub_events import next_morning_utc
                    action.due_at = next_morning_utc(now)
                    await db.commit()
                    ol.decision("actions", conv.channel, who, "defer",
                                "hub status unconfirmable — not chasing on a guess",
                                kind="payment_reminder", action=getattr(action, "id", None))
                    continue
            # What the customer themselves said (Stage 3) — never shadowed:
            # "give me time / I'm comparing / I must ask the bishop" holds every
            # unprompted sales message until the day they named (or a week);
            # a language no automated message can be written in parks the row
            # for a person. A kept promise and care about an order still go.
            from app.services import customer_state as _cs
            if message_class(action) == "routine":
                _hold = await _cs.hold_for(db, action, now=now)
                if _hold:
                    _until, _said = _hold
                    action.due_at = _until
                    await db.commit()
                    ol.decision("actions", conv.channel, who, "hold",
                                f"they asked for time ({_said}) — until {_until.date().isoformat()}",
                                kind=getattr(action, "kind", None), action=getattr(action, "id", None))
                    await _shadow_count(redis, "hold_customer")
                    continue
            _lang = await _cs.language_for(db, conv)
            if not _cs.automated_ok(_lang) and (message_class(action) == "routine"
                                                 or not in_window):
                if await claim(db, action, ("planned",), "needs_approval"):
                    await finish(db, action, "needs_approval",
                                 reason=f"{action.reason or ''} [they write in '{_lang}' — a person should write this]")
                    ol.decision("actions", conv.channel, who, "park", f"language {_lang}",
                                kind=getattr(action, "kind", None), action=getattr(action, "id", None))
                    await _shadow_count(redis, "park_language")
                continue
            # The contextual decision (shadow or enforce — per rule, Stage 5).
            shadow_flags: list[str] = []
            verdict, why = await decide(db, conv, action, now=now)
            if verdict != "go":
                _rule = rule_of(why)
                await _shadow_count(redis, f"rule_{_rule}")
                if control["mode"] == "enforce" or _rule in control["rules"]:
                    if verdict == "suppress":
                        if await claim(db, action, ("planned",), "vetoed"):
                            await finish(db, action, "vetoed", reason=f"{action.reason or ''} [{why}]")
                    else:
                        from app.services.hub_events import next_morning_utc
                        action.due_at = next_morning_utc(now)
                        await db.commit()
                    ol.decision("actions", conv.channel, who, verdict, why,
                                kind=getattr(action, "kind", None), action=getattr(action, "id", None))
                    await _shadow_count(redis, f"enforced_{verdict}")
                    continue
                shadow_flags.append(f"{verdict}: {why}")
                ol.decision("actions", conv.channel, who, f"shadow-{verdict}", why,
                            kind=getattr(action, "kind", None), action=getattr(action, "id", None))
                await _shadow_count(redis, verdict)
            gate = await needs_approval(db, deal, conv, in_window)
            # Fit-checks (~6 days after delivery) and customer-agreed
            # replenishment check-ins ("check with me in two weeks") come due
            # long after the WhatsApp window closed. Both are service
            # follow-ups on the customer's own transaction/request, so they
            # ride the approved UTILITY template instead of dying in the
            # approvals queue.
            _purpose = template_purpose(action)
            if (gate == "outside the 24h messaging window" and _purpose
                    and conv.channel == "whatsapp" and settings.agent_initiative):
                # Vetoed or sent by hand since this tick read it → leave it be.
                if not await claim(db, action, ("planned",)):
                    continue
                try:
                    if await _send_followup_template(db, redis, conv, action, _purpose):
                        spoken_to.add(conv.id)
                        done += 1
                        continue
                except _templates.TemplateRefused as exc:
                    # No template fits (a deciding customer and no approved
                    # follow-up template, a parameter that would read as
                    # nonsense): a person sends it, never an approximation.
                    await finish(db, action, "needs_approval",
                                 reason=with_hold_reason(action.reason,
                                                         f"outside the 24h window — {exc}"))
                    ol.decision("actions", conv.channel, who, "hold", str(exc),
                                kind=getattr(action, "kind", None), action=getattr(action, "id", None))
                    await _shadow_count(redis, "park_template")
                    await _notify(redis, "⏳ Follow-up needs a person",
                                  f"{str(exc)[:100]} — {(action.reason or '')[:80]}", conv)
                    continue
                except SendOutcomeUnknown as exc:
                    await finish(db, action, "needs_approval",
                                 reason=with_hold_reason(action.reason,
                                                         "sent? outcome unknown — check the thread before resending"))
                    _log.warning("template for action %s: outcome unknown (%s)", action.id, exc)
                    continue
                except Exception as exc:
                    _log.warning("%s template send failed for %s: %s", action.kind, who, exc)
                # The template didn't go: back to planned for the usual path.
                await finish(db, action, "planned")
            if gate is not None:
                draft = ""
                if is_quote:
                    draft = action.draft or ""   # composed from the quote — kept as is
                else:
                    try:
                        draft = await _compose_follow_up(db, redis, conv,
                                                         action.reason or "follow up")
                    except Exception as exc:
                        _log.info("draft for held action %s not composed: %s", action.id, exc)
                # Conditional: a veto made while composing stands.
                if not await claim(db, action, ("planned",), "needs_approval"):
                    continue
                await finish(db, action, "needs_approval", draft=(draft or None),
                             reason=with_hold_reason(action.reason, gate))
                await _notify(redis, "⏳ Follow-up needs your approval",
                              f"{gate} — draft ready: {(draft or '')[:80]}", conv)
                continue

            if not settings.agent_initiative:
                # Flag off: leave it planned, visible — the trust-building mode.
                continue

            # A quote follow-up or a payment reminder sends the text composed in
            # code when it was planned — its figures can't drift; everything
            # else is composed now, into the open conversation.
            code_composed = getattr(action, "kind", None) in CODE_COMPOSED_KINDS
            text = ((action.draft or "").strip() if code_composed else
                    await _compose_follow_up(db, redis, conv, action.reason or "follow up"))
            if not text:
                action.status = "failed"
                await db.commit()
                continue
            # Never nudge someone with a message they've already had. If the
            # composer only managed to echo an earlier line, a human rewords it.
            repeats = (await _repeats_earlier(db, conv, text, exact_only=True) if code_composed
                       else await _repeats_earlier(db, conv, text))
            if repeats:
                if not await claim(db, action, ("planned",), "needs_approval"):
                    continue
                await finish(db, action, "needs_approval", draft=text,
                             reason=with_hold_reason(
                                 action.reason, "draft repeats an earlier message — reword it"))
                _log.info("planned action %s held — draft repeats an earlier message",
                          action.id)
                await _notify(redis, "⏳ Follow-up needs a reword",
                              "Neema's draft repeats what she already said: "
                              f"{text[:80]}", conv)
                continue
            # Claim it: an operator may have vetoed or sent it while the
            # text was being composed.
            if not await claim(db, action, ("planned",)):
                _log.info("planned action %s changed while composing — not sent", action.id)
                continue
            try:
                await _send(db, redis, conv, text, action, shadow=shadow_flags)
            except SendOutcomeUnknown as exc:
                # Meta may have delivered it: the row is recorded as unknown
                # and a person decides — never an automatic resend.
                await finish(db, action, "needs_approval", draft=text,
                             reason=with_hold_reason(
                                 action.reason, "sent? outcome unknown — check the thread before resending"))
                ol.decision("actions", conv.channel, who, "hold", f"outcome unknown: {exc}",
                            kind=getattr(action, "kind", None), action=getattr(action, "id", None))
                await _shadow_count(redis, "unknown_outcome")
                spoken_to.add(conv.id)
                continue
            except Exception:
                # Nothing went out: planned again, for the next tick (bounded
                # by the 3-tries counter above).
                await finish(db, action, "planned")
                raise
            await finish(db, action, "sent", draft=text)
            spoken_to.add(conv.id)
            # The recovery reports keep counting what the planners started.
            if getattr(action, "source", None) in ("cart_recovery", "payment_followup"):
                try:
                    from app.services.recovery_results import record_send
                    await record_send(action.source, conv,
                                      ref=(getattr(action, "dedupe_key", "") or "").split(":", 1)[-1])
                except Exception:
                    pass
            ol.decision("actions", conv.channel, who, "send", "planned action sent",
                        kind=getattr(action, "kind", None), action=getattr(action, "id", None), cls=message_class(action))
            done += 1
            _log.info("planned action %s sent to %s", action.id,
                      conv.wa_id or conv.external_id)
        except Exception as exc:
            _log.warning("planned action %s failed: %s", action.id, exc)
            try:
                await db.rollback()
            except Exception:
                pass
    return done


async def actions_loop(redis) -> None:
    """60s tick, leader-locked — the heartbeat of Neema's initiative."""
    from app.database import AsyncSessionLocal
    while True:
        try:
            await asyncio.sleep(60)
            if redis is None:
                continue
            got = await redis.set(LEADER_KEY, "1", nx=True, ex=55)
            if not got:
                continue
            async with AsyncSessionLocal() as db:
                await process_due(db, redis)
            # Copilot C4 rides the same heartbeat: quiet human-held threads
            # get their once-a-day "take it back?" ping.
            try:
                from app.services.copilot import take_back_scan
                async with AsyncSessionLocal() as db:
                    await take_back_scan(db, redis)
            except Exception:
                pass
            # Inbound Meta photos/videos arrive as signed CDN links that expire
            # within days. Re-host anything still on one, so the inbox never
            # loses sight of what a customer actually sent.
            try:
                from app.services.meta_media import repair_pending
                async with AsyncSessionLocal() as db:
                    await repair_pending(db)
            except Exception as exc:
                _log.info("meta media repair skipped: %s", exc)
            # Outcome self-check (services/selfcheck.py): most subsystems here
            # are best-effort, so a broken one looks identical to a quiet one.
            # Hourly, leader-only; a failed tick is itself logged loudly.
            try:
                hour_key = "selfcheck:" + datetime.now(timezone.utc).strftime("%Y%m%d%H")
                if await redis.set(hour_key, "1", nx=True, ex=3600):
                    from app.services.selfcheck import run_checks
                    async with AsyncSessionLocal() as db:
                        await run_checks(db, redis)
            except Exception as exc:
                _log.warning("selfcheck tick failed: %s", exc)
            # Learning loops (plan D): 03:00 self-QA, 08:00 standup,
            # Sunday 07:00 weekly distillation — daily-guarded, leader-only.
            try:
                from datetime import datetime as _dt, timedelta as _td, timezone as _tz
                from app.jobs import self_qa as _qa
                nbo = _dt.now(_tz.utc) + _td(hours=3)
                today = nbo.strftime("%Y%m%d")
                if nbo.hour == 3 and await redis.set(f"selfqa:{today}", "1", nx=True, ex=86400):
                    async with AsyncSessionLocal() as db:
                        await _qa.run_qa(db)
                # 06:00: identify the page's recent posts BEFORE anyone
                # comments — comments look up, they never guess.
                # Sunday 05:00: the stylebook re-learns the house voice from
                # the week's human replies — the textbook follows the team
                # without anyone remembering a script (zero model cost).
                if (nbo.weekday() == 6 and nbo.hour == 5
                        and await redis.set(f"stylebook:{today}", "1", nx=True, ex=86400)):
                    from app.tools.stylebook import refresh as _style_refresh
                    async with AsyncSessionLocal() as db:
                        await _style_refresh(db, redis)
                if nbo.hour == 6 and await redis.set(f"postsweep:{today}", "1", nx=True, ex=86400):
                    from app.services.post_catalog import sweep_page_posts
                    async with AsyncSessionLocal() as db:
                        await sweep_page_posts(db, redis)
                if nbo.hour == 8 and await redis.set(f"standup:{today}", "1", nx=True, ex=86400):
                    async with AsyncSessionLocal() as db:
                        standup = await _qa.compose_standup(db)
                    await redis.publish("ws:channel:agents:all", json.dumps({
                        "event": "notification", "type": "standup",
                        "title": "☀️ Neema's morning standup",
                        "body": standup[:400]}))
                if (nbo.weekday() == 6 and nbo.hour == 7 and
                        await redis.set(f"distill:{nbo.strftime('%G%V')}", "1",
                                        nx=True, ex=8 * 86400)):
                    async with AsyncSessionLocal() as db:
                        await _qa.distill_weekly(db)
            except Exception as exc:
                _log.info("learning-loop tick skipped: %s", exc)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _log.warning("actions loop tick failed: %s", exc)
