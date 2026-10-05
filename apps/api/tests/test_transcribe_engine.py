"""Cycle 4 — the transcription engine (services/transcribe.py).

Real audio, real ffmpeg, a mocked provider (no network, no keys). Each test is
one scenario from the cycle's battery: languages, silence, music, very long,
corrupt, provider timeout / 5xx / refusal / bad key, over budget, duplicate
deliveries, and the production root cause itself (the extensionless voice
note). Latency is measured on the real code path with a provider that takes a
fixed time, so the engine's own overhead is visible.
"""
import asyncio
import os
import shutil
import subprocess
import time

import pytest

import app.main  # noqa: F401 — registers models
from app.core.config import settings
from app.services import transcribe as stt

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


# ── fakes ────────────────────────────────────────────────────────────────────

class FakeRedis:
    """The subset of redis.asyncio the engine and the AI meter use."""

    def __init__(self):
        self.kv: dict = {}
        self.h: dict = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def delete(self, *ks):
        for k in ks:
            self.kv.pop(k, None)

    async def expire(self, k, s):
        return True

    async def incrbyfloat(self, k, v):
        self.kv[k] = float(self.kv.get(k) or 0) + float(v)
        return self.kv[k]

    async def hincrbyfloat(self, k, f, v):
        d = self.h.setdefault(k, {})
        d[f] = float(d.get(f) or 0) + float(v)

    async def hincrby(self, k, f, v):
        d = self.h.setdefault(k, {})
        d[f] = int(d.get(f) or 0) + int(v)

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))


class Provider:
    """A scripted provider: each call pops the next answer (text, lang) or
    raises it when it is an exception. Records every call."""

    def __init__(self, *answers, delay=0.0):
        self.answers = list(answers)
        self.calls: list[str] = []
        self.delay = delay

    def __call__(self, path, prov, model):
        self.calls.append(path)
        if self.delay:
            time.sleep(self.delay)
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, BaseException):
            raise a
        return a


class HTTPErr(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "whisper_enabled", True)
    monkeypatch.setattr(settings, "whisper_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-not-real")
    monkeypatch.setattr(settings, "transcribe_model", "gpt-4o-transcribe")
    monkeypatch.setattr(settings, "transcribe_daily_cap_usd", 3.0)
    monkeypatch.setattr(settings, "transcribe_retries", 2)
    monkeypatch.setattr(stt, "BACKOFF", (0.0, 0.0, 0.0))
    return monkeypatch


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def audio(tmp_path_factory):
    d = tmp_path_factory.mktemp("audio")
    f = {}
    # A WhatsApp voice note exactly as production stored it: ogg/opus, NO extension.
    f["voice"] = str(d / "wa_1234567890")
    _ff("-f", "lavfi", "-i", "sine=frequency=330:duration=4", "-af", "volume=0.5",
        "-c:a", "libopus", "-f", "ogg", f["voice"])
    f["voice2"] = str(d / "wa_other")
    _ff("-f", "lavfi", "-i", "sine=frequency=550:duration=3", "-c:a", "libopus", "-f", "ogg", f["voice2"])
    f["silence"] = str(d / "silence.ogg")
    _ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "5", "-c:a", "libopus", f["silence"])
    f["messenger"] = str(d / "clip.mp4")             # Messenger audio: mp4/aac
    _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "aac", f["messenger"])
    f["long_voice"] = str(d / "long.ogg")            # 11 minutes > the 10-minute voice limit
    _ff("-f", "lavfi", "-i", "sine=frequency=300:duration=660", "-c:a", "libopus", "-b:a", "8k", f["long_voice"])
    f["long_call"] = str(d / "call.webm")            # 21 minutes: three 10-minute pieces
    _ff("-f", "lavfi", "-i", "sine=frequency=300:duration=1260", "-c:a", "libopus", "-b:a", "8k", f["long_call"])
    f["corrupt"] = str(d / "corrupt.ogg")
    with open(f["corrupt"], "wb") as fh:
        fh.write(os.urandom(4096))
    f["empty"] = str(d / "empty.ogg")
    open(f["empty"], "wb").close()
    return f


def run(coro):
    return asyncio.run(coro)


# ── the production root cause ────────────────────────────────────────────────

