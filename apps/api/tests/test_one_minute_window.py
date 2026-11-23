"""ONE MINUTE, ONE ANSWER (owner, 2026-11-20): "Make Neema wait for one minute
and combine any message that comes in one minute and give one response."

The minute restarts with each new message; the whole wait is capped from the
first message of the burst, so a steady typer is still answered."""
import asyncio
import time

from app.core.config import Settings, settings
from app.services.wa_native import reply_wait


class _Redis:
    def __init__(self):
        self.kv = {}

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def get(self, k):
        return self.kv.get(k)

    async def delete(self, k):
        self.kv.pop(k, None)


def test_the_window_is_one_minute_on_every_private_channel():
    assert Settings.model_fields["whatsapp_debounce_seconds"].default == 60
    assert Settings.model_fields["meta_debounce_seconds"].default == 60
    assert Settings.model_fields["reply_window_max_seconds"].default == 120


def test_the_first_message_waits_the_full_minute(monkeypatch):
    monkeypatch.setattr(settings, "reply_window_max_seconds", 120, raising=False)
    r = _Redis()
    assert asyncio.run(reply_wait(r, "k", 60)) == 60.0
    assert "k" in r.kv                                    # the burst's start is remembered


def test_a_later_message_restarts_the_minute_until_the_cap(monkeypatch):
    monkeypatch.setattr(settings, "reply_window_max_seconds", 120, raising=False)
    r = _Redis()
    r.kv["k"] = str(time.time() - 30)                     # the burst began 30 s ago
    assert asyncio.run(reply_wait(r, "k", 60)) == 60.0    # 90 s in total: under the cap
    r.kv["k"] = str(time.time() - 90)                     # began 90 s ago
    w = asyncio.run(reply_wait(r, "k", 60))
    assert 29.0 <= w <= 30.5                              # answered at 120 s, not 150 s
    r.kv["k"] = str(time.time() - 500)                    # long past the cap
    assert asyncio.run(reply_wait(r, "k", 60)) == 1.0     # answer now


def test_no_redis_or_no_cap_is_the_plain_window(monkeypatch):
    assert asyncio.run(reply_wait(None, "k", 60)) == 60.0
    monkeypatch.setattr(settings, "reply_window_max_seconds", 0, raising=False)
    assert asyncio.run(reply_wait(_Redis(), "k", 60)) == 60.0


def test_both_channels_use_it_and_clear_the_start_when_answered():
    import inspect
    from app.agent import runtime
    from app.services import wa_native
    wa = inspect.getsource(wa_native._reply_after_debounce)
    meta = inspect.getsource(runtime._run_meta_after_burst)
    for src in (wa, meta):
        assert "reply_wait(" in src and "redis.delete(_first)" in src
