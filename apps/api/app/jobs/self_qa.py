"""The learning loops (plan D2-D4): Neema reviews her own work every night,
reports to the owner every morning, and turns the week's lessons into rule
proposals the owner approves or rejects.

Rules-first detectors (cheap, deterministic):
  · repeated_question — the same discovery question asked twice (the single
    most robotic failure; the SLOT CHECK rule exists to prevent it)
  · missed_close — clear buying intent with no order/payment move in the next
    AI replies

Approved proposals land in app_settings.learned_rules and are injected into
her prompt alongside the standing orders.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

_log = logging.getLogger("neema.selfqa")

_BUY_INTENT_RE = re.compile(
    r"\b(i(?:'| wi)ll take|nataka ku(?:nunua|lipa)|how do i pay|nitalipa|"
    r"send (?:me )?the (?:bill|invoice|total)|ready to pay|place the order)\b",
    re.IGNORECASE)
_CLOSE_MARKER_RE = re.compile(
    r"(order|payment|m-?pesa|paybill|checkout|pay here|total)", re.IGNORECASE)

LEARNED_RULES_KEY = "learned_rules"
PROPOSALS_KEY = "rule_proposals"
LEARNED_RULES_MAX = 1200


def _tokens(s: str) -> set:
    return {w for w in re.findall(r"[a-z']+", (s or "").lower()) if len(w) > 2}


def is_repeated_question(a: str, b: str) -> bool:
    """Two AI messages asking (near) the same thing."""
    if "?" not in (a or "") or "?" not in (b or ""):
        return False
    ta, tb = _tokens(a), _tokens(b)
    if len(ta) < 3 or len(tb) < 3:
        return False
    # Containment, not Jaccard: 'which colour would you like' vs 'what colour
    # would you like' is the same question despite the wording drift.
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return overlap >= 0.7


def find_issues(messages: list[dict]) -> list[dict]:
    """messages: [{direction, sender, text}] in order → findings."""
    out = []
    ai = [(i, m) for i, m in enumerate(messages)
          if m.get("direction") == "outbound" and (m.get("text") or "").strip()]
    for (i1, m1), (i2, m2) in zip(ai, ai[1:]):
        if is_repeated_question(m1["text"], m2["text"]):
            out.append({"kind": "repeated_question",
                        "detail": (m2["text"] or "")[:200]})
    for i, m in enumerate(messages):
        if m.get("direction") == "inbound" and _BUY_INTENT_RE.search(m.get("text") or ""):
            after = [x for x in messages[i + 1:i + 4]
                     if x.get("direction") == "outbound"]
            if after and not any(_CLOSE_MARKER_RE.search(x.get("text") or "") for x in after):
                out.append({"kind": "missed_close",
                            "detail": (m.get("text") or "")[:200]})
    return out


async def run_qa(db) -> int:
    """Grade yesterday's conversations; store findings. Returns finding count."""
    from app.models.conversation import Conversation
    from app.models.message import Message
    from app.models.agent_feedback import QaFinding
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    convs = (await db.execute(select(Conversation).where(
        Conversation.last_message_at >= since).limit(40))).scalars().all()
    total = 0
    for conv in convs:
        where = ((Message.wa_id == conv.wa_id) if conv.channel == "whatsapp" else
                 ((Message.channel == conv.channel) & (Message.external_id == conv.external_id)))
        rows = (await db.execute(
            select(Message).where(where)
            .where(Message.media_type.is_(None) | (Message.media_type != "note"))
            .order_by(Message.created_at).limit(60))).scalars().all()
        msgs = [{"direction": str(getattr(m.direction, "value", m.direction)),
                 "text": m.text or ""} for m in rows]
        for f in find_issues(msgs):
            db.add(QaFinding(conversation_id=conv.id, kind=f["kind"],
                             detail=f["detail"]))
            total += 1
    await db.commit()
    if total:
        _log.info("self-QA: %d finding(s) from %d conversation(s)", total, len(convs))
    return total