def test_whatsapp_voice_notes_are_saved_with_an_extension(monkeypatch):
    """The bug: guess_extension('audio/ogg') is None on the slim image, so every
    note was saved as `wa_<id>` — and OpenAI refuses a nameless format."""
    import mimetypes
    from app.services import wa_native as wn
    monkeypatch.setattr(mimetypes, "guess_extension", lambda *_a, **_k: None)
    assert wn.media_ext("audio/ogg; codecs=opus") == ".ogg"
    assert wn.media_ext("audio/mpeg") == ".mp3"
    assert wn.media_ext("audio/mp4") == ".m4a"
    assert wn.media_ext("audio/amr") == ".amr"
    assert wn.media_ext("image/jpeg") == ".jpg"
    assert wn.media_ext("application/x-unknown") == ""
    assert wn.media_ext(None) == ""


def test_an_extensionless_ogg_note_still_transcribes(on, audio):
    """Even a file already on disk without an extension (the 87 notes) is
    decoded by content and sent as a named .mp3."""
    p = Provider(("Habari, nataka kasoki nyeusi size 52", None))
    on.setattr(stt, "call_provider", p)
    r = run(stt.transcribe_file(audio["voice"], redis=FakeRedis()))
    assert r.status == "done" and r.ok
    assert r.text == "Habari, nataka kasoki nyeusi size 52"
    assert r.lang == "sw"
    assert len(p.calls) == 1 and p.calls[0].endswith(".mp3")
    assert 3.5 < r.duration_s < 4.6
    assert r.cost_usd == pytest.approx(r.duration_s / 60 * 0.006, rel=1e-3)


# ── languages ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said,lang,expect", [
    ("Hello, how much is the black cassock in size 52?", None, "en"),
    ("Bonjour, combien coûte la chasuble verte s'il vous plaît", None, "fr"),
    ("Niaje boss, nataka ile cassock black, bei gani?", None, "sw"),       # Sheng, code-mixed
    ("Je, mna vikombe vya komunio? Nataka sinia moja.", None, "sw"),
    ("Habari", "swahili", "sw"),                                           # whisper-1 names it
    ("Olá, quanto custa?", "portuguese", "pt"),
])
def test_language_is_stored_as_iso(on, audio, said, lang, expect):
    on.setattr(stt, "call_provider", Provider((said, stt.lang_code(lang))))
    r = run(stt.transcribe_file(audio["voice2"], redis=None))
    assert r.ok and r.text == said and r.lang == expect


def test_whisper1_asks_for_the_language_and_4o_gets_the_vocabulary(on, audio, monkeypatch):
    """The OpenAI request shape: whisper-1 → verbose_json (language comes back),
    gpt-4o-transcribe → json; both carry the trade vocabulary as the prompt."""
    import sys
    import types
    seen = []

    class _T:
        def create(self, **kw):
            seen.append(kw)
            lang = "swahili" if kw["response_format"] == "verbose_json" else None
            return types.SimpleNamespace(text=" Nataka alb ", language=lang)

    class _OpenAI:
        def __init__(self, **kw):
            seen.append({"client": kw})
            self.audio = types.SimpleNamespace(transcriptions=_T())
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_OpenAI))
    path = audio["voice2"]
    assert stt._openai_transcribe(path, "whisper-1") == ("Nataka alb", "sw")
    assert stt._openai_transcribe(path, "gpt-4o-transcribe") == ("Nataka alb", None)
    reqs = [s for s in seen if "model" in s]
    assert reqs[0]["response_format"] == "verbose_json" and reqs[1]["response_format"] == "json"
    assert all("cassock" in r["prompt"].lower() for r in reqs)
    clients = [s["client"] for s in seen if "client" in s]
    assert all(c["max_retries"] == 0 and c["timeout"] == float(settings.transcribe_timeout_seconds)
               for c in clients)
    # the hint is bilingual (OpenAI: a prompt "should match the audio language")
    assert "kasoki" in reqs[0]["prompt"] and "komunio" in reqs[0]["prompt"]
    # gpt-transcribe: keywords + the languages we expect, no free-text prompt
    seen.clear()
    stt._openai_transcribe(path, "gpt-transcribe")
    r = [s for s in seen if "model" in s][0]
    assert r["languages"] == ["en", "sw", "fr"] and "cassock" in r["keywords"] and "prompt" not in r
    # TRANSCRIBE_VOCABULARY="" sends no prompt at all
    monkeypatch.setattr(settings, "transcribe_vocabulary", "")
    seen.clear()
    stt._openai_transcribe(path, "gpt-4o-transcribe")
    assert "prompt" not in [s for s in seen if "model" in s][0]


