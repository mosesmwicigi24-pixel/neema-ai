"""ONE TURN AT A TIME PER CONVERSATION (audit, 2026-11-05): a second burst
waits for the running turn instead of starting a concurrent one, the
missed-reply sweeper leaves an in-flight thread alone, and a colleague who
took the chat while the turn composed is not talked over."""
import asyncio
import inspect

import app.main  # noqa: F401 — registers models
from app.agent import runtime as rt


class _Redis:
    def __init__(self):
        self.kv = {}

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        return True

    async def delete(self, k):
        self.kv.pop(k, None)

    async def exists(self, k):
        return 1 if k in self.kv else 0


def test_the_second_turn_waits_for_the_first(monkeypatch):
    r = _Redis()
    monkeypatch.setattr(rt, "INFLIGHT_WAIT_S", 6)
    waits = []

    async def _sleep(s):
        waits.append(s)
        if len(waits) == 2:                      # the first turn finishes meanwhile
            await rt._release_inflight(r, "whatsapp", "k")
    monkeypatch.setattr(rt.asyncio, "sleep", _sleep)
    assert asyncio.run(rt._acquire_inflight(r, "whatsapp", "k")) is True
    assert asyncio.run(rt.in_flight(r, "whatsapp", "k")) is True
    assert asyncio.run(rt._acquire_inflight(r, "whatsapp", "k")) is True
    assert waits == [2, 2]
    asyncio.run(rt._release_inflight(r, "whatsapp", "k"))
    assert asyncio.run(rt.in_flight(r, "whatsapp", "k")) is False
    # no redis: nothing to wait on
    assert asyncio.run(rt._acquire_inflight(None, "whatsapp", "k")) is True


def test_a_wait_that_runs_out_still_answers(monkeypatch):
    r = _Redis()
    monkeypatch.setattr(rt, "INFLIGHT_WAIT_S", 4)

    async def _sleep(s):
        pass
    monkeypatch.setattr(rt.asyncio, "sleep", _sleep)
    asyncio.run(rt._acquire_inflight(r, "whatsapp", "k"))
    assert asyncio.run(rt._acquire_inflight(r, "whatsapp", "k")) is True   # fail-open after the wait


def test_the_senders_hold_the_slot_and_re_read_the_mode_before_sending():
    for fn in (rt._run_and_send, rt._run_and_send_meta):
        src = inspect.getsource(fn)
        assert "_acquire_inflight(" in src and "_release_inflight(" in src and "finally:" in src
        assert src.index("_still_ai(") < src.index("send_to_channel(" if "meta" in fn.__name__ else "_send_waba(")


def test_the_sweeper_skips_a_thread_whose_turn_is_composing():
    from app.services import reply_sweeper
    src = inspect.getsource(reply_sweeper.sweep_missed_replies)
    assert "in_flight(redis, channel, ext)" in src
    assert src.index("in_flight(redis, channel, ext)") < src.index("_run_and_send(")