async def compose_standup(db) -> str:
    """Yesterday in one message: activity, wins, misses, what needs the owner."""
    from sqlalchemy import func as sa_func
    from app.models.conversation import Conversation
    from app.models.deal import Deal
    from app.models.agent_action import AgentAction
    from app.models.agent_feedback import QaFinding
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    convs = (await db.execute(select(sa_func.count()).select_from(Conversation)
                              .where(Conversation.last_message_at >= since))).scalar_one()
    won = (await db.execute(select(sa_func.count()).select_from(Deal)
                            .where(Deal.status == "won",
                                   Deal.updated_at >= since))).scalar_one()
    approvals = (await db.execute(select(sa_func.count()).select_from(AgentAction)
                                  .where(AgentAction.status == "needs_approval"))).scalar_one()
    findings = (await db.execute(select(QaFinding)
                                 .where(QaFinding.created_at >= since)
                                 .order_by(QaFinding.created_at.desc())
                                 .limit(3))).scalars().all()
    lines = [f"☀️ Standup — last 24h: {convs} active conversations, {won} deal(s) won."]
    if approvals:
        lines.append(f"⏳ {approvals} follow-up(s) await your approval on the Deals board.")
    if findings:
        lines.append("🪞 I caught myself: " + "; ".join(
            f"{f.kind.replace('_', ' ')} ({(f.detail or '')[:60]}…)" for f in findings))
    else:
        lines.append("🪞 Self-review: no misses caught yesterday.")

    # What the brain cost — measured, not guessed. Invisible spend is how the
    # account ran dry with nobody warned; one line a day keeps it seen.
    try:
        from app.models.ai_usage import AiUsage
        spend, calls = (await db.execute(
            select(sa_func.coalesce(sa_func.sum(AiUsage.cost_usd), 0), sa_func.count())
            .select_from(AiUsage).where(AiUsage.created_at >= since))).one()
        if calls:
            lines.append(f"💳 AI spend: ${float(spend):.2f} across {calls} model call(s).")
    except Exception:
        pass

    # System health — the hourly outcome self-check's last verdict, so a dead
    # subsystem reaches the owner by breakfast, not by archaeology.
    try:
        from app.services.selfcheck import health_line
        health = await health_line(db)
        if health:
            lines.append(health)
    except Exception:
        pass

    # Unmet demand — what customers asked for that we couldn't sell. The pile
    # exists to be read: three lines a day beat a table nobody opens.
    try:
        from app.models.demand_signal import DemandSignal
        week = datetime.now(timezone.utc) - timedelta(days=7)
        top = (await db.execute(
            select(DemandSignal.query, sa_func.count().label("n"))
            .where(DemandSignal.created_at >= week)
            .group_by(DemandSignal.query)
            .order_by(sa_func.count().desc()).limit(3))).all()
        if top:
            lines.append("📈 Most asked-for this week (unmet): " +
                         ", ".join(f"{q} ×{n}" for q, n in top))
    except Exception:
        pass
    return "\n".join(lines)


async def distill_weekly(db, llm=None) -> int:
    """The week's corrections + findings → up to 3 proposed rules (owner
    approves in Settings). Returns proposal count."""
    from app.models.agent_feedback import AgentFeedback, QaFinding
    from app.services.app_settings import set_value
    since = datetime.now(timezone.utc) - timedelta(days=7)
    fb = (await db.execute(select(AgentFeedback)
                           .where(AgentFeedback.created_at >= since)
                           .limit(30))).scalars().all()
    qa = (await db.execute(select(QaFinding)
                           .where(QaFinding.created_at >= since)
                           .limit(30))).scalars().all()
    if not fb and not qa:
        return 0
    evidence = []
    for f in fb[:15]:
        evidence.append(f"EDIT — Neema wrote: {f.draft[:160]!r} → human sent: {f.sent[:160]!r}")
    kinds: dict[str, int] = {}
    for q in qa:
        kinds[q.kind] = kinds.get(q.kind, 0) + 1
    for k, n in kinds.items():
        evidence.append(f"QA — {k} occurred {n}x this week")

    proposals: list[str] = []
    try:
        if llm is None:
            from app.agent.runtime import build_llm
            llm = build_llm()
        resp = await llm.complete(
            system=("You improve a sales agent's standing rules. From the evidence "
                    "of human edits and QA findings, propose AT MOST 3 short, "
                    "concrete behavioural rules (one line each, imperative, no "
                    "numbering). Only rules the evidence clearly supports. "
                    "Output one rule per line, nothing else."),
            messages=[{"role": "user", "content": "\n".join(evidence)}],
            tools=[])
        proposals = [ln.strip("-• ").strip() for ln in (resp.text or "").split("\n")
                     if ln.strip()][:3]
    except Exception as exc:
        _log.info("distillation LLM unavailable: %s", exc)
        return 0
    if proposals:
        await set_value(db, PROPOSALS_KEY,
                        json.dumps([{"rule": p, "status": "pending"} for p in proposals]))
        _log.info("distillation: %d rule proposal(s) stored", len(proposals))
    return len(proposals)
