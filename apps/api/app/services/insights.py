"""THE COMMERCIAL READ OF A CUSTOMER — from evidence, deterministically.

Owner's directive (2026-11-09, Phase 4): the Insights tab should say where
this customer commercially stands, from what the system already knows — the
deal, the customer-state floor, the orders WITH their payment status, the hub
summary, slice 12's commitments — and name ONE next best action with its
reason. No model call: every line here is a rule over recorded facts.

What this module fixes from the audit (`CUSTOMER_INTELLIGENCE_AUDIT.md` §5):

  · paid and unpaid orders were scored and summed identically — `spend()`
    separates them (the hub's paid states, the same predicate the payment
    reminder and the performance view use);
  · the panel and the leads list computed the score from different inputs —
    `score_inputs()` is the one builder both call;
  · "qualified" came from a name plus a dialling prefix — the stage now needs
    the customer's own details (`lead_signals.derive_lead_stage`).

Nothing is stored: the snapshot is recomputed on every read, like the score.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.jobs.payment_followup import PAID_STATES

OPEN_ORDER_DAYS = 30          # an unpaid order older than this is history, not a lead signal
WARM_DAYS = 7                 # a conversation this fresh is live

# Plain words for the customer-state floor's readings (services/customer_state).
STATE_LABELS = {
    "exploring": "Exploring", "quoting": "Asked for prices", "comparing": "Comparing prices",
    "consulting": "Consulting someone", "needs_time": "Asked for time", "ready": "Ready to buy",
    "paid_claim": "Says they have paid", "complaint": "Has a complaint", "closing": "Closing",
    "stop": "Asked us to stop", "none": None,
}


def _get(o, key, default=None):
    if isinstance(o, dict):
        return o.get(key, default)
    return getattr(o, key, default)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_paid(order) -> bool:
    """The hub's word first (`hub_payment_status`), else the local
    `payment_status`; only an explicit paid-like state counts, so unpaid,
    partial and unknown never read as paid."""
    status = _get(order, "hub_payment_status") or _get(order, "payment_status")
    return (str(status or "").strip().lower()) in PAID_STATES


def order_view(o) -> dict:
    """One shape for a hub order dict and a local OrderEvent row."""
    total = _get(o, "total")
    if total is None:
        total = _get(o, "hub_total")
    if total is None:
        total = _get(o, "subtotal")
    return {
        "id": str(_get(o, "id") or ""),
        "number": _get(o, "order_number") or _get(o, "hub_order_number"),
        "total": _f(total),
        "currency": _get(o, "currency_code") or _get(o, "hub_currency") or _get(o, "currency"),
        "created_at": _dt(_get(o, "created_at")),
        "paid": is_paid(o),
        "payment_status": (_get(o, "hub_payment_status") or _get(o, "payment_status")),
        "link": _get(o, "hub_public_url") or _get(o, "hub_payment_url"),
    }


def spend(orders, *, now: datetime | None = None) -> dict:
    """Paid and unpaid, kept apart. `open_order` is the newest unpaid order
    within OPEN_ORDER_DAYS — the one a follow-up would be about. Totals are
    summed as stored (the currencies are listed; nothing is converted)."""
    now = now or datetime.now(timezone.utc)
    views = [order_view(o) for o in (orders or [])]
    paid = [v for v in views if v["paid"]]
    unpaid = [v for v in views if not v["paid"]]
    recent_unpaid = [v for v in unpaid if v["created_at"] and
                     v["created_at"] >= now - timedelta(days=OPEN_ORDER_DAYS)]
    recent_unpaid.sort(key=lambda v: v["created_at"], reverse=True)
    open_order = None
    if recent_unpaid:
        v = recent_unpaid[0]
        open_order = {"id": v["id"], "number": v["number"], "total": v["total"],
                      "currency": v["currency"], "payment_status": v["payment_status"],
                      "created_at": v["created_at"].isoformat() if v["created_at"] else None,
                      "age_days": (now - v["created_at"]).days if v["created_at"] else None,
                      "link": v["link"]}
    return {
        "listed": len(views),
        "paid_orders": len(paid),
        "unpaid_orders": len(unpaid),
        "paid_total": round(sum(v["total"] for v in paid), 2),
        "unpaid_total": round(sum(v["total"] for v in unpaid), 2),
        "currencies": sorted({v["currency"] for v in views if v["currency"]}),
        "open_order": open_order,
        "last_paid_at": max((v["created_at"] for v in paid if v["created_at"]), default=None),
    }


def score_inputs(*, user, orders, conversations, identities=None, person_state=None,
                 now: datetime | None = None) -> dict:
    """The ONE set of inputs the lead score is computed from — the panel and
    the leads list both call this, so the same customer ranks the same in
    both. Paid orders and paid spend only; an unpaid order within the window
    is its own, separate signal."""
    from app.routers.crm import _cart_size, _days_since, _phone_verified, _profile_of
    now = now or datetime.now(timezone.utc)
    sp = spend(orders, now=now)
    channels = {(_get(c, "channel") or "whatsapp") for c in (conversations or [])}
    last_contact = max((_get(c, "last_message_at") for c in (conversations or [])
                        if _get(c, "last_message_at")), default=None)
    user_state = _get(user, "state") or {}
    return {
        "order_count": sp["paid_orders"],
        "total_spent": sp["paid_total"],
        "channel_count": len(channels),
        "phone_verified": _phone_verified(user, identities),
        "cart_items": _cart_size(person_state, user_state),
        "days_since_contact": _days_since(last_contact),
        "role": _profile_of(person_state, user_state).get("role"),
        "open_orders": 1 if sp["open_order"] else 0,
    }


def _hold(person_state: dict | None, deal, now: datetime) -> dict | None:
    """An open hold — from the deal's next_action (the floor writes it there)."""
    nxt = _get(deal, "next_action") if deal is not None else None
    hold = nxt.get("hold") if isinstance(nxt, dict) else None
    if not isinstance(hold, dict):
        return None
    until = _dt(hold.get("until"))
    if until and until <= now:
        return None
    return {"said": hold.get("said"), "label": STATE_LABELS.get(hold.get("said")),
            "until": until.isoformat() if until else None}


