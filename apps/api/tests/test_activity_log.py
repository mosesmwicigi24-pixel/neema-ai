"""The Activity Log panel's journey ledger — person-scoped, newest first.

The endpoint aggregates what the system already records (pickups, planned
check-ins, deals + promises, orders, calls) instead of only intercepts, so a
conversation that was never escalated still shows its journey.
"""
import asyncio
import types
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.models.intercept import InterceptAction
from app.routers.admin import get_conversation_activity


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
    """Returns queued results in the order the endpoint issues its queries."""

    def __init__(self, results):
        self._results = list(results)

    async def execute(self, *a, **k):
        return _Res(self._results.pop(0))


def _ts(h):
    return datetime(2026, 8, 15, h, 0, tzinfo=timezone.utc)


def _world():
    conv_id = uuid.uuid4()
    person_id = uuid.uuid4()
    conv = types.SimpleNamespace(id=conv_id, person_id=person_id, wa_id="254700000001")
    icpt = types.SimpleNamespace(
        id=uuid.uuid4(), action=InterceptAction.escalated, agent_id=None,
        note="customer asked for a human", created_at=_ts(9))
    act = types.SimpleNamespace(
        id=uuid.uuid4(), status="planned", kind="customer_promise",
        reason="they said next Sunday", due_at=_ts(18),
        created_at=_ts(10), updated_at=_ts(10))
    deal = types.SimpleNamespace(
        id=uuid.uuid4(), title="4 altar cloths", stage="qualified", status="open",
        next_action={"kind": "customer_promise", "note": "they said: next sunday"},
        created_at=_ts(8), updated_at=_ts(11))
    order = types.SimpleNamespace(
        id="254700000001_1", items=[{"name": "Tray"}], subtotal=Decimal("2500"),
        currency="KES", status="open", payment_status="unpaid", created_at=_ts(12))
    call = types.SimpleNamespace(
        id=uuid.uuid4(), status="missed", answered_at=None, ended_at=None,
        started_at=_ts(13), agent_id=None)
    # Query order: conv → sibling ids → intercepts → actions → deals → orders → calls
    db = _SeqDB([conv, [(conv_id,)], [icpt], [act], [deal], [order], [call]])
    return conv_id, db


def test_activity_aggregates_every_journey_source():
    conv_id, db = _world()
    out = asyncio.run(get_conversation_activity(str(conv_id), db=db, agent=object()))
    kinds = {e["kind"] for e in out["events"]}
    assert {"escalated", "checkin_planned", "deal", "promise", "order", "call"} <= kinds


def test_activity_is_newest_first_and_labels_read_like_english():
    conv_id, db = _world()
    events = asyncio.run(
        get_conversation_activity(str(conv_id), db=db, agent=object()))["events"]
    ats = [e["at"] for e in events]
    assert ats == sorted(ats, reverse=True)
    by_kind = {e["kind"]: e for e in events}
    assert "KES 2,500" in by_kind["order"]["detail"]
    assert by_kind["promise"]["label"] == "Customer promised"
    assert by_kind["checkin_planned"]["label"].startswith("Check-in planned")
    assert "Escalated" in by_kind["escalated"]["label"]
    assert by_kind["call"]["label"] == "Call missed"


def test_activity_404s_on_a_missing_conversation():
    from fastapi import HTTPException
    db = _SeqDB([None])
    try:
        asyncio.run(get_conversation_activity(str(uuid.uuid4()), db=db, agent=object()))
        raise AssertionError("expected 404")
    except HTTPException as e:
        assert e.status_code == 404