# ── silence, music, artefacts ────────────────────────────────────────────────

def test_silence_never_reaches_the_provider_or_the_budget(on, audio):
    p = Provider(("Thank you.", None))
    on.setattr(stt, "call_provider", p)
    r = FakeRedis()
    out = run(stt.transcribe_file(audio["silence"], redis=r))
    assert out.status == "silent" and not out.ok and p.calls == []
    assert run(stt.spent_today(r)) == 0.0


@pytest.mark.parametrize("artefact", ["♪♪♪", "[Music]", "Thanks for watching!",
                                      "Subtitles by the Amara.org community", "  ...  "])
def test_music_and_whisper_artefacts_count_as_no_speech(on, audio, artefact):
    on.setattr(stt, "call_provider", Provider((artefact, None)))
    out = run(stt.transcribe_file(audio["voice2"], redis=None))
    assert out.status == "silent" and out.text == ""


def test_a_real_thank_you_is_kept(on, audio):
    on.setattr(stt, "call_provider", Provider(("Thank you", None)))
    out = run(stt.transcribe_file(audio["voice2"], redis=None))
    assert out.ok and out.text == "Thank you"


# ── limits ───────────────────────────────────────────────────────────────────

def test_a_voice_note_over_ten_minutes_is_refused_unsent(on, audio):
    p = Provider(("x", None))
    on.setattr(stt, "call_provider", p)
    r = FakeRedis()
    out = run(stt.transcribe_file(audio["long_voice"], kind="voice_note", redis=r))
    assert out.status == "failed:too_long" and p.calls == []
    assert run(stt.spent_today(r)) == 0.0
    assert "longer than the limit" in stt.describe(out.status)


def test_a_long_call_goes_in_ten_minute_pieces_in_order(on, audio):
    p = Provider(("Agent: karibu Bethany House.", None), ("Customer: nataka cassock tatu.", None),
                 ("Agent: asante, tutakutumia bei.", None))
    on.setattr(stt, "call_provider", p)
    r = FakeRedis()
    out = run(stt.transcribe_file(audio["long_call"], kind="call", redis=r))
    assert out.ok and len(p.calls) == 3
    assert out.text == ("Agent: karibu Bethany House. Customer: nataka cassock tatu. "
                        "Agent: asante, tutakutumia bei.")
    assert 1255 < out.duration_s < 1265
    assert run(stt.spent_today(r)) == pytest.approx(out.duration_s / 60 * 0.006, rel=1e-3)


def test_too_large_is_refused_before_any_work(on, audio):
    on.setattr(settings, "transcribe_max_bytes", 100)
    p = Provider(("x", None))
    on.setattr(stt, "call_provider", p)
    assert run(stt.transcribe_file(audio["voice2"])).status == "failed:too_large"
    assert p.calls == []


@pytest.mark.parametrize("key", ["corrupt", "empty"])
def test_a_corrupt_or_empty_file_is_named_not_sent(on, audio, key):
    p = Provider(("x", None))
    on.setattr(stt, "call_provider", p)
    out = run(stt.transcribe_file(audio[key], redis=FakeRedis()))
    assert out.status == "failed:corrupt" and p.calls == []


def test_a_missing_file(on):
    assert run(stt.transcribe_file("/nope/wa_1")).status == "failed:no_file"
    assert run(stt.transcribe_file(None)).status == "failed:no_file"


# ── provider failures: retried when they heal, named when they don't ─────────

def test_a_timeout_is_retried_then_succeeds(on, audio):
    p = Provider(APITimeoutError("read timed out"), ("Nataka stole", None))
    on.setattr(stt, "call_provider", p)
    out = run(stt.transcribe_file(audio["voice2"], redis=FakeRedis()))
    assert out.ok and len(p.calls) == 2


