"""THE CUSTOMER TIMELINE (owner's directive, 2026-11-09, Phase 5; audit §6):
every ledger event carries a level (customer / technical), repeated technical
steps fold into one row, the endpoint filters by level, and the trail's new
state-change events (a discovery, a stage move, a promised check, a hold)
read as customer-level lines."""
import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401
from app.services import timeline as tl


def _ev(kind, label, minutes=0, detail=None, **kw):
    at = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc) - timedelta(minutes=minutes)
    return {"id": f"{kind}-{label}-{minutes}", "kind": kind, "label": label, "detail": detail,
            "at": at.isoformat(), **kw}


# ── 1. levels ────────────────────────────────────────────────────────────────

def test_customer_level_is_what_happened_to_the_customer():
    for kind, label in (("order", "Order pending"), ("call", "Missed call"), ("escalated", "Escalated"),
                        ("intercept", "Picked up by Ann"), ("deal", "Deal open"), ("promise", "Customer promised"),
                        ("checkin_sent", "Check-in sent"), ("geography", "Placed the customer"),
                        ("stage", "Stage moved to qualified"), ("commitment", "Promised check answered"),
                        ("customer_state", "Asked for time"), ("flag", "Flagged"), ("pause", "Paused")):
        assert tl.level_of({"kind": kind, "label": label}) == "customer", (kind, label)
    for label in ("Created an order", "Saved customer details", "Saved measurements",
                  "Handed the conversation to a human", "Asked the team to confirm availability",
                  "Placed the customer", "Order NOT placed"):
        assert tl.level_of({"kind": "tool", "label": label}) == "customer", label


def test_technical_level_is_how_neema_got_there():
    for label in ("Searched the catalogue", "Showed product card(s)", "Updated the cart",
                  "Shared the catalogue link", "Checked the church calendar", "Noted a durable fact",
                  "Recorded the lead source", "Agent step: whatever"):
        assert tl.level_of({"kind": "tool", "label": label}) == "technical", label
    for kind in ("checkin_planned", "checkin_vetoed", "checkin_needs_approval", "checkin_failed"):
        assert tl.level_of({"kind": kind, "label": "Check-in planned"}) == "technical"


# ── 2. folding ───────────────────────────────────────────────────────────────

def test_repeated_technical_steps_fold_into_one_row_with_a_count():
    events = [_ev("tool", "Searched the catalogue", 0, "“tray” → 2 result(s)"),
              _ev("tool", "Searched the catalogue", 1, "“chalice” → 3 result(s)"),
              _ev("tool", "Searched the catalogue", 2, "“tray” → 2 result(s)"),      # duplicate detail
              _ev("tool", "Searched the catalogue", 3, "“cope” → 1 result(s)"),
              _ev("tool", "Searched the catalogue", 4, "“stole” → 5 result(s)"),
              _ev("order", "Order pending", 5),
              _ev("tool", "Searched the catalogue", 6, "“mitre” → 1 result(s)")]
    out = tl.annotate(events)["events"]
    assert [e["label"] for e in out] == ["Searched the catalogue", "Order pending", "Searched the catalogue"]
    folded = out[0]
    assert folded["count"] == 5 and len(folded["members"]) == 5
    assert folded["details"] == ["“tray” → 2 result(s)", "“chalice” → 3 result(s)", "“cope” → 1 result(s)"]
    assert folded["detail"].endswith("· +2 more") and folded["first_at"] == events[4]["at"]
    assert out[2].get("count") is None                    # a lone step is not a group
    assert out[1]["level"] == "customer"


def test_folding_respects_the_window_and_never_touches_customer_rows():
    events = [_ev("tool", "Searched the catalogue", 0), _ev("tool", "Searched the catalogue", 30)]
    assert len(tl.annotate(events)["events"]) == 2        # 30 minutes apart: two rows
    orders = [_ev("order", "Order pending", 0), _ev("order", "Order pending", 1)]
    assert len(tl.annotate(orders)["events"]) == 2
    assert len(tl.annotate(events, fold=False)["events"]) == 2


def test_annotate_counts_levels_and_filters():
    events = [_ev("tool", "Searched the catalogue", 0), _ev("tool", "Searched the catalogue", 1),
              _ev("order", "Order pending", 2), _ev("checkin_planned", "Check-in planned", 3),
              _ev("geography", "Placed the customer", 4)]
    out = tl.annotate(events, level="customer")
    assert out["levels"] == {"customer": 2, "technical": 3}
    assert [e["kind"] for e in out["events"]] == ["order", "geography"]
    tech = tl.annotate(events, level="technical")["events"]
    assert [e["label"] for e in tech] == ["Searched the catalogue", "Check-in planned"]
    assert tech[0]["count"] == 2
    assert len(tl.annotate(events, level="all")["events"]) == 4
    assert tl.annotate([])["events"] == [] and tl.annotate([])["levels"] == {"customer": 0, "technical": 0}


# ── 3. the trail's labels for the new events ─────────────────────────────────

