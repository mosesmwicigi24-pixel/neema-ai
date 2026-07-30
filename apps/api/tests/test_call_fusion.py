"""Phase F — voice and text are one memory: call summaries join chat context."""
import asyncio
import types
from datetime import datetime

from app.agent.runtime import _recent_call_context


class _Res:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []
    def scalar_one_or_none(self): return self._one
    def scalars(self): return types.SimpleNamespace(all=lambda: self._many)


class _DB:
    """First execute → Identity lookup; second → calls query."""
    def __init__(self, ident=None, calls=None):
        self._q = [_Res(one=ident), _Res(many=calls or [])]
    async def execute(self, *a, **k):
        return self._q.pop(0)


def _call(summary, day):
    return types.SimpleNamespace(summary=summary,
                                 started_at=datetime(2026, 7, day, 10, 0))


def test_call_summaries_join_the_context_capped():
    calls = [_call("Bishop wants 12 choir robes, purple, needs quote by Friday. " + "x" * 300, 28),
             _call("Discussed communion trays; he prefers gold with lid.", 25),
             _call("", 24)]                       # empty summary → skipped
    out = asyncio.run(_recent_call_context(_DB(calls=calls), "254700000001", "whatsapp"))
    assert "RECENT PHONE CALLS" in out
    assert "never re-ask what was already settled" in out
    assert "28 Jul" in out and "choir robes" in out
    assert "gold with lid" in out
    # per-call cap ~220 chars
    first_line = [l for l in out.split("\n") if "choir robes" in l][0]
    assert len(first_line) < 260


def test_no_calls_means_no_block():
    assert asyncio.run(_recent_call_context(_DB(calls=[]), "254700000001", "whatsapp")) == ""


def test_meta_channel_resolves_via_identity():
    ident = types.SimpleNamespace(person_id="p1")
    calls = [_call("Asked about cassock sizes on the phone.", 27)]
    out = asyncio.run(_recent_call_context(_DB(ident=ident, calls=calls),
                                           "PSID123", "messenger"))
    assert "cassock sizes" in out
    # no identity + not whatsapp → nothing to match on, no query crash
    out2 = asyncio.run(_recent_call_context(_DB(ident=None, calls=[]),
                                            "PSID123", "messenger"))
    assert out2 == ""