def test_every_attempt_timing_out_fails_and_refunds_the_budget(on, audio):
    p = Provider(asyncio.TimeoutError())
    on.setattr(stt, "call_provider", p)
    r = FakeRedis()
    out = run(stt.transcribe_file(audio["voice2"], redis=r))
    assert out.status == "failed:provider_timeout" and len(p.calls) == 3
    assert run(stt.spent_today(r)) == pytest.approx(0.0, abs=1e-9)
    # a transient failure is NOT cached — the next try really tries
    p2 = Provider(("Nataka stole", None))
    on.setattr(stt, "call_provider", p2)
    assert run(stt.transcribe_file(audio["voice2"], redis=r)).ok and len(p2.calls) == 1


@pytest.mark.parametrize("exc,reason,tries", [
    (HTTPErr(500), "provider_error", 3),
    (HTTPErr(503), "provider_error", 3),
    (HTTPErr(429), "provider_busy", 3),
    (APIConnectionError("dns"), "provider_unreachable", 3),
    (HTTPErr(400), "provider_rejected", 1),      # never retried: it will refuse again
    (HTTPErr(401), "provider_auth", 1),          # a bad key is named, not hammered
])
def test_provider_failures(on, audio, exc, reason, tries):
    p = Provider(exc)
    on.setattr(stt, "call_provider", p)
    out = run(stt.transcribe_file(audio["voice2"], redis=FakeRedis()))
    assert out.status == f"failed:{reason}" and len(p.calls) == tries
    assert stt.describe(out.status) == stt.REASON_WORDS[reason]


def test_a_500_then_success(on, audio):
    p = Provider(HTTPErr(502), ("Nataka mitre", None))
    on.setattr(stt, "call_provider", p)
    assert run(stt.transcribe_file(audio["voice2"])).ok and len(p.calls) == 2


def test_a_hung_provider_is_cut_off_by_the_timeout(on, audio):
    on.setattr(settings, "transcribe_timeout_seconds", 0.2)
    on.setattr(settings, "transcribe_retries", 0)
    on.setattr(stt, "call_provider", Provider(("late", None), delay=3.0))
    t = time.perf_counter()
    out = run(stt.transcribe_file(audio["voice2"]))
    assert out.status == "failed:provider_timeout"
    assert time.perf_counter() - t < 3.6          # cut off at 1.25 s; the thread drains by 3 s


# ── the daily ceiling ────────────────────────────────────────────────────────

def test_over_budget_is_refused_before_the_provider(on, audio):
    on.setattr(settings, "transcribe_daily_cap_usd", 0.0001)
    p = Provider(("x", None))
    on.setattr(stt, "call_provider", p)
    r = FakeRedis()
    out = run(stt.transcribe_file(audio["voice2"], redis=r))
    assert out.status == "failed:over_budget" and p.calls == []
    assert run(stt.spent_today(r)) == pytest.approx(0.0, abs=1e-9)
    assert stt.describe(out.status) == "today's transcription budget is used up"


def test_concurrent_notes_cannot_overrun_the_ceiling(on, audio):
    """Room for exactly one 3-second note: two at once → one done, one refused."""
    on.setattr(settings, "transcribe_daily_cap_usd", 0.0004)   # one ≈ $0.0003
    on.setattr(stt, "call_provider", Provider(("ok", None), delay=0.2))
    r = FakeRedis()

    async def both():
        return await asyncio.gather(stt.transcribe_file(audio["voice2"], redis=r),
                                    stt.transcribe_file(audio["messenger"], redis=r))
    a, b = run(both())
    assert sorted([a.status, b.status]) == ["done", "failed:over_budget"]
    assert run(stt.spent_today(r)) <= 0.0004


def test_the_global_ai_stop_also_stops_transcription(on, audio):
    from app.services import ai_budget
    on.setattr(settings, "ai_daily_stop_usd", 1.0)
    r = FakeRedis()
    r.kv[ai_budget._day_key()] = 5.0
    p = Provider(("x", None))
    on.setattr(stt, "call_provider", p)
    assert run(stt.transcribe_file(audio["voice2"], redis=r)).status == "failed:over_budget"
    assert p.calls == []


def test_spend_is_metered_into_the_ai_breaker(on, audio):
    from app.services import ai_budget
    on.setattr(stt, "call_provider", Provider(("Nataka alb", None)))
    r = FakeRedis()
    out = run(stt.transcribe_file(audio["voice2"], redis=r))
    assert float(r.kv[ai_budget._day_key()]) == pytest.approx(out.cost_usd)
    by = r.h[ai_budget._by_key()]
    assert by["usd:transcribe"] == pytest.approx(out.cost_usd)
    assert by["calls:transcribe"] == 1 and by["calls:model:gpt-4o-transcribe"] == 1


