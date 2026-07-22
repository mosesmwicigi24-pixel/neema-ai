"""Per-person × per-channel message rollup the Bethany hub pulls.

Keyed by phone (from the phone identifier), aggregated across channels, sorted
by volume. People with no phone claim are skipped (the hub joins on phone).
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.routers.analytics import message_rollup


class _Res:
    def __init__(self, items): self._items = items
    def scalars(self): return SimpleNamespace(all=lambda: self._items)


class _FakeDB:
    """Serves the two selects in order: identifiers, then messages."""
    def __init__(self, idents, msgs):
        self._seq = [idents, msgs]
    async def execute(self, stmt):
        return _Res(self._seq.pop(0))


def _msg(person_id, channel, direction, when):
    return SimpleNamespace(person_id=person_id, channel=channel, direction=direction, created_at=when)


def test_rollup_groups_by_phone_and_channel_sorted_by_volume():
    now = datetime.now(timezone.utc)
    p1, p2, p_nophone = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    idents = [
        SimpleNamespace(person_id=p1, value="254712345678"),
        SimpleNamespace(person_id=p2, value="254799999999"),
        # p_nophone has no phone identifier
    ]
    msgs = [
        _msg(p1, "whatsapp", "inbound",  now - timedelta(days=3)),
        _msg(p1, "whatsapp", "outbound", now - timedelta(days=2)),
        _msg(p1, "whatsapp", "inbound",  now - timedelta(days=1)),
        _msg(p2, "messenger", "inbound", now - timedelta(days=1)),
        _msg(p_nophone, "whatsapp", "inbound", now),   # dropped — no phone claim
    ]

    out = asyncio.run(message_rollup(since_days=365, db=_FakeDB(idents, msgs), _=None))

    rows = out["rows"]
    # p_nophone dropped → two rows.
    assert len(rows) == 2
    # Sorted by volume: p1's whatsapp (3) first.
    top = rows[0]
    assert top["phone"] == "254712345678" and top["channel"] == "whatsapp"
    assert top["messages"] == 3 and top["inbound"] == 2
    assert top["first_at"] is not None and top["last_at"] is not None
    # p2 messenger row present.
    msgr = next(r for r in rows if r["channel"] == "messenger")
    assert msgr["phone"] == "254799999999" and msgr["messages"] == 1
    # No row lacks a phone.
    assert all(r["phone"] for r in rows)
