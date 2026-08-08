"""Sell from THEIR history: the companion set and the scheduled next need.

The owner's brief, verbatim in spirit: a parish bought divai, wafers and cups
together in May. Today they order wafers only — Neema should notice the
companions from their own past basket and ask, in at most two lines, how the
divai and cups are holding up. Not finished yet? Ask when they'll be needed
and BOOK the check-in — a named time is a promise the system keeps.

The chain: past baskets become visible in memory (they were number+total
only), the prompt teaches the companion ask + the schedule move, a
schedule_check_in tool books it on the initiative scheduler, and the utility
template carries the check-in when it comes due weeks later.
"""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.core.config import settings


# ── past baskets are visible, not just totals ────────────────────────────────

def test_order_history_shows_the_basket(monkeypatch):
    from app.agent import memory

    row = types.SimpleNamespace(
        hub_order_number="BH-2401", hub_total=3500, hub_currency="KES",
        subtotal=3500, currency="KES", id="x",
        created_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        items=[{"name": "Communion Wafer Bread 500PCS", "qty": 2},
               {"name": "Divai Communion Wine", "qty": 1},
               {"name": "Communion Cups 50pk", "qty": 4}])

    class _DB:
        async def execute(self, *a, **k):
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(all=lambda: [row]))

    out = asyncio.run(memory._recent_orders_summary(_DB(), "254712345678"))
    line = out[0]
    assert "BH-2401 (12 May 2026) — KES 3500" in line
    assert "Communion Wafer Bread 500PCS ×2" in line
    assert "Divai Communion Wine" in line and "Communion Cups 50pk ×4" in line


# ── the prompt teaches the move ──────────────────────────────────────────────

def test_prompt_carries_companion_set_and_scheduling():
    from app.agent.prompt import build_system_prompt
    flat = " ".join(build_system_prompt(country_iso="KE", currency="KES").split())
    assert "THE COMPANION SET" in flat
    assert "wafers + divai/wine + cups" in flat
    assert "at most TWO lines" in flat
    assert "COUNTS as your one suggestion" in flat        # no double upsells
    assert "SCHEDULE THE NEXT NEED" in flat
    assert "`schedule_check_in`" in flat
    assert "A named time is a promise the system keeps" in flat


# ── the tool books it ────────────────────────────────────────────────────────

class _ConvDB:
    def __init__(self, conv):
        self._conv = conv
        self.added, self.committed = [], False
    async def execute(self, *a, **k):
        c = self._conv
        return types.SimpleNamespace(scalar_one_or_none=lambda: c)
    def add(self, obj): self.added.append(obj)
    async def commit(self): self.committed = True


def _ctx(db, **kw):
    from app.agent.tools import ToolContext
    return ToolContext(db=db, redis=None, wa_id="254712345678", **kw)


def test_schedule_check_in_books_a_replenishment_action():
    from app.agent import tools
    conv = types.SimpleNamespace(id="c1")
    db = _ConvDB(conv)
    out = asyncio.run(tools._schedule_check_in(
        {"days_from_now": 14,
         "reason": "divai and cups expected to run out; offer next delivery"},
        _ctx(db)))
    assert out["ok"] and db.committed
    action = db.added[0]
    assert action.kind == "replenishment"
    days = (action.due_at - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 12.5 < days < 14.5
    assert "divai and cups" in action.reason


def test_schedule_check_in_clamps_and_validates():
    from app.agent import tools
    conv = types.SimpleNamespace(id="c1")
    out = asyncio.run(tools._schedule_check_in(
        {"days_from_now": 900, "reason": "x"}, _ctx(_ConvDB(conv))))
    assert out["ok"]                                       # clamped to 90, not rejected
    out2 = asyncio.run(tools._schedule_check_in(
        {"days_from_now": 7}, _ctx(_ConvDB(conv))))
    assert "error" in out2                                 # reason required
    # Draft/preview mode books nothing.
    db = _ConvDB(conv)
    out3 = asyncio.run(tools._schedule_check_in(
        {"days_from_now": 7, "reason": "x"}, _ctx(db, read_only=True)))
    assert out3.get("preview") and db.added == []


def test_check_in_tool_is_registered_everywhere():
    from app.agent.tools import TOOLS, _HANDLERS
    from app.agent.runtime import _META_TOOL_NAMES
    assert any(t["name"] == "schedule_check_in" for t in TOOLS)
    assert "schedule_check_in" in _HANDLERS
    assert "schedule_check_in" in _META_TOOL_NAMES


# ── the scribe also catches spoken timelines ─────────────────────────────────

def test_customer_replenishment_timelines_are_detected():
    from app.services.deals import detect_customer_promise
    out = detect_customer_promise("We'll need them in two weeks")
    assert out is not None
    due, hint = out
    days = (due - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 13 < days < 15 and "two weeks" in hint
    out2 = detect_customer_promise("I'll order next month")
    assert out2 is not None
    days2 = (out2[0] - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 28 < days2 < 31
    # A bare pleasantry with no timeline still books nothing.
    assert detect_customer_promise("thanks, we'll talk") is None


# ── weeks later, the check-in rides the utility template ─────────────────────

def test_replenishment_check_in_rides_the_template(monkeypatch):
    from app.services import actions
    monkeypatch.setattr(settings, "wa_event_template", "order_update__category")
    monkeypatch.setattr(settings, "wa_event_lang", "en")
    tpl = {}

    async def _fake_tpl(wa_id, template, lang, params):
        tpl["params"] = params
        return {"messages": [{"id": "wamid.R"}]}
    async def _fake_save(db, redis, wa_id, text, **k): pass
    monkeypatch.setattr("app.services.n8n_bridge.send_wa_template", _fake_tpl)
    monkeypatch.setattr("app.services.n8n_bridge.save_outbound_message", _fake_save)

    class _DB:
        async def commit(self): pass

    conv = types.SimpleNamespace(wa_id="254712345678", contact_name="Pastor Moses")
    action = types.SimpleNamespace(kind="replenishment", status="planned", draft=None,
                                   reason="Customer-agreed check-in (whatsapp): divai and cups")
    ok = asyncio.run(actions._send_followup_template(_DB(), None, conv, action))
    assert ok and action.status == "sent"
    assert tpl["params"][1] == "your supplies"             # no order number → honest fallback
    assert "check-in you asked for" in tpl["params"][2]


# ── address the parcel, don't re-ask the name (Francis, 2026-08-08) ──────────
# His name was on his Messenger profile, yet the delivery ask was "your name,
# phone and address" — twice. Known names are CONFIRMED at order time, never
# re-collected: "Shall we address the parcel to your name — Francis Xavier
# Pereira?"

def test_known_names_are_confirmed_not_reasked():
    from app.agent.prompt import build_system_prompt
    flat = " ".join(build_system_prompt(country_iso="KE", currency="KES").split())
    assert "ADDRESS THE PARCEL, DON'T RE-ASK THE NAME" in flat
    assert "Shall we address the parcel to your name" in flat
    assert "capture that name as the delivery recipient" in flat


def test_meta_order_stage_asks_phone_and_address_only():
    from app.agent.runtime import _meta_addendum
    a = " ".join(_meta_addendum("USD").split())
    assert "delivery details are the phone and address ONLY" in a
    assert "never 'your name' when you already have it" in a
    assert "Shall we address the parcel to your name" in a
