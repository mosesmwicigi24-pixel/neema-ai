"""Cycle 9 — hostile audit of calls & audio (no database needed).

Each test is one attack scenario from the audit's evidence table:

  · cost abuse: a decode that hangs under load must not be remembered as a
    "corrupt" file for 30 days, a timed-out provider request (which OpenAI
    may still bill) must stay counted against the daily ceiling, and a caller
    that forgets to pass redis must not bypass the ceiling;
  · the ceiling under real concurrency (real redis when one is installed).
"""
import asyncio
import os
import shutil
import socket
import subprocess
import time

import pytest

import app.main  # noqa: F401 — registers models
from app.core.config import settings
from app.services import transcribe as stt
from tests import test_transcribe_engine as eng

on, audio = eng.on, eng.audio            # the engine battery's fixtures
FakeRedis, Provider = eng.FakeRedis, eng.Provider


def run(coro):
    return asyncio.run(coro)


# ── 1. cost abuse ────────────────────────────────────────────────────────────

def test_a_decode_that_times_out_is_not_cached_as_corrupt(on, audio):
    """100 notes in a minute → 100 ffmpeg processes → some decodes exceed
    their timeout. That is load, not a broken file: it must not be cached as
    `corrupt` for 30 days (a re-sent or forwarded copy would be refused
    unheard), and the team must not be told the audio is undecodable."""
    real = stt.normalise
    calls = {"n": 0}

    async def slow(src, dst, max_seconds):
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.TimeoutError()
        return await real(src, dst, max_seconds)
    on.setattr(stt, "normalise", slow)
    on.setattr(stt, "call_provider", Provider(("Nataka kasoki", None)))
    r = FakeRedis()
    first = run(stt.transcribe_file(audio["voice2"], redis=r))
    assert first.status != "failed:corrupt"
    assert first.reason == "decode_timeout"
    assert stt.describe(first.status) == stt.REASON_WORDS["decode_timeout"]
    assert not any(k.startswith("transcribe:result:") for k in r.kv)
    second = run(stt.transcribe_file(audio["voice2"], redis=r))
    assert second.ok and second.text == "Nataka kasoki"


def test_a_timed_out_provider_request_stays_counted(on, audio):
    """A request cut off by our timeout keeps running in its thread and
    reaches OpenAI, which bills it. Refunding it let the counter fall below
    what was really spent — repeated, the $3 ceiling could be passed."""
    on.setattr(settings, "transcribe_timeout_seconds", 0.2)
    on.setattr(settings, "transcribe_retries", 0)
    p = Provider(("late", None), delay=1.5)
    on.setattr(stt, "call_provider", p)
    r = FakeRedis()
    out = run(stt.transcribe_file(audio["voice2"], redis=r))
    time.sleep(1.6)                               # the cut-off thread finishes its (billed) request
    assert out.status == "failed:provider_timeout" and len(p.calls) == 1
    assert run(stt.spent_today(r)) > 0            # the request is counted, not refunded


def test_a_refusal_is_still_refunded(on, audio):
    class E(Exception):
        status_code = 400
    on.setattr(stt, "call_provider", Provider(E("bad audio")))
    r = FakeRedis()
    out = run(stt.transcribe_file(audio["voice2"], redis=r))
    assert out.status == "failed:provider_rejected"
    assert run(stt.spent_today(r)) == pytest.approx(0.0, abs=1e-9)


def test_a_caller_without_redis_still_meets_the_ceiling(on, audio):
    """runtime._hear_voice_note's fallback calls transcribe_audio_url(url)
    with no redis: before the fix that ran with NO ceiling, no cache, no lock."""
    from app.services import ai_budget
    sink = FakeRedis()
    sink.kv[stt._spend_key()] = 3.0               # today's ceiling already used
    on.setattr(ai_budget, "_sink", sink)
    p = Provider(("x", None))
    on.setattr(stt, "call_provider", p)
    out = run(stt.transcribe_file(audio["voice2"]))          # redis omitted
    assert out.status == "failed:over_budget" and p.calls == []


def test_non_audio_with_an_audio_name_is_refused_unsent(on, tmp_path):
    p = Provider(("x", None))
    on.setattr(stt, "call_provider", p)
    for name, data in (("page.ogg", b"<html><script>alert(1)</script></html>" * 50),
                       ("zip.ogg", b"PK\x03\x04" + os.urandom(8192))):
        f = tmp_path / name
        f.write_bytes(data)
        out = run(stt.transcribe_file(str(f), redis=FakeRedis()))
        assert out.status == "failed:corrupt"
    assert p.calls == []


# ── 2. the ceiling under real concurrency (real redis, when installed) ───────

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.skipif(shutil.which("redis-server") is None, reason="needs a local redis-server")
def test_the_ceiling_holds_under_real_redis_concurrency(tmp_path, monkeypatch):
    import redis.asyncio as aioredis
    port = _free_port()
    proc = subprocess.Popen(["redis-server", "--port", str(port), "--bind", "127.0.0.1",
                             "--save", "", "--appendonly", "no", "--dir", str(tmp_path)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
                break
            except OSError:
                time.sleep(0.1)
        monkeypatch.setattr(settings, "transcribe_daily_cap_usd", 3.0)

        async def race():
            conns = [aioredis.from_url(f"redis://127.0.0.1:{port}/0") for _ in range(8)]
            got = await asyncio.gather(*(stt._reserve(conns[i % 8], 0.07) for i in range(400)))
            spent = await stt.spent_today(conns[0])
            for c in conns:
                await c.aclose()
            return sum(got), spent
        granted, spent = run(race())
        assert granted == int(3.0 / 0.07)          # 42 — never one more
        assert spent <= 3.0 + 1e-6
    finally:
        proc.terminate()
        proc.wait(timeout=5)
