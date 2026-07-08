"""Re-engagement sweep selection logic (no DB, no network).

Verifies we only re-engage conversations where the customer is genuinely waiting
on us — the newest message is an inbound text — and skip our-own-last-reply and
text-less rows.
"""
import asyncio
from types import SimpleNamespace

from app.models.message import MsgDirection
from app.jobs import reengage


def _msg(direction, text):
    return SimpleNamespace(id="m", direction=direction, text=text)


def test_qualifies_only_for_inbound_text():
    assert reengage._qualifies(_msg(MsgDirection.inbound, "how much?")) is True
    assert reengage._qualifies(_msg(MsgDirection.outbound, "hi there")) is False  # we spoke last
    assert reengage._qualifies(_msg(MsgDirection.inbound, "   ")) is False         # blank
    assert reengage._qualifies(_msg(MsgDirection.inbound, None)) is False          # media/echo
    assert reengage._qualifies(None) is False


class _Res:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return SimpleNamespace(all=lambda: self._items)

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class _FakeDB:
    """Serves queued results in order: first the conversation list, then one
    latest-message lookup per conversation."""
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, stmt):
        return self._results.pop(0)


def test_find_waiting_filters_to_customers_waiting_on_us():
    convA = SimpleNamespace(id="A", channel="whatsapp", wa_id="254700", external_id="254700")
    convB = SimpleNamespace(id="B", channel="messenger", wa_id=None, external_id="PSID_B")
    convC = SimpleNamespace(id="C", channel="whatsapp", wa_id="254711", external_id="254711")
    db = _FakeDB([
        _Res([convA, convB, convC]),                       # the conversation query
        _Res([_msg(MsgDirection.inbound, "still available?")]),   # A: waiting → keep
        _Res([_msg(MsgDirection.outbound, "we replied")]),        # B: we spoke last → drop
        _Res([_msg(MsgDirection.inbound, "")]),                   # C: blank → drop
    ])
    waiting = asyncio.run(reengage.find_waiting(db))
    assert [c.id for c, _ in waiting] == ["A"]
    assert waiting[0][1].text == "still available?"
