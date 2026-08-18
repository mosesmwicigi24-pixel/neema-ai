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


_PRICE_Q_RE = re.compile(
    r"\b(how much|price|bei(\s+gani)?|ngapi|pesa ngapi|cost)\b", re.IGNORECASE)
_SELL_MARKER_RE = re.compile(
    r"(KES\s*\d|USD\s*\d|would you like|how many|payment link|checkout|"
    r"ready to (order|pay))", re.IGNORECASE)


def find_issues(messages: list[dict]) -> list[dict]:
    """messages: [{direction, sender, text}] in order → findings."""
    out = []
    try:
        from app.agent.runtime import looks_negative
    except Exception:                       # pragma: no cover — runtime unimportable
        def looks_negative(s):
            return False
    ai = [(i, m) for i, m in enumerate(messages)
          if m.get("direction") == "outbound" and (m.get("text") or "").strip()]
    for (i1, m1), (i2, m2) in zip(ai, ai[1:]):
        if is_repeated_question(m1["text"], m2["text"]):
            out.append({"kind": "repeated_question",
                        "detail": (m2["text"] or "")[:200]})
    for i, m in enumerate(messages):
        if m.get("direction") != "inbound":
            continue
        text = m.get("text") or ""
        after = [x for x in messages[i + 1:i + 4]
                 if x.get("direction") == "outbound"][:2]
        if _BUY_INTENT_RE.search(text):
            if after and not any(_CLOSE_MARKER_RE.search(x.get("text") or "") for x in after):
                out.append({"kind": "missed_close", "detail": text[:200]})
        if not after:
            continue
        # A price question answered without a single number is a non-answer —
        # the "repeated how much?" failure, caught the night it happens.
        if _PRICE_Q_RE.search(text) and not any(
                re.search(r"\d", x.get("text") or "") for x in after):
            out.append({"kind": "price_unanswered", "detail": text[:200]})
        # Selling into displeasure — the Florence failure, watched nightly.
        if looks_negative(text) and any(
                _SELL_MARKER_RE.search(x.get("text") or "") for x in after):
            out.append({"kind": "sold_into_complaint", "detail": text[:200]})
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
            line = f"💳 AI spend: ${float(spend):.2f} across {calls} model call(s)."
            # The breakdown is a NICETY on top of the number that matters, so
            # it gets its own guard: a shape the detail queries dislike must
            # never cost the owner the spend line itself.
            #
            # WHERE the money went, and whether the cache is earning its keep.
            # Spend alone said nothing actionable: the same total means one
            # thing if the ~16k-token rules+tools prefix is being READ from
            # cache (0.1x) and quite another if it is paid for fresh (1x) on
            # every call. The per-model split shows whether the light-model
            # routing is catching the high-volume comment replies, and the
            # per-node split shows comments vs conversations now that every
            # row's node carries the channel (":comment" for public replies).
            try:
                by_model = (await db.execute(
                    select(AiUsage.model, sa_func.sum(AiUsage.cost_usd))
                    .where(AiUsage.created_at >= since)
                    .group_by(AiUsage.model)
                    .order_by(sa_func.sum(AiUsage.cost_usd).desc()).limit(3))).all()
                if by_model:
                    line += " " + ", ".join(
                        f"{(m or 'unknown').split('-')[1] if m and '-' in m else (m or 'unknown')}"
                        f" ${float(c or 0):.2f}" for m, c in by_model)
                by_node = (await db.execute(
                    select(AiUsage.node, sa_func.sum(AiUsage.cost_usd))
                    .where(AiUsage.created_at >= since)
                    .group_by(AiUsage.node)
                    .order_by(sa_func.sum(AiUsage.cost_usd).desc()).limit(2))).all()
                if by_node and any(n for n, _ in by_node):
                    line += " · " + ", ".join(
                        f"{(n or '?')} ${float(c or 0):.2f}" for n, c in by_node)
                cached, fresh = (await db.execute(
                    select(sa_func.coalesce(sa_func.sum(AiUsage.cached_tokens), 0),
                           sa_func.coalesce(sa_func.sum(AiUsage.prompt_tokens), 0))
                    .where(AiUsage.created_at >= since))).one()
                if fresh:
                    hit = 100.0 * float(cached or 0) / float(fresh)
                    line += f" · prompt cache hit {hit:.0f}%"
            except Exception:
                pass
            lines.append(line)
    except Exception:
        pass

    # Promises made visible: the planned follow-ups — including answers Neema
    # owes customers — lived only on the Deals board nobody opens daily.
    try:
        from app.models.agent_action import AgentAction
        now = datetime.now(timezone.utc)
        due = (await db.execute(select(sa_func.count()).select_from(AgentAction)
                                .where(AgentAction.status == "planned",
                                       AgentAction.due_at <= now + timedelta(hours=24)))
               ).scalar_one()
        overdue = (await db.execute(select(sa_func.count()).select_from(AgentAction)
                                    .where(AgentAction.status == "planned",
                                           AgentAction.due_at < now))).scalar_one()
        if due:
            lines.append(f"🤝 {due} follow-up(s) due in the next 24h"
                         + (f" ({overdue} already overdue)" if overdue else "")
                         + " — see the Deals board.")
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

    # Hub-bridge migration watch: authenticated pushes still arriving on the
    # legacy /api/n8n surface. When this line stays absent for ~a week after
    # the hub plugin switches, dropping the legacy mount is evidence-backed
    # (docs/HUB_BRIDGE_MIGRATION.md).
    try:
        from app.main import app as _app
        _redis = getattr(_app.state, "redis", None)
        if _redis is not None:
            _y = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
            _n = int(await _redis.get(f"bridge:legacy:{_y}") or 0)
            if _n:
                lines.append(
                    f"🌉 Hub bridge: {_n} push(es) yesterday still used the legacy "
                    "/api/n8n path — the hub plugin hasn't fully migrated "
                    "(docs/HUB_BRIDGE_MIGRATION.md).")
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
