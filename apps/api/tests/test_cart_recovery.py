"""Abandoned-cart recovery — the guardrails, because this messages real customers.

Pins the rules that keep a helpful nudge from becoming spam: quiet hours, one
nudge per basket, and never nudging someone we actually owe a reply to.
"""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers models
import app.jobs.cart_recovery as cr
from app.models.conversation import ConvStatus, InterceptMode
from app.models.message import MsgDirection


# ── quiet hours (Nairobi = UTC+3) ────────────────────────────────────────────

def test_quiet_hours_allow_daytime_only():
    def at(utc_hour):
        return datetime(2026, 7, 27, utc_hour, 0, tzinfo=timezone.utc)
    assert cr.within_quiet_hours(at(6)) is True     # 09:00 Nairobi
    assert cr.within_quiet_hours(at(14)) is True    # 17:00
    assert cr.within_quiet_hours(at(2)) is False    # 05:00 — too early
    assert cr.within_quiet_hours(at(18)) is False   # 21:00 — too late
    assert cr.within_quiet_hours(at(23)) is False   # 02:00 — the middle of the night


# ── one nudge per basket ─────────────────────────────────────────────────────

def test_fingerprint_is_stable_per_basket_and_order_independent():
    a = [{"name": "Chasuble", "qty": 1}, {"name": "Mitre", "qty": 2}]
    b = [{"name": "Mitre", "qty": 2}, {"name": "Chasuble", "qty": 1}]   # reordered
    assert cr.cart_fingerprint(a) == cr.cart_fingerprint(b)
    # a genuinely changed basket is a different cart → nudgeable again
    c = [{"name": "Chasuble", "qty": 3}, {"name": "Mitre", "qty": 2}]
    assert cr.cart_fingerprint(a) != cr.cart_fingerprint(c)
    assert cr.cart_fingerprint([]) == cr.cart_fingerprint([])


def test_summary_names_what_they_picked():
    s = cr._summarise([{"name": "Red Chasuble", "qty": 1}, {"name": "Mitre", "qty": 2}])
    assert "Red Chasuble" in s and "Mitre ×2" in s
    assert "×1" not in s          # a single item reads naturally


# ── selection rules ──────────────────────────────────────────────────────────

class _DB:
    """Serves conversations, then a latest-message per conversation."""
    def __init__(self, convs, latest):
        self.convs, self.latest, self._first = convs, latest, True

    async def execute(self, *a, **k):
        if self._first:
            self._first = False
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(all=lambda: self.convs))
        # subsequent calls are the per-conversation latest-message lookups
        conv_id = self._pending
        return types.SimpleNamespace(
            scalar_one_or_none=lambda: self.latest.get(conv_id))


def _conv(cid, channel="whatsapp", wa_id="254700000001"):
    return types.SimpleNamespace(
        id=cid, channel=channel, wa_id=wa_id, external_id=wa_id,
        intercept_mode=InterceptMode.ai, status=ConvStatus.open,
        last_message_at=datetime.now(timezone.utc) - timedelta(hours=2))


def _msg(direction):
    return types.SimpleNamespace(direction=direction, text="hi")


def test_skips_when_the_customer_is_the_one_waiting(monkeypatch):
    """If their message is newest we OWE them a reply — that's the re-engage
    sweep's job. Nudging instead would look like we ignored them."""
    conv = _conv("c1")

    async def fake_get_cart(db, key, channel="whatsapp"):
        return {"items": [{"name": "Chasuble", "qty": 1}]}

    async def fake_latest(db, cid):
        return _msg(MsgDirection.inbound)          # customer spoke last

    monkeypatch.setattr("app.agent.cart.get_cart", fake_get_cart)
    monkeypatch.setattr("app.agent.cart.cart_total", lambda c: 15000)
    monkeypatch.setattr(cr, "_latest_message", fake_latest)

    db = types.SimpleNamespace(execute=lambda *a, **k: _scalars([conv]))
    rows = asyncio.run(cr.find_abandoned(db))
    assert rows == []


def test_picks_up_a_cart_we_are_not_owed_a_reply_on(monkeypatch):
    conv = _conv("c2")

    async def fake_get_cart(db, key, channel="whatsapp"):
        return {"items": [{"name": "Chasuble", "qty": 2}]}

    async def fake_latest(db, cid):
        return _msg(MsgDirection.outbound)         # we spoke last; they went quiet

    monkeypatch.setattr("app.agent.cart.get_cart", fake_get_cart)
    monkeypatch.setattr("app.agent.cart.cart_total", lambda c: 24000)
    monkeypatch.setattr(cr, "_latest_message", fake_latest)

    db = types.SimpleNamespace(execute=lambda *a, **k: _scalars([conv]))
    rows = asyncio.run(cr.find_abandoned(db))
    assert len(rows) == 1
    assert rows[0]["to"] == "254700000001"
    assert rows[0]["items"][0]["name"] == "Chasuble"


def test_empty_cart_is_never_a_candidate(monkeypatch):
    conv = _conv("c3")

    async def fake_get_cart(db, key, channel="whatsapp"):
        return {"items": []}                        # ordered → create_order cleared it

    monkeypatch.setattr("app.agent.cart.get_cart", fake_get_cart)
    monkeypatch.setattr("app.agent.cart.cart_total", lambda c: 0)
    db = types.SimpleNamespace(execute=lambda *a, **k: _scalars([conv]))
    assert asyncio.run(cr.find_abandoned(db)) == []


def _scalars(rows):
    async def _coro():
        return types.SimpleNamespace(
            scalars=lambda: types.SimpleNamespace(all=lambda: rows))
    return _coro()


def test_selection_only_targets_ai_mode_open_conversations():
    """The query itself must exclude human-handled / paused / closed threads."""
    import inspect
    src = inspect.getsource(cr.find_abandoned)
    assert "InterceptMode.ai" in src
    assert "ConvStatus.open" in src
    assert "WINDOW_HOURS" in src        # never outside the free-form window