# ── idempotency: the same audio is transcribed once ──────────────────────────

def test_a_redelivered_note_is_never_transcribed_twice(on, audio):
    p = Provider(("Nataka sinia mbili", None))
    on.setattr(stt, "call_provider", p)
    r = FakeRedis()
    a = run(stt.transcribe_file(audio["voice2"], redis=r))
    b = run(stt.transcribe_file(audio["voice2"], redis=r))
    assert a.text == b.text == "Nataka sinia mbili"
    assert len(p.calls) == 1 and b.cached and not a.cached
    assert run(stt.spent_today(r)) == pytest.approx(a.cost_usd)    # paid once


def test_concurrent_duplicates_share_one_call(on, audio):
    on.setattr(stt, "call_provider", Provider(("Nataka sinia", None), delay=0.5))
    p = stt.call_provider
    r = FakeRedis()

    async def three():
        return await asyncio.gather(*(stt.transcribe_file(audio["voice2"], redis=r) for _ in range(3)))
    outs = run(three())
    assert all(o.ok and o.text == "Nataka sinia" for o in outs)
    assert len(p.calls) == 1


# ── switches ─────────────────────────────────────────────────────────────────

def test_off_means_off(monkeypatch, audio):
    monkeypatch.setattr(settings, "whisper_enabled", False)
    assert run(stt.transcribe_file(audio["voice2"])).status == "failed:disabled"


def test_openai_without_a_key_is_named(on, audio):
    on.setattr(settings, "openai_api_key", "")
    assert run(stt.transcribe_file(audio["voice2"])).status == "failed:no_provider"


def test_faster_whisper_not_installed_is_named(on, audio):
    on.setattr(settings, "whisper_provider", "faster_whisper")
    import importlib.util
    if importlib.util.find_spec("faster_whisper"):
        pytest.skip("faster-whisper is installed here")
    assert run(stt.transcribe_file(audio["voice2"])).status == "failed:no_provider"


def test_status_kinds_cover_legacy_rows():
    assert stt.status_kind("pending") == "queued"
    assert stt.status_kind("failed") == "failed"
    assert stt.status_kind("failed:over_budget") == "failed"
    assert stt.status_kind(None) == "none"
    assert stt.status_kind("done") == "done"
    assert stt.describe("silent").startswith("no speech")


def test_the_engine_never_raises(on, audio, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(stt, "_transcribe", boom)
    assert run(stt.transcribe_file(audio["voice2"])).status == "failed:error"


# ── measurement ──────────────────────────────────────────────────────────────

def test_latency_engine_overhead_is_small(on, audio, capsys):
    """Provider fixed at 300 ms (a mocked gpt-4o-transcribe answer for a short
    note). Everything else — hashing, ffmpeg normalise + level, budget, cache —
    is the real code. Printed for the cycle's evidence table."""
    rows = []
    for key in ("voice", "messenger"):
        on.setattr(stt, "call_provider", Provider(("Nataka kasoki", None), delay=0.3))
        out = run(stt.transcribe_file(audio[key], redis=FakeRedis()))
        assert out.ok
        total, prov = out.timings_ms["total"], out.timings_ms["provider"]
        rows.append((key, out.duration_s, out.timings_ms["normalise"], prov, total, total - prov))
        assert total - prov < 1500, out.timings_ms
    # a cached replay costs no provider time at all
    r = FakeRedis()
    on.setattr(stt, "call_provider", Provider(("Nataka kasoki", None), delay=0.3))
    run(stt.transcribe_file(audio["voice"], redis=r))
    t = time.perf_counter()
    again = run(stt.transcribe_file(audio["voice"], redis=r))
    cached_ms = (time.perf_counter() - t) * 1000
    assert again.cached and cached_ms < 200
    with capsys.disabled():
        for key, dur, norm, prov, total, over in rows:
            print(f"\n[latency] {key}: audio {dur:.1f}s · normalise {norm:.0f} ms · provider {prov:.0f} ms"
                  f" · total {total:.0f} ms · engine overhead {over:.0f} ms")
        print(f"[latency] duplicate (cached): {cached_ms:.1f} ms")
