"""INSIGHTS FROM EVIDENCE (owner's directive, 2026-11-09, Phase 4; audit §5):
paid and unpaid orders kept apart, one set of score inputs shared by the panel
and the leads list, the commercial snapshot and ONE next best action — all
rules over recorded facts, no model."""
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers models
from app.routers.crm import _build_profile, _compute_lead_score, _lead_score_parts
from app.services import insights as ins

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def _order(total=5000, paid=False, days=3, hub_status=None, number=None, as_dict=False, **kw):
    base = dict(id=f"o-{number or days}", subtotal=total, currency="KES", status="pending",
                payment_status=("paid" if paid else "unpaid"), hub_payment_status=hub_status,
                hub_order_number=number, hub_order_id=(92 if number else None),
                hub_total=None, hub_public_url=None, hub_payment_url=None,
                items=[{"name": "Collar", "qty": 1, "total": total}],
                created_at=NOW - timedelta(days=days), person_id=None, wa_id="254700000001")
    base.update(kw)
    if as_dict:   # the hub's shape
        return {"id": base["id"], "order_number": number, "status": base["status"],
                "payment_status": base["payment_status"], "total": total, "subtotal": total,
                "currency_code": "KES", "created_at": base["created_at"].isoformat(),
                "items": base["items"], "source": "hub"}
    return types.SimpleNamespace(**base)