def test_the_trail_labels_the_state_change_events():
    from app.services.activity_trail import describe
    assert describe("stage", {}, {"summary": "Stage moved to qualified", "detail": "from new"}) == \
        ("Stage moved to qualified", "from new")
    assert describe("commitment", {}, {"summary": "Promised check answered", "detail": "'the cope' — answered by team after 42 min"})[0] == "Promised check answered"
    assert describe("customer_state", {}, {"summary": "Asked for time", "detail": "on hold until 2026-11-12"}) == \
        ("Asked for time", "on hold until 2026-11-12")
    assert describe("customer_state", {}, {})[0] == "customer_state changed"


# ── 4. the endpoint: levels, the kinds of the new rows, the filter ───────────

class _Res:
    def __init__(self, payload):
        self._p = payload
    def scalar_one_or_none(self):
        return self._p
    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._p)
    def all(self):
        return self._p


class _SeqDB:
    def __init__(self, results):
        self._results = list(results)
    async def execute(self, *a, **k):
        return _Res(self._results.pop(0))


def _ts(h, m=0):
    return datetime(2026, 11, 9, h, m, tzinfo=timezone.utc)


def _row(tool, summary, detail, h, m=0):
    return types.SimpleNamespace(id=uuid.uuid4(), tool=tool, summary=summary, detail=detail, created_at=_ts(h, m))


def _world():
    conv_id, person_id = uuid.uuid4(), uuid.uuid4()
    conv = types.SimpleNamespace(id=conv_id, person_id=person_id, wa_id="254700000001")
    steps = [_row("search_catalog", "Searched the catalogue", "“tray” → 2", 10, 5),
             _row("search_catalog", "Searched the catalogue", "“cope” → 1", 10, 4),
             _row("search_catalog", "Searched the catalogue", "“stole” → 3", 10, 3),
             _row("geography", "Placed the customer", "Placed in Kenya (what the customer said); was Bahrain", 10, 2),
             _row("stage", "Stage moved to qualified", "from contacted", 10, 1),
             _row("commitment", "Promised check answered", "'the cope' — answered by team after 42 min", 10, 0),
             _row("customer_state", "Asked for time", "on hold until 2026-11-12", 9, 59)]
    # conv → sibling ids → intercepts → actions → deals → orders → agent steps → calls
    db = _SeqDB([conv, [(conv_id,)], [], [], [], [], steps, []])
    return conv_id, db


def test_the_endpoint_levels_folds_and_keeps_the_new_kinds():
    from app.routers.admin import get_conversation_activity
    conv_id, db = _world()
    out = asyncio.run(get_conversation_activity(str(conv_id), db=db, agent=object()))
    assert out["levels"] == {"customer": 4, "technical": 3}
    kinds = [e["kind"] for e in out["events"]]
    assert kinds == ["tool", "geography", "stage", "commitment", "customer_state"]   # newest first; 3 searches folded
    assert out["events"][0]["count"] == 3 and out["events"][0]["level"] == "technical"
    assert all(e["level"] == "customer" for e in out["events"][1:])


def test_the_endpoint_filters_by_level():
    from app.routers.admin import get_conversation_activity
    conv_id, db = _world()
    out = asyncio.run(get_conversation_activity(str(conv_id), db=db, agent=object(), level="customer"))
    assert [e["kind"] for e in out["events"]] == ["geography", "stage", "commitment", "customer_state"]
    conv_id, db = _world()
    out = asyncio.run(get_conversation_activity(str(conv_id), db=db, agent=object(), level="technical", fold=False))
    assert [e["label"] for e in out["events"]] == ["Searched the catalogue"] * 3


# ── 5. the writers: a change writes one customer-level line ──────────────────

def test_the_stage_change_writes_a_timeline_line(monkeypatch):
    from app.services import lead_signals, timeline
    notes = []

    async def fake_note(db, **kw):
        notes.append(kw)
    monkeypatch.setattr(timeline, "note", fake_note)

    class _DB:
        def __init__(self, user):
            self._user = user
            self.commits = 0
        async def execute(self, stmt):
            # select(User) then select(OrderEvent) — both from the user
            payload = self._user if "users" in str(stmt) else []
            return types.SimpleNamespace(scalar_one_or_none=lambda: payload,
                                         scalars=lambda: types.SimpleNamespace(all=lambda: payload if isinstance(payload, list) else []))
        async def get(self, model, pk, **kw):
            return self._user
        async def commit(self):
            self.commits += 1

    from app.models.user import User
    user = User(wa_id="254700000001", name="Moses", email="m@x.ke", country="Kenya",
                location=None, person_id=None, last_message_at=datetime.now(timezone.utc),
                state={"lead_stage": "new"})
    user.id = uuid.uuid4()
    monkeypatch.setattr("app.services.lead_signals.lock_for_write", _lock)
    asyncio.run(lead_signals.refresh_lead_signals(_DB(user), "254700000001"))
    assert user.state["lead_stage"] == "qualified"
    assert notes and notes[0]["kind"] == "stage" and notes[0]["summary"] == "Stage moved to qualified"
    assert notes[0]["detail"].startswith("from new")
    # the same signals again: no new line
    notes.clear()
    asyncio.run(lead_signals.refresh_lead_signals(_DB(user), "254700000001"))
    assert notes == []


async def _lock(db, row):
    return row