def next_best_action(*, commitment, customer_state, hold, open_order, cart_items,
                     days_since_contact, interest, rhythm, paid_orders, opted_out=False) -> dict:
    """ONE action, by precedence, each with its reason. Deterministic."""
    said = (customer_state or {}).get("said")
    if opted_out or said == "stop":
        return {"kind": "none", "action": "Nothing — they asked us to stop",
                "reason": "An opt-out is final; only their own message reopens the thread."}
    if commitment and commitment.get("overdue"):
        return {"kind": "answer_check",
                "action": f"Answer the promised check on {commitment.get('item')}",
                "reason": f"Promised {commitment.get('age_min', 0) // 60} h ago and still unanswered; "
                          "the customer is waiting on us."}
    if commitment:
        return {"kind": "answer_check",
                "action": f"Confirm {commitment.get('item')} with the workshop",
                "reason": "A check is open and not yet overdue."}
    if said == "paid_claim":
        return {"kind": "verify_payment", "action": "Verify the payment in the hub",
                "reason": "They say they have paid; only the hub's record confirms it."}
    if said == "complaint":
        return {"kind": "resolve_complaint", "action": "Resolve the complaint first",
                "reason": "Nothing sells over an open complaint."}
    if hold:
        return {"kind": "wait", "action": f"Wait — {hold.get('label') or 'they asked for time'}",
                "reason": (f"No outreach until {hold['until'][:10]}; the scheduled check-in returns."
                           if hold.get("until") else "No outreach; they will come back.")}
    if open_order:
        num = f" #{open_order['number']}" if open_order.get("number") else ""
        return {"kind": "collect_payment", "action": f"Follow up the unpaid order{num}",
                "reason": f"Placed {open_order.get('age_days', 0)} day(s) ago, not yet paid."}
    warm = days_since_contact is not None and days_since_contact <= WARM_DAYS
    if cart_items and warm:
        return {"kind": "close", "action": "Close: offer the order for the cart",
                "reason": f"{cart_items} item(s) in the cart and the conversation is live."}
    if said == "ready":
        return {"kind": "close", "action": "Close: place the order",
                "reason": "They said they are ready."}
    if interest and warm:
        return {"kind": "advance", "action": f"Advance the conversation on {interest}",
                "reason": "Interest named this week; no order yet."}
    if cart_items:
        return {"kind": "nudge", "action": "A gentle nudge on the cart",
                "reason": f"{cart_items} item(s) left in the cart; the conversation has cooled."}
    if rhythm and rhythm.get("overdue") and paid_orders:
        return {"kind": "check_in", "action": "Check in — their usual buying gap has passed",
                "reason": f"Buys {rhythm.get('cadence_label')}; {rhythm.get('days_since_last')} days since the last order."}
    if days_since_contact is None or days_since_contact > 30:
        return {"kind": "none", "action": "Nothing due",
                "reason": "No live signal; re-engage only on their move."}
    return {"kind": "none", "action": "Nothing due", "reason": "Recent contact, no open signal."}