def _user(**kw):
    base = dict(id="u1", wa_id="254700000001", name="Moses", name_confirmed=True, email=None,
                phone=None, location=None, age=None, state={}, person_id=None,
                last_message_at=NOW - timedelta(days=1), created_at=NOW - timedelta(days=90),
                country="Kenya", country_iso="KE", flag_url=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _conv(days=1, channel="whatsapp"):
    return types.SimpleNamespace(id=f"c-{channel}", channel=channel, wa_id="254700000001",
                                 last_message_at=NOW - timedelta(days=days),
                                 created_at=NOW - timedelta(days=30), person_id=None)


# ── 1. paid vs unpaid ────────────────────────────────────────────────────────

def test_paid_reads_the_hubs_word_first_and_never_guesses():
    assert ins.is_paid(_order(paid=True))
    assert ins.is_paid(_order(paid=False, hub_status="completed"))        # the hub's word wins
    assert not ins.is_paid(_order(paid=True, hub_status="unpaid"))         # …both ways
    assert not ins.is_paid(_order(paid=False))
    assert not ins.is_paid({"payment_status": "partial"})
    assert not ins.is_paid({"payment_status": None}) and not ins.is_paid({})
    assert ins.is_paid({"payment_status": "Paid"})                          # the hub's dict shape


def test_spend_separates_paid_from_unpaid_and_names_the_open_order():
    orders = [_order(total=3000, paid=True, days=40), _order(total=7000, paid=False, days=2, number="BH-12"),
              _order(total=1000, paid=False, days=60)]              # too old to be "open"
    sp = ins.spend(orders, now=NOW)
    assert (sp["paid_orders"], sp["unpaid_orders"], sp["listed"]) == (1, 2, 3)
    assert (sp["paid_total"], sp["unpaid_total"]) == (3000.0, 8000.0)
    assert sp["open_order"]["number"] == "BH-12" and sp["open_order"]["age_days"] == 2
    assert sp["open_order"]["total"] == 7000.0 and sp["currencies"] == ["KES"]
    assert ins.spend([], now=NOW)["open_order"] is None
    assert ins.spend([_order(paid=False, days=45)], now=NOW)["open_order"] is None


def test_spend_reads_the_hubs_order_dicts_too():
    hub = [_order(total=20000, paid=True, days=15, number="H1", as_dict=True),
           _order(total=4000, paid=False, days=1, number="H2", as_dict=True)]
    sp = ins.spend(hub, now=NOW)
    assert sp["paid_total"] == 20000.0 and sp["unpaid_total"] == 4000.0
    assert sp["open_order"]["number"] == "H2"


# ── 2. the scorer: paid orders, an unpaid order as its own row ───────────────

def test_an_unpaid_order_no_longer_scores_like_a_paid_one():
    u = _user()
    paid = _compute_lead_score(u, order_count=1, total_spent=5000, channel_count=1)
    unpaid_only = _compute_lead_score(u, order_count=0, total_spent=0, channel_count=1, open_orders=1)
    assert paid > unpaid_only
    rows = {p["label"]: p for p in _lead_score_parts(u, 0, 0, 1, open_orders=1)}
    assert rows["Open order (unpaid)"]["pts"] == 10 and rows["Paid orders"]["pts"] == 0
    assert rows["Open order (unpaid)"]["max"] == 10


def test_score_inputs_use_paid_figures_and_the_open_order():
    u = _user()
    orders = [_order(total=12000, paid=True, days=20), _order(total=5000, paid=False, days=2)]
    # days_since_contact is read against the real clock: the threads are dated
    # from it, not from the fixed NOW (which made this fail from 12 Nov on).
    real = datetime.now(timezone.utc)
    c1, c2 = _conv(1), _conv(2, "messenger")
    c1.last_message_at, c2.last_message_at = real - timedelta(days=1), real - timedelta(days=2)
    inputs = ins.score_inputs(user=u, orders=orders, conversations=[c1, c2],
                              identities=[], person_state={"agent_cart": {"items": [{"name": "x"}]}},
                              now=NOW)
    assert inputs["order_count"] == 1 and inputs["total_spent"] == 12000.0
    assert inputs["open_orders"] == 1 and inputs["channel_count"] == 2
    assert inputs["cart_items"] == 1 and inputs["phone_verified"] is True
    assert 0 < inputs["days_since_contact"] < 3
    _compute_lead_score(u, **inputs)                     # the inputs fit the scorer exactly


def test_the_panel_and_the_list_share_the_inputs():
    import inspect
    from app.routers import crm
    assert "score_inputs(" in inspect.getsource(crm._build_profile)
    assert "score_inputs(" in inspect.getsource(crm.list_leads)
    assert "OrderEvent.person_id.in_" in inspect.getsource(crm.list_leads)   # person-wide, like the panel
    assert "Identity.person_id.in_" in inspect.getsource(crm.list_leads)     # identity-aware phone proof


# ── 3. the next best action, by precedence ───────────────────────────────────

def _nba(**kw):
    base = dict(commitment=None, customer_state=None, hold=None, open_order=None, cart_items=0,
                days_since_contact=1.0, interest=None, rhythm=None, paid_orders=0)
    base.update(kw)
    return ins.next_best_action(**base)


def test_an_opt_out_outranks_everything():
    a = _nba(opted_out=True, commitment={"item": "the cope", "overdue": True, "age_min": 600},
             open_order={"number": "1", "age_days": 1}, cart_items=3)
    assert a["kind"] == "none" and "stop" in a["action"]
    assert _nba(customer_state={"said": "stop"})["kind"] == "none"


def test_an_overdue_commitment_comes_first_then_the_payment_claim_then_the_hold():
    a = _nba(commitment={"item": "the cope", "overdue": True, "age_min": 600},
             customer_state={"said": "paid_claim"}, open_order={"number": "1", "age_days": 1})
    assert a["kind"] == "answer_check" and "the cope" in a["action"] and "10 h" in a["reason"]
    b = _nba(commitment={"item": "the cope", "overdue": False, "age_min": 3})
    assert b["kind"] == "answer_check" and "not yet overdue" in b["reason"]
    c = _nba(customer_state={"said": "paid_claim"}, open_order={"number": "1", "age_days": 1})
    assert c["kind"] == "verify_payment"
    d = _nba(customer_state={"said": "complaint"}, cart_items=2)
    assert d["kind"] == "resolve_complaint"
    e = _nba(hold={"said": "needs_time", "label": "Asked for time", "until": "2026-11-12T07:00:00+00:00"},
             open_order={"number": "1", "age_days": 1}, cart_items=2)
    assert e["kind"] == "wait" and "2026-11-12" in e["reason"]


def test_then_the_unpaid_order_the_live_cart_readiness_interest_and_rhythm():
    assert _nba(open_order={"number": "BH-1", "age_days": 2}, cart_items=2)["kind"] == "collect_payment"
    assert "#BH-1" in _nba(open_order={"number": "BH-1", "age_days": 2})["action"]
    assert _nba(cart_items=2, days_since_contact=1.0)["kind"] == "close"
    assert _nba(customer_state={"said": "ready"})["kind"] == "close"
    assert _nba(interest="Cassock", days_since_contact=3.0)["kind"] == "advance"
    assert _nba(cart_items=2, days_since_contact=20.0)["kind"] == "nudge"
    r = _nba(rhythm={"overdue": True, "cadence_label": "about every 2 months", "days_since_last": 120},
             paid_orders=3, days_since_contact=20.0)
    assert r["kind"] == "check_in" and "120 days" in r["reason"]
    assert _nba(rhythm={"overdue": True}, paid_orders=0, days_since_contact=20.0)["kind"] == "none"
    assert _nba(days_since_contact=None)["action"] == "Nothing due"
    assert _nba(days_since_contact=45.0)["reason"].startswith("No live signal")
    assert _nba(days_since_contact=10.0)["reason"] == "Recent contact, no open signal."


# ── 4. the snapshot ──────────────────────────────────────────────────────────

def _deal(**kw):
    base = dict(title="Cassock, Collar", items_snapshot=[{"name": "Cassock"}, {"name": "Collar"}],
                blocking=None, next_action=None, stage="qualified")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_snapshot_reads_the_state_the_hold_the_deal_and_the_money():
    ps = {"customer_state": {"said": "needs_time", "at": "2026-11-08T10:00:00+00:00", "source": "floor",
                             "waiting_on": "customer"},
          "agent_cart": {"items": [{"name": "Cassock"}]}}
    deal = _deal(next_action={"hold": {"said": "needs_time", "until": "2026-11-12T07:00:00+00:00"}},
                 blocking="Asked for time — until 12 Nov")
    snap = ins.snapshot(user=_user(), person_state=ps, deal=deal,
                        orders=[_order(total=3000, paid=True, days=30), _order(total=7000, days=2, number="BH-9")],
                        conversations=[_conv(1)], lead_stage="qualified", lead_stage_source="auto", now=NOW)
    assert snap["stage"] == "qualified" and snap["stage_source"] == "auto"
    assert snap["customer_state"]["label"] == "Asked for time" and snap["customer_state"]["at"].startswith("2026-11-08")
    assert snap["hold"]["until"].startswith("2026-11-12")
    assert snap["interest"] == "Cassock, Collar" and snap["deal_blocking"].startswith("Asked for time")
    assert snap["cart_items"] == 1
    assert (snap["paid_orders"], snap["paid_total"], snap["unpaid_orders"], snap["unpaid_total"]) == (1, 3000.0, 1, 7000.0)
    assert snap["open_order"]["number"] == "BH-9"
    assert snap["next_best_action"]["kind"] == "wait"        # the hold outranks the unpaid order
    assert snap["commitment"] is None


def test_snapshot_with_a_commitment_and_an_expired_hold():
    deal = _deal(next_action={"hold": {"said": "needs_time", "until": "2026-11-01T07:00:00+00:00"}})
    snap = ins.snapshot(user=_user(), person_state={}, deal=deal, orders=[], conversations=[_conv(1)],
                        commitment={"item": "the cope", "age_min": 1500, "overdue": True,
                                    "escalation": {"stage": "supervisor"}}, now=NOW)
    assert snap["hold"] is None                                # expired holds are not holds
    assert snap["commitment"] == {"item": "the cope", "age_min": 1500, "overdue": True, "escalation": "supervisor"}
    assert snap["next_best_action"]["kind"] == "answer_check"
    assert snap["customer_state"] is None


def test_snapshot_with_nothing_known():
    snap = ins.snapshot(user=_user(last_message_at=None), person_state=None, deal=None, orders=[],
                        conversations=[], now=NOW)
    assert snap["next_best_action"] == {"kind": "none", "action": "Nothing due",
                                        "reason": "No live signal; re-engage only on their move."}
    assert snap["interest"] is None and snap["open_order"] is None and snap["days_since_contact"] is None


# ── 5. the profile carries it all, from the same orders ──────────────────────

def test_the_profile_scores_paid_only_and_carries_the_snapshot():
    u = _user(state={"lead_stage": "contacted", "lead_stage_source": "auto"})
    local = [_order(total=15000, paid=True, days=20, number="A"),
             _order(total=6000, paid=False, days=1, number="B")]
    p = _build_profile(u, local, [_conv(1)], None, hub=None,
                       deal=_deal(), commitment=None)
    assert p["total_orders"] == 2 and p["total_spent"] == 21000.0          # as before: everything listed
    assert (p["paid_orders"], p["paid_spent"], p["unpaid_orders"], p["unpaid_spent"]) == (1, 15000.0, 1, 6000.0)
    assert p["open_order"]["number"] == "B"
    rows = {r["label"]: r["pts"] for r in p["lead_score_breakdown"]}
    assert rows["Paid orders"] == 10 and rows["Open order (unpaid)"] == 10 and rows["Spend level"] == 15
    assert p["snapshot"]["next_best_action"]["kind"] == "collect_payment"
    assert p["snapshot"]["interest"] == "Cassock, Collar"
    assert p["snapshot"]["stage"] == "contacted" and p["snapshot"]["stage_source"] == "auto"


def test_the_profile_with_the_hub_summary_splits_the_listed_orders():
    hub = {"total_orders": 24, "total_spent": 480000.0, "avg_order_value": 20000.0,
           "last_order_date": (NOW - timedelta(days=15)).isoformat(),
           "orders": [_order(total=20000, paid=True, days=15, number="H1", as_dict=True),
                      _order(total=20000, paid=False, days=3, number="H2", as_dict=True)]}
    p = _build_profile(_user(), [], [_conv(2)], None, hub=hub)
    assert p["total_orders"] == 24 and p["total_spent"] == 480000.0       # the hub's lifetime figures
    assert p["orders_listed"] == 2 and p["paid_orders"] == 1 and p["unpaid_orders"] == 1
    assert p["open_order"]["number"] == "H2"
    assert p["snapshot"]["next_best_action"]["kind"] == "collect_payment"


def test_an_old_caller_without_the_new_arguments_still_works():
    p = _build_profile(_user(), [], [], None, hub=None)
    assert p["snapshot"]["next_best_action"]["kind"] == "none" and p["paid_orders"] == 0
