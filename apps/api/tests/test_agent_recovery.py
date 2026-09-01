"""Recovery must be as visible as failure.

2026-09-01: the account ran out of credit, every turn failed, /api/health said
`kind: credit, needs_a_human: true` — correctly. The owner topped it up. The
endpoint kept saying a human was needed for the best part of an hour, because
the only thing that ever cleared the state was a rolling-hour TTL. A dashboard
that cries for help after the help arrived teaches people to ignore it.

A completed turn now clears it — but only for the failures a person was told
to go and fix. `rate` and `other` are intermittent: some turns fail while
others succeed, and clearing on the next success would hide the partial outage
the count exists to show.
"""
import asyncio
import json

import pytest

from app.services import agent_health as ah


class _Redis:
    def __init__(self, store=None):
        self.store = dict(store or {})
    async def get(self, k):
        return self.store.get(k)
    async def set(self, k, v, **kw):
        self.store[k] = v
        return True
    async def delete(self, k):
        self.store.pop(k, None)
    async def incr(self, k):
        self.store[k] = int(self.store.get(k, 0)) + 1
        return self.store[k]
    async def expire(self, k, ttl):
        return True


def _failing(kind: str, count: int = 3) -> _Redis:
    return _Redis({"agent:fail:count": count,
                   "agent:fail:last": json.dumps({"kind": kind, "error": "…"})})


@pytest.mark.parametrize("kind", list(ah.ACTIONABLE))
def test_a_completed_turn_clears_what_a_human_was_told_to_fix(kind):
    r = _failing(kind)
    assert asyncio.run(ah.record_turn_success(r)) is True
    assert asyncio.run(ah.read_turn_failures(r)) == {}


@pytest.mark.parametrize("kind", ["rate", "other"])
def test_an_intermittent_failure_survives_the_next_success(kind):
    # Half the turns failing is exactly what the count is for. One success is
    # not proof the blip is over.
    r = _failing(kind)
    assert asyncio.run(ah.record_turn_success(r)) is False
    assert asyncio.run(ah.read_turn_failures(r))["count"] == 3


def test_success_on_a_healthy_agent_is_a_no_op():
    r = _Redis()
    assert asyncio.run(ah.record_turn_success(r)) is False
    assert asyncio.run(ah.read_turn_failures(r)) == {}


def test_it_never_raises_on_a_broken_redis():
    class _Boom:
        async def get(self, k):
            raise RuntimeError("redis down")
    assert asyncio.run(ah.record_turn_success(_Boom())) is False
    assert asyncio.run(ah.record_turn_success(None)) is False


def test_the_full_round_trip_of_an_outage(monkeypatch):
    """Fail, fail, fail → a human is called. Fix it, one turn lands → quiet."""
    r = _Redis()
    for _ in range(3):
        asyncio.run(ah.record_turn_failure(r, "254700000000",
                                           Exception("credit balance is too low")))
    state = asyncio.run(ah.read_turn_failures(r))
    assert state["count"] == 3 and state["kind"] == "credit"

    asyncio.run(ah.record_turn_success(r))
    assert asyncio.run(ah.read_turn_failures(r)) == {}

    # …and a fresh failure afterwards starts a clean count, not a resumed one.
    asyncio.run(ah.record_turn_failure(r, "254700000000",
                                       Exception("credit balance is too low")))
    assert asyncio.run(ah.read_turn_failures(r))["count"] == 1


def test_every_path_that_records_a_failure_also_records_the_recovery():
    # The pairing is the whole point: a surface that can raise the alarm but
    # never lower it is how the dashboard lied for an hour.
    import inspect
    from app.agent import runtime
    from app.services import conversation
    for fn in (runtime._run_and_send, runtime._run_and_send_meta):
        src = inspect.getsource(fn)
        assert "record_turn_failure" in src and "record_turn_success" in src
    src = inspect.getsource(conversation)
    assert src.count("record_turn_failure") >= 1 and src.count("record_turn_success") >= 1