def snapshot(*, user, person_state, deal, orders, conversations, commitment=None,
             rhythm=None, lead_stage=None, lead_stage_source=None, opted_out=False,
             now: datetime | None = None) -> dict:
    """The commercial snapshot the Insights tab shows: stage (and who set
    it), what they said last and when, an open hold, the open commitment, the
    open unpaid order, the interest on the deal, the cart, paid vs unpaid, and
    the one next best action. Everything from recorded facts."""
    from app.routers.crm import _cart_size, _days_since
    now = now or datetime.now(timezone.utc)
    ps = person_state or {}
    sp = spend(orders, now=now)
    cs = ps.get("customer_state") if isinstance(ps.get("customer_state"), dict) else None
    customer_state = None
    if cs and cs.get("said") and cs.get("said") != "none":
        customer_state = {"said": cs.get("said"), "label": STATE_LABELS.get(cs.get("said")),
                          "at": cs.get("at"), "source": cs.get("source"),
                          "waiting_on": cs.get("waiting_on")}
    hold = _hold(ps, deal, now)
    items = list(_get(deal, "items_snapshot") or []) if deal is not None else []
    interest = (_get(deal, "title") or ", ".join(
        str(i.get("name") or "") for i in items if isinstance(i, dict) and i.get("name"))) or None
    last_contact = max((_get(c, "last_message_at") for c in (conversations or [])
                        if _get(c, "last_message_at")), default=None)
    days = _days_since(last_contact)
    cart_items = _cart_size(ps, _get(user, "state") or {})
    action = next_best_action(commitment=commitment, customer_state=customer_state, hold=hold,
                              open_order=sp["open_order"], cart_items=cart_items,
                              days_since_contact=days, interest=interest, rhythm=rhythm,
                              paid_orders=sp["paid_orders"], opted_out=opted_out)
    return {
        "stage": lead_stage, "stage_source": lead_stage_source,
        "customer_state": customer_state,
        "hold": hold,
        "commitment": ({"item": commitment.get("item"), "age_min": commitment.get("age_min"),
                        "overdue": commitment.get("overdue"),
                        "escalation": (commitment.get("escalation") or {}).get("stage")}
                       if commitment else None),
        "open_order": sp["open_order"],
        "interest": (interest[:200] if interest else None),
        "deal_blocking": (_get(deal, "blocking") if deal is not None else None),
        "cart_items": cart_items,
        "paid_orders": sp["paid_orders"], "paid_total": sp["paid_total"],
        "unpaid_orders": sp["unpaid_orders"], "unpaid_total": sp["unpaid_total"],
        "currencies": sp["currencies"], "orders_listed": sp["listed"],
        "days_since_contact": (round(days, 1) if days is not None else None),
        "next_best_action": action,
    }
