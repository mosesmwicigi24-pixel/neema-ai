"""The executive performance view (intelligence programme §7, 2026-11-06).

Every figure here is one of three things, and says which:
  measured      — computed from stored outcomes or timestamps, with its
                  denominator and a 95% Wilson interval where it is a proportion
  partial       — measured, but on a denominator narrower than the question
                  (e.g. Neema-placed orders only: hub/POS orders are not ingested)
  not_measured  — no reliable data exists yet; the row names the instrumentation
                  that would produce it
Nothing is estimated. A `previous` value, when present, is the same metric on
the window before this one, so a trend is a comparison of two measurements.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

PAID_STATES = ("paid", "completed", "settled", "success", "successful", "complete")


def _wilson(k: int, n: int) -> list[float] | None:
    if n <= 0:
        return None
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def _prop(k: int, n: int) -> dict:
    return {"k": int(k), "n": int(n), "p": (round(k / n, 3) if n else None), "ci95": _wilson(k, n)}


def _trend(cur, prev) -> str | None:
    if cur is None or prev is None:
        return None
    if abs(cur - prev) < 1e-9:
        return "flat"
    return "up" if cur > prev else "down"


def _measured(label: str, value, *, unit: str = "", n: int | None = None, ci95=None, basis: str,
              previous=None, caveat: str = "", status: str = "measured") -> dict:
    return {"label": label, "status": status, "value": value, "unit": unit, "n": n, "ci95": ci95,
            "basis": basis, "caveat": caveat, "previous": previous, "trend": _trend(value, previous)}


def _not_measured(label: str, *, needs: str, basis: str = "") -> dict:
    return {"label": label, "status": "not_measured", "value": None, "unit": "", "n": None, "ci95": None,
            "basis": basis, "caveat": "", "instrumentation": needs, "previous": None, "trend": None}


# ── the queries ──────────────────────────────────────────────────────────────

_FIRST_RESPONSE_SQL = text("""
WITH inbound AS (
  SELECT m.id, m.conversation_id, m.created_at,
         LEAD(m.created_at) OVER (PARTITION BY m.conversation_id ORDER BY m.created_at) AS next_at,
         LEAD(m.direction::text) OVER (PARTITION BY m.conversation_id ORDER BY m.created_at) AS next_dir,
         LEAD(m.sender::text) OVER (PARTITION BY m.conversation_id ORDER BY m.created_at) AS next_sender
  FROM messages m
  WHERE m.created_at >= :since AND m.created_at < :until
    AND m.conversation_id IS NOT NULL AND COALESCE(m.media_type, '') <> 'note'
)
SELECT next_sender,
       count(*) AS n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (next_at - created_at))) AS median_s,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (next_at - created_at))) AS p90_s
FROM inbound
WHERE next_dir = 'outbound' AND next_at IS NOT NULL
GROUP BY next_sender
""")

_ORDERS_SQL = text("""
SELECT count(*) AS orders,
       count(*) FILTER (WHERE lower(COALESCE(hub_payment_status, payment_status, '')) = ANY(:paid)) AS paid,
       COALESCE(sum(COALESCE(hub_total, subtotal)) FILTER (WHERE lower(COALESCE(hub_payment_status, payment_status, '')) = ANY(:paid)), 0) AS paid_revenue,
       COALESCE(sum(COALESCE(hub_total, subtotal)), 0) AS placed_revenue
FROM order_events
WHERE created_at >= :since AND created_at < :until AND COALESCE(status, '') <> 'cancelled'
""")

_SALES_SPLIT_SQL = text("""
SELECT
  count(*) FILTER (WHERE h.n_human = 0) AS autonomous,
  count(*) FILTER (WHERE h.n_human > 0) AS assisted
FROM (
  SELECT o.id,
         (SELECT count(*) FROM messages m
            WHERE m.wa_id = o.wa_id AND m.sender::text = 'human_agent'
              AND m.created_at < o.created_at
              AND m.created_at >= o.created_at - interval '14 days'
              AND COALESCE(m.media_type, '') <> 'note') AS n_human
  FROM order_events o
  WHERE o.created_at >= :since AND o.created_at < :until AND COALESCE(o.status, '') <> 'cancelled'
) h
""")

_ACTIVE_CONVERSATIONS_SQL = text("""
SELECT count(DISTINCT conversation_id) FROM messages
WHERE created_at >= :since AND created_at < :until AND direction::text = 'inbound'
""")

_INTERVENTIONS_SQL = text("""
SELECT count(DISTINCT conversation_id) FROM intercepts
WHERE created_at >= :since AND created_at < :until
""")

_OPT_OUTS_SQL = text("""
SELECT count(*) AS total,
       count(*) FILTER (WHERE (state->'contact_preferences'->'opt_out'->>'at') >= :since_iso) AS in_window
