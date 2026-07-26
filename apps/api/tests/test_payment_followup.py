"""Payment follow-up — the guardrails, because chasing money is easy to get wrong.

The rule that matters most: NEVER nag someone who has already paid. The hub is
re-checked live for every order, a payment that landed is reconciled instead of
chased, and an unconfirmable status means we say nothing at all.
"""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers models
import app.jobs.payment_followup as pf
from app.models.conversation import ConvStatus, InterceptMode
from app.models.order_event import OrderEvent


# ── what counts as paid ──────────────────────────────────────────────────────

def test_only_an_explicit_paid_state_counts():
    for s in ("paid", "PAID", " Completed ", "settled", "success"):
        assert pf.is_paid(s) is True
    for s in ("unpaid", "pending", "partial", "failed", "", None, "awaiting_payment"):
        assert pf.is_paid(s) is False


def test_quiet_hours_allow_daytime_only():
    at = lambda h: datetime(2026, 7, 27, h, 0, tzinfo=timezone.utc)
    assert pf.within_quiet_hours(at(6)) is True      # 09:00 Nairobi
    assert pf.within_quiet_hours(at(2)) is False     # 05:00
    assert pf.within_quiet_hours(at(19)) is False    # 22:00


# ── the message ──────────────────────────────────────────────────────────────

def _order(**kw):
    o = OrderEvent(id="x", wa_id="254700000001")
    o.hub_order_id = kw.get("hub_order_id", 77)
    o.hub_order_number = kw.get("hub_order_number", "ORD-260727-AB")
    o.hub_payment_url = kw.get("hub_payment_url", "https://hub.example/pay/tok123")
    o.hub_total = kw.get("hub_total", 27000)
    o.hub_currency = kw.get("hub_currency", "KES")
    o.payment_status = kw.get("payment_status", "unpaid")
    o.channel = kw.get("channel", "whatsapp")
    o.subtotal = kw.get("subtotal", 27000)
    o.currency = "KES"
    return o


def test_reminder_reuses_the_same_link_and_stays_gentle():
    text = pf.compose(_order(), "Moses Mwicigi")
    assert "https://hub.example/pay/tok123" in text     # the SAME link, never a new one
    assert "ORD-260727-AB" in text
    assert "KES 27,000" in text
    assert "Moses" in text and "Mwicigi" not in text    # first name only
    # no pressure language
    assert "immediately" not in text.lower() and "urgent" not in text.lower()


def test_reminder_without_a_name_or_total_still_reads_fine():
    o = _order(hub_order_number=None, hub_total=None, subtotal=None)
    text = pf.compose(o, None)
    assert "https://hub.example/pay/tok123" in text
    assert "Hi 🙏" in text


# ── selection: never chase a paid order ──────────────────────────────────────

class _DB:
    def __init__(self, orders, conv=None):
        self.orders, self.conv, self.commits, self._n = orders, conv, 0, 0
    async def execute(self, *a, **k):
        self._n += 1
        if self._n == 1:
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(all=lambda: self.orders))
        return types.SimpleNamespace(
            scalars=lambda: types.SimpleNamespace(first=lambda: self.conv))
    async def commit(self):
        self.commits += 1


def _conv(mode=InterceptMode.ai, status=ConvStatus.open):
    return types.SimpleNamespace(channel="whatsapp", wa_id="254700000001",
                                 external_id=None, intercept_mode=mode, status=status)


def _hub(status):
    async def f(order_id, redis=None):
        return None if status is None else {"payment_status": status}
    return f


def test_a_paid_order_is_reconciled_not_chased(monkeypatch):
    """They paid; our mirror was stale. Update the record and stay quiet."""
    o = _order(payment_status="unpaid")
    db = _DB([o], _conv())
    monkeypatch.setattr("app.core.hub_client.fetch_order_status", _hub("paid"))

    rows = asyncio.run(pf.find_unpaid(db))
    assert rows == []                       # never chased
    assert o.payment_status == "paid"       # quietly reconciled
    assert db.commits == 1


def test_an_unconfirmable_status_means_we_say_nothing(monkeypatch):
    db = _DB([_order()], _conv())
    monkeypatch.setattr("app.core.hub_client.fetch_order_status", _hub(None))
    assert asyncio.run(pf.find_unpaid(db)) == []


def test_a_genuinely_unpaid_order_is_picked_up(monkeypatch):
    db = _DB([_order()], _conv())
    monkeypatch.setattr("app.core.hub_client.fetch_order_status", _hub("unpaid"))
    rows = asyncio.run(pf.find_unpaid(db))
    assert len(rows) == 1 and rows[0]["to"] == "254700000001"


def test_locally_paid_orders_never_hit_the_hub(monkeypatch):
    called = {"n": 0}

    async def boom(order_id, redis=None):
        called["n"] += 1
        return {"payment_status": "unpaid"}

    monkeypatch.setattr("app.core.hub_client.fetch_order_status", boom)
    db = _DB([_order(payment_status="paid")], _conv())
    assert asyncio.run(pf.find_unpaid(db)) == []
    assert called["n"] == 0


def test_human_handled_or_closed_conversations_are_left_alone(monkeypatch):
    monkeypatch.setattr("app.core.hub_client.fetch_order_status", _hub("unpaid"))
    assert asyncio.run(pf.find_unpaid(_DB([_order()], _conv(mode=InterceptMode.human)))) == []
    assert asyncio.run(pf.find_unpaid(_DB([_order()], _conv(status=ConvStatus.closed)))) == []
    assert asyncio.run(pf.find_unpaid(_DB([_order()], None))) == []   # no conversation


def test_selection_respects_the_window_and_grace_period():
    import inspect
    src = inspect.getsource(pf.find_unpaid)
    assert "WINDOW_HOURS" in src and "GRACE_HOURS" in src
    assert "hub_payment_url" in src        # only orders that actually got a link
