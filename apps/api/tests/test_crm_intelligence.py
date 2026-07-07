"""Buying-rhythm + customer-tier helpers for the CRM panel (pure, no DB)."""
import types
from datetime import datetime, timezone, timedelta

from app.routers.crm import (
    _buying_rhythm, _customer_tier, _cadence_label, _parse_dt, _build_profile,
)


def _order(days_ago: int):
    """A bare order date (`_buying_rhythm` takes datetimes, not order rows)."""
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def test_buying_rhythm_avg_interval_and_recency():
    r = _buying_rhythm([_order(90), _order(60), _order(30)])  # ~30-day cadence
    assert 28 <= r["avg_interval_days"] <= 32
    assert 29 <= r["days_since_last"] <= 31
    assert r["overdue"] is False
    assert "months" in r["cadence_label"] or "weeks" in r["cadence_label"]


def test_buying_rhythm_overdue_past_usual_gap():
    # ~30-day cadence but last order was 140 days ago -> overdue (140 > 30*1.5).
    r = _buying_rhythm([_order(200), _order(170), _order(140)])
    assert r["overdue"] is True


def test_buying_rhythm_single_order_has_no_cadence():
    r = _buying_rhythm([_order(10)])
    assert r["avg_interval_days"] is None
    assert r["days_since_last"] == 10
    assert r["overdue"] is False


def test_buying_rhythm_no_orders():
    r = _buying_rhythm([])
    assert r["days_since_last"] is None and r["avg_interval_days"] is None


def test_customer_tier_segments():
    assert _customer_tier(0, 0, None)["tier"] == "prospect"
    assert _customer_tier(1, 5_000, 3)["tier"] == "new"
    assert _customer_tier(3, 50_000, 10)["tier"] == "regular"
    assert _customer_tier(8, 200_000, 20)["tier"] == "loyal"
    assert _customer_tier(25, 900_000, 5)["tier"] == "vip"        # by count
    assert _customer_tier(4, 600_000, 5)["tier"] == "vip"         # by spend
    assert _customer_tier(4, 100_000, 200)["tier"] == "at_risk"   # dormant good customer


def test_cadence_label_units():
    assert "day" in _cadence_label(5)
    assert "week" in _cadence_label(21)
    assert "month" in _cadence_label(60)


def test_parse_dt_handles_iso_and_naive():
    assert _parse_dt(None) is None
    assert _parse_dt("") is None
    assert _parse_dt("not-a-date") is None
    z = _parse_dt("2026-01-02T03:04:05Z")
    assert z.year == 2026 and z.tzinfo is not None
    naive = _parse_dt("2026-01-02 03:04:05")           # hub sends space-separated
    assert naive.tzinfo is not None                    # assumed UTC


# ── _build_profile sourcing: hub is truth, local is fallback ─────────────────

def _user():
    return types.SimpleNamespace(
        id="u1", wa_id="254700000001", name="Moses", name_confirmed=True,
        email="m@x.com", phone=None, location="Nairobi", age=35,
        state={"lead_stage": "qualified", "tags": ["Kenya"]},
        last_message_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc) - timedelta(days=200),
        country="Kenya", country_iso="KE", flag_url=None,
    )


def test_build_profile_prefers_hub_orders_and_spend():
    hub = {
        "total_orders": 24, "total_spent": 480_000.0, "avg_order_value": 20_000.0,
        "last_order_date": (datetime.now(timezone.utc) - timedelta(days=15)).isoformat(),
        "orders": [
            {"id": "9001", "status": "completed", "total": 20_000.0,
             "created_at": (datetime.now(timezone.utc) - timedelta(days=15)).isoformat(),
             "items": [{"name": "Cassock", "qty": 1, "total": 20_000.0}]},
            {"id": "9000", "status": "completed", "total": 20_000.0,
             "created_at": (datetime.now(timezone.utc) - timedelta(days=45)).isoformat(),
             "items": []},
        ],
    }
    # Local order_events would say only 1 order — hub must win.
    local = [types.SimpleNamespace(subtotal=5000, created_at=datetime.now(timezone.utc),
                                   hub_order_id=None)]
    p = _build_profile(_user(), local, [], None, hub=hub)

    assert p["total_orders"] == 24
    assert p["total_spent"] == 480_000.0
    assert p["avg_order_value"] == 20_000.0
    assert p["orders_source"] == "hub"
    assert [o["id"] for o in p["orders"]] == ["9001", "9000"]
    assert p["tier"] == "vip"                         # 24 orders -> VIP
    assert p["buying_rhythm"]["avg_interval_days"] is not None


def test_build_profile_falls_back_to_local_when_no_hub():
    local = [
        types.SimpleNamespace(id="l1", subtotal=3000, currency="KES", status="open",
                              payment_status="unpaid", hub_order_number=None, hub_order_id=None,
                              items=[{"name": "Collar"}],
                              created_at=datetime.now(timezone.utc) - timedelta(days=5)),
        types.SimpleNamespace(id="l2", subtotal=3000, currency="KES", status="open",
                              payment_status="unpaid", hub_order_number=None, hub_order_id=None,
                              items=[], created_at=datetime.now(timezone.utc) - timedelta(days=35)),
    ]
    p = _build_profile(_user(), local, [], None, hub=None)
    assert p["orders_source"] == "whatsapp"
    assert p["total_orders"] == 2
    assert p["total_spent"] == 6000.0
    assert {o["id"] for o in p["orders"]} == {"l1", "l2"}