FROM persons
WHERE state->'contact_preferences'->'opt_out' IS NOT NULL
""")

_COST_SQL = text("""
SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls,
       count(DISTINCT wa_id) FILTER (WHERE wa_id IS NOT NULL) AS contacts
FROM ai_usage WHERE created_at >= :since AND created_at < :until
""")


async def _window(db, since: datetime, until: datetime) -> dict:
    p = {"since": since, "until": until}
    out: dict = {}
    fr = (await db.execute(_FIRST_RESPONSE_SQL, p)).mappings().all()
    out["first_response"] = {r["next_sender"]: {"n": int(r["n"]), "median_s": float(r["median_s"] or 0),
                                                "p90_s": float(r["p90_s"] or 0)} for r in fr}
    o = (await db.execute(_ORDERS_SQL, {**p, "paid": list(PAID_STATES)})).mappings().first() or {}
    out["orders"] = {"orders": int(o.get("orders") or 0), "paid": int(o.get("paid") or 0),
                     "paid_revenue": float(o.get("paid_revenue") or 0),
                     "placed_revenue": float(o.get("placed_revenue") or 0)}
    s = (await db.execute(_SALES_SPLIT_SQL, p)).mappings().first() or {}
    out["split"] = {"autonomous": int(s.get("autonomous") or 0), "assisted": int(s.get("assisted") or 0)}
    out["active"] = int((await db.execute(_ACTIVE_CONVERSATIONS_SQL, p)).scalar() or 0)
    out["interventions"] = int((await db.execute(_INTERVENTIONS_SQL, p)).scalar() or 0)
    c = (await db.execute(_COST_SQL, p)).mappings().first() or {}
    out["cost"] = {"usd": float(c.get("usd") or 0), "calls": int(c.get("calls") or 0),
                   "contacts": int(c.get("contacts") or 0)}
    return out


async def collect(db, redis, *, days: int = 7, now: datetime | None = None) -> dict:
    """The whole view. Every metric carries its status; nothing is estimated."""
    days = max(1, min(int(days), 90))
    now = now or datetime.now(timezone.utc)
    since, prev_since = now - timedelta(days=days), now - timedelta(days=2 * days)
    cur = await _window(db, since, now)
    prev = await _window(db, prev_since, since)
    metrics: dict[str, dict] = {}

    # ── evaluation-based (the case set through the real model) ──
    history: list[dict] = []
    try:
        from app.services.app_settings import get_value
        raw = await get_value(db, "eval_history")
        history = json.loads(raw) if raw else []
    except Exception:
        history = []
    # Only BLIND runs count as measured (verification pass 4): the dev and
    # held-out halves were tuned on, so a row from them is a diagnostic, not
    # a measurement, and a trend must never mix the two.
    blind = [h for h in history if str(h.get("selection") or "").startswith("file:blind")]
    last = blind[-1] if blind else None
    first = blind[0] if blind else None

    def _eval_metric(label, key, needs):
        if not last or not (last.get(key) or {}).get("n"):
            return _not_measured(label, needs=needs, basis="app_settings.eval_history (blind runs only)")
        m = last[key]
        base = (first or {}).get(key) or {}
        return _measured(label, m.get("p"), unit="proportion", n=m.get("n"), ci95=m.get("ci95"),
                         basis=f"blind-set run {last.get('at', '')[:10]} on {last.get('git', '')}, {last.get('cases')} cases, "
                               f"producer {last.get('producer')}",
                         previous=(base.get("p") if first is not last and len(blind) > 1 else None),
                         caveat="the blind held-out set only; objective verdicts, no model judge")

    metrics["intent_next_action"] = _eval_metric(
        "Intent and next-action accuracy", "turns",
        needs="run `python -m app.jobs.agent_eval --cases --file blind_heldout.jsonl --history` "
              "(scripts/eval-blind.sh on the box, or the agent-eval workflow)")
    metrics["critical_safety"] = _eval_metric(
        "Critical-case correctness (consent, payment, invented facts)", "critical",
        needs="same run; the critical slice of the case set")
    metrics["language_continuity"] = _eval_metric(
        "Language continuity", "language", needs="same run")
    metrics["figures_verified"] = _eval_metric(
        "Price and figure accuracy (every figure from the hub)", "figures", needs="same run")
    metrics["emotional_appropriateness"] = _not_measured(
        "Emotional appropriateness on hard cases",
        needs="human raters score the rater packet (`--packet`) on the emotion dimension; a model judge alone does not count")
    metrics["consultative_judgment"] = _not_measured(
        "Consultative sales judgment",
        needs="human raters on the sales dimension of the rater packet; the `pressure` gate rule gives the objective floor")
    metrics["customer_rating"] = _not_measured(
        "Customer-rated experience",
        needs="a post-conversation rating ask (an unprompted message — needs the owner's approval) stored per conversation")
    metrics["autonomous_task_completion"] = _not_measured(
        "Correct autonomous task completion (sandbox)",
        needs="the case-set run's business-state assertions (cart/order/quote end states) — add end-state checks to agent_eval --cases")
    metrics["onboarding_success"] = _not_measured(
        "Onboarding: enquiry to quotation without repeated questions",
        needs="the `memory`/`onboarding` slices of the case-set run (forbid re-asked facts)")
    metrics["resolution"] = _not_measured(
        "End-to-end resolution",
        needs="a resolution definition (research memo §4: confirmed, or assumed by silence and reversed on return) and a per-conversation outcome record")

    # ── stored outcomes and timestamps ──
    fr_ai, fr_h = cur["first_response"].get("ai"), cur["first_response"].get("human_agent")
    pfr_ai = prev["first_response"].get("ai")
    metrics["first_response_neema"] = (
        _measured("First response by Neema (median)", round(fr_ai["median_s"], 1), unit="seconds", n=fr_ai["n"],
                  basis="messages: inbound → next outbound by Neema, same conversation",
                  previous=(round(pfr_ai["median_s"], 1) if pfr_ai else None),
                  caveat=f"p90 {round(fr_ai['p90_s'], 1)} s; includes the 30 s WhatsApp debounce by design")
        if fr_ai else _not_measured("First response by Neema (median)", needs="inbound messages in the window"))
    metrics["first_response_human"] = (
        _measured("First response by a colleague (median)", round(fr_h["median_s"] / 60, 1), unit="minutes", n=fr_h["n"],
                  basis="messages: inbound → next outbound by a human, same conversation")
        if fr_h else _not_measured("First response by a colleague (median)", needs="human replies in the window"))

    o, po = cur["orders"], prev["orders"]
    conv_pp = _prop(o["paid"], o["orders"])
    metrics["verified_paid_conversion"] = _measured(
        "Verified paid-order conversion (paid ÷ Neema-placed orders)", conv_pp["p"], unit="proportion",
        n=o["orders"], ci95=conv_pp["ci95"],
        basis="order_events.hub_payment_status / payment_status in the hub's paid states",
        previous=_prop(po["paid"], po["orders"])["p"], status="partial",
        caveat="Neema-placed orders only — hub/POS/human-only orders are not ingested")
    active_pp = _prop(o["paid"], cur["active"])
    metrics["paid_orders_per_active_conversation"] = _measured(
        "Paid orders ÷ conversations with an inbound message", active_pp["p"], unit="proportion",
        n=cur["active"], ci95=active_pp["ci95"], basis="order_events × messages",
        previous=_prop(po["paid"], prev["active"])["p"], status="partial",
        caveat="same denominator caveat; a conversation may pay in a later window")
    metrics["revenue_paid"] = _measured(
        "Revenue — paid (hub-confirmed)", round(o["paid_revenue"], 2), unit="mixed currencies as stored",
        n=o["paid"], basis="sum of hub_total (else subtotal) over paid order_events",
        previous=round(po["paid_revenue"], 2), status="partial",
        caveat="Neema-placed only; currencies not converted")
    metrics["revenue_placed_unpaid"] = _measured(
        "Revenue — placed but not yet paid", round(o["placed_revenue"] - o["paid_revenue"], 2),
        unit="mixed currencies as stored", n=o["orders"] - o["paid"],
        basis="order_events not in a paid state", previous=round(po["placed_revenue"] - po["paid_revenue"], 2),
        status="partial", caveat="this is the figure the Overview page calls 'revenue' today")
    sp, psp = cur["split"], prev["split"]
    metrics["sales_autonomous"] = _measured(
        "Orders with no human message in the 14 days before (Neema-autonomous)", sp["autonomous"], unit="orders",
        n=sp["autonomous"] + sp["assisted"], basis="order_events × messages(sender=human_agent)",
        previous=psp["autonomous"], status="partial", caveat="Neema-placed only")
    metrics["sales_assisted"] = _measured(
        "Orders with a human message before (Neema-assisted)", sp["assisted"], unit="orders",
        n=sp["autonomous"] + sp["assisted"], basis="same", previous=psp["assisted"], status="partial")
    metrics["sales_human_only"] = _not_measured(
        "Human-only sales", needs="hub order ingestion for orders not placed through Neema (the hub's order feed → order_events)")

    iv = _prop(cur["interventions"], cur["active"])
    metrics["human_intervention"] = _measured(
        "Conversations a person intervened in ÷ active conversations", iv["p"], unit="proportion",
        n=cur["active"], ci95=iv["ci95"], basis="intercepts × messages",
        previous=_prop(prev["interventions"], prev["active"])["p"])
    metrics["avoidable_escalation"] = _not_measured(
        "Avoidable escalations", needs="a label on each intercept (needed / avoidable) from the person who took it")

    # follow-ups and opt-outs
    try:
        from app.services.recovery_results import results as _recovery
        rec = await _recovery(db, days)
        sent = sum(j["sent"] for j in rec["jobs"])
        settled = sum(j["settled"] for j in rec["jobs"])
        replied = sum(j["replied"] for j in rec["jobs"])
        converted = sum(j["converted"] for j in rec["jobs"])
        rp, cp = _prop(replied, settled), _prop(converted, settled)
        metrics["follow_up_reply_rate"] = _measured(
            "Follow-ups answered within 72 h ÷ follow-ups settled", rp["p"], unit="proportion", n=settled,
            ci95=rp["ci95"], basis="recovery_sends ∪ agent_actions(sent) × messages", caveat=f"{sent} sent in window")
        metrics["follow_up_convert_rate"] = _measured(
            "Follow-ups followed by an order or payment within 7 d", cp["p"], unit="proportion", n=settled,
            ci95=cp["ci95"], basis="same × order_events")
    except Exception as exc:
        metrics["follow_up_reply_rate"] = _not_measured("Follow-ups answered", needs=f"recovery_results unavailable: {exc}")
    try:
        oo = (await db.execute(_OPT_OUTS_SQL, {"since_iso": since.isoformat()})).mappings().first() or {}
        metrics["opt_outs"] = _measured(
            "Customers who asked not to be messaged (new in window / total)", int(oo.get("in_window") or 0),
            unit="people", n=int(oo.get("total") or 0),
            basis="persons.state.contact_preferences.opt_out", caveat="opt-outs with no person row live in redis only")
    except Exception as exc:
        metrics["opt_outs"] = _not_measured("Opt-outs", needs=f"persons.state query failed: {exc}")

    # reply accuracy today (the gate's tally) — today only by design of the store
    try:
        from app.agent.review import read_verdicts, verdict_view
        v = verdict_view(await read_verdicts(redis))
        passed, rewritten, soft, held = (int(v.get(k) or 0) for k in ("passed", "rewritten", "soft", "held"))
        total = passed + rewritten + soft + held
        fd = _prop(passed, total)
        metrics["first_draft_pass_today"] = _measured(
            "Replies that passed the gate on the first draft (today)", fd["p"], unit="proportion", n=total,
            ci95=fd["ci95"], basis="reviewer verdict tally (redis, UTC day)",
            caveat=f"held {held}; the tally keeps three days, so no window trend", status="partial")
    except Exception:
        metrics["first_draft_pass_today"] = _not_measured("First-draft pass rate", needs="redis verdict tally")
    metrics["pricing_quote_payment_accuracy"] = _not_measured(
        "Pricing, quotation, payment and order accuracy (live)",
        needs="a durable per-reply record of the gate's findings (today the tally is a redis counter kept three days); the case-set run gives the sandbox figure above")

    # latency, cost, availability
    metrics["turn_latency"] = _not_measured(
        "Agent turn latency", needs="store the turn's wall-clock time per reply (turn_facts → ai_usage or a messages.raw_meta field)")
    c, pc = cur["cost"], prev["cost"]
    metrics["model_cost"] = _measured(
        "Model spend in the window", round(c["usd"], 2), unit="USD", n=c["calls"],
        basis="ai_usage.cost_usd", previous=round(pc["usd"], 2),
        caveat=f"{c['contacts']} contacts; cost per contact {round(c['usd'] / c['contacts'], 3) if c['contacts'] else '—'} USD")
    try:
        from app.services.agent_health import read_turn_failures
        failures = await read_turn_failures(redis)
        metrics["availability_now"] = _measured(
            "Reply failures in the last hour", int((failures or {}).get("count") or 0), unit="failed turns",
            basis="agent_health (redis, rolling hour)", caveat="no history is kept: an availability trend needs a stored probe log")
    except Exception:
        metrics["availability_now"] = _not_measured("Availability", needs="agent_health redis read")
    metrics["availability_history"] = _not_measured(
        "Availability over time", needs="store each hourly selfcheck result (today only the latest findings are kept)")

    counts = {"measured": 0, "partial": 0, "not_measured": 0}
    for m in metrics.values():
        counts[m["status"]] = counts.get(m["status"], 0) + 1
    return {"window_days": days, "since": since.isoformat(), "until": now.isoformat(),
            "counts": counts, "metrics": metrics,
            "eval_history": history[-20:]}
