"""Buying-rhythm + customer-tier helpers for the CRM panel (pure, no DB)."""
import types
from datetime import datetime, timezone, timedelta

from app.routers.crm import _buying_rhythm, _customer_tier, _cadence_label


def _order(days_ago: int):
    return types.SimpleNamespace(created_at=datetime.now(timezone.utc) - timedelta(days=days_ago))


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
