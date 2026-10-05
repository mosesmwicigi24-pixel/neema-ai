"""The transcriber handed our own hint back as the customer's speech (2026-10-05).

Production, read-only audit of the 74 transcribed voice notes: 30 of them
(41%) were the vocabulary hint itself — "Habari, nataka kasoki." (19),
"Bethany House, Nairobi." (6), the whole trade list (8) — for LOUD notes of
7–61 seconds (mean −15 to −29 dB, peaks at 0 dB): real speech, replaced by
"Hello, I want a cassock". The live case today: a customer pricing trays
sent a note, the agent "heard" a cassock request and quoted cassocks; the
customer re-recorded six minutes later ("a communion tray, several cups and
a chalice"). The agent got none of those 30 customers' words.

The engine now: (1) sends a plain list, no sentence; (2) builds it from the
live catalogue (services/stt_vocabulary); (3) treats a transcript made of
the hint's own words as an ECHO and transcribes the same audio again with NO
hint, keeping that answer; (4) never serves a result cached under the old
hint. Real audio, real ffmpeg, a scripted provider — no network, no keys.
"""
import asyncio
import json
import shutil

import pytest

import app.main  # noqa: F401 — registers models
from app.core import hub_client
from app.services import stt_vocabulary as sv
from app.services import transcribe as stt

from test_transcribe_engine import FakeRedis, _ff

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

# The hint production sent until 2026-10-05, verbatim.
OLD_HINT = ("Bethany House, Nairobi. Habari, nataka kasoki. Cassock, chasuble, alb, stole, "
            "surplice, cope, clergy shirt, collar, mitre, zucchetto, pectoral cross, "
            "mkate wa komunio, vikombe vya komunio, sinia, M-Pesa, Paybill, KES, shilingi.")

# The shapes the 30 echoed notes took in production (the transcripts are the
# hint, so quoting them reveals nothing about anyone).
PRODUCTION_ECHOES = [
    "Habari, nataka kasoki.",
    "Bethany House, Nairobi.",
    "Bethany House, Nairobi. Habari, nataka kasoki.",
    "nataka kasoki",
    "Habari, nataka kasoki. Cassock",
    "Habari, nataka kasoki. Cassock, chasuble, alb, stole, surplice, cope, clergy shirt, "
    "collar, mitre, zucchetto, pectoral cross, mkate wa komunio, vikombe vya komunio, sinia.",
    OLD_HINT,
]

# Real speech from the same audit (paraphrased where personal).
REAL_SPEECH = [
    "Hi there, I need to buy a communion tray, several cups and a chalice cup.",
    "Good morning, good morning, I'm looking for a prayer shawl.",
    "Kanisani kwetu vikombe vipo. Ninachotaka ni kisinia cha kubebea vikombe, pamoja na "
    "sinia ya kubebea mikate. Bei gani?",
    "Personnellement, j'ai besoin de chemises pastorales et aussi de toges pastorales.",
    "Sorry, I'm not looking for a big cup. I am looking for tots, and a golden big tray.",
]


class HintAware:
    """A provider that, like the real one did, returns the hint when it is
    given one (`echo`), and the speech when it is not. Records the hint each
    call carried (read through stt.vocabulary(), as the real providers do)."""

    def __init__(self, speech, echo="hint", fail_without_hint=False):
        self.speech, self.echo, self.fail = speech, echo, fail_without_hint
        self.hints: list[str] = []

    def __call__(self, path, prov, model):
        h = stt.vocabulary()
        self.hints.append(h)
        if h:
            return (h if self.echo == "hint" else self.echo), None
        if self.fail:
            raise RuntimeError("provider down")
        return self.speech, None


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def on(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "whisper_enabled", True)
    monkeypatch.setattr(settings, "whisper_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-not-real")
    monkeypatch.setattr(settings, "transcribe_model", "gpt-4o-transcribe")
    monkeypatch.setattr(settings, "transcribe_vocabulary", None)
    monkeypatch.setattr(settings, "transcribe_daily_cap_usd", 3.0)
    monkeypatch.setattr(settings, "transcribe_retries", 2)
    monkeypatch.setattr(stt, "BACKOFF", (0.0, 0.0, 0.0))
    return monkeypatch


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """Three seconds of a voice-note-shaped ogg/opus (loud enough to send)."""
    path = str(tmp_path_factory.mktemp("echo") / "note.ogg")
    _ff("-f", "lavfi", "-i", "sine=frequency=550:duration=3", "-c:a", "libopus", "-f", "ogg", path)
    return path


# ── the detector, on production's own strings ────────────────────────────────

@pytest.mark.parametrize("text", PRODUCTION_ECHOES)
def test_every_production_echo_is_recognised(text):
    assert stt.prompt_echo(text, OLD_HINT) == "full"


@pytest.mark.parametrize("text", REAL_SPEECH)
def test_real_speech_is_not_an_echo(text):
    assert stt.prompt_echo(text, stt.VOCABULARY) is None
    assert stt.prompt_echo(text, OLD_HINT) is None


def test_a_spliced_in_run_is_partial_and_is_cut_out():
    hint = stt.VOCABULARY
    text = ("I want a tray for forty cups. cassock, kasoki, kanzu, chasuble, alb, stole, "
            "stola, surplice")
    assert stt.prompt_echo(text, hint) == "partial"
    assert stt.strip_echo(text, hint) == "I want a tray for forty cups."
    # five of OUR words in a row inside real speech — and only then
    assert stt.prompt_echo("cassock, chasuble and an alb please", hint) is None


def test_the_static_hint_is_a_list_not_a_sentence():
    v = stt.VOCABULARY.lower()
    assert "habari" not in v and "nataka" not in v and "nairobi" not in v
    assert "." not in v


# ── the engine ───────────────────────────────────────────────────────────────

def test_an_echo_is_transcribed_again_without_the_hint(on, clip):
    p = HintAware("Hi there, I need to buy a communion tray, several cups and a chalice cup.")
    on.setattr(stt, "call_provider", p)
    r = FakeRedis()
    out = run(stt.transcribe_file(clip, redis=r))
    assert out.ok and out.text.startswith("Hi there, I need to buy a communion tray")
    assert len(p.hints) == 2 and p.hints[0] and p.hints[1] == ""
    # both requests are paid for and counted against the day's ceiling
    assert run(stt.spent_today(r)) == pytest.approx(2 * out.duration_s / 60 * 0.006, rel=1e-3)


def test_a_customer_who_really_says_it_is_heard(on, clip):
    """The retry carries no hint — so what it hears is theirs, even a note
    that only says the words the hint holds."""
    p = HintAware("Kasoki, stola.", echo="Kasoki, stola.")
    on.setattr(stt, "call_provider", p)
    out = run(stt.transcribe_file(clip, redis=FakeRedis()))
    assert out.ok and out.text == "Kasoki, stola." and len(p.hints) == 2


def test_an_echo_that_cannot_be_retried_is_unheard_never_a_cassock(on, clip):
    p = HintAware("ignored", fail_without_hint=True)
    on.setattr(stt, "call_provider", p)
    on.setattr(stt, "BACKOFF", (0.0, 0.0, 0.0))
    out = run(stt.transcribe_file(clip, redis=FakeRedis()))
    assert out.status == "failed:echo" and out.text == ""
    assert "could not be made out" in stt.describe(out.status)


def test_an_echo_over_budget_is_unheard(on, clip):
    from app.core.config import settings
    p = HintAware("words")
    on.setattr(stt, "call_provider", p)
    r = FakeRedis()
    # room for the first request only
    on.setattr(settings, "transcribe_daily_cap_usd", 0.0005)
    out = run(stt.transcribe_file(clip, redis=r))
    assert out.status == "failed:echo" and len(p.hints) == 1


def test_a_partial_echo_with_no_retry_keeps_only_their_words(on, clip):
    hint = stt.VOCABULARY
    spliced = "Nataka sinia mbili. cassock, kasoki, kanzu, chasuble, alb, stole"
    p = HintAware("x", echo=spliced, fail_without_hint=True)
    on.setattr(stt, "call_provider", p)
    on.setattr(stt, "BACKOFF", (0.0, 0.0, 0.0))
    out = run(stt.transcribe_file(clip, redis=FakeRedis()))
    assert out.ok and out.text == "Nataka sinia mbili."
    assert stt.prompt_echo(out.text, hint) is None


def test_speech_needs_one_request(on, clip):
    p = HintAware("x", echo="Habari, nataka kasoki nyeusi size 52")
    on.setattr(stt, "call_provider", p)
    out = run(stt.transcribe_file(clip, redis=FakeRedis()))
    assert out.ok and len(p.hints) == 1


def test_a_result_cached_under_the_old_hint_is_never_served(on, clip):
    """Thirty days of cached echoes: the old cache key is not read."""
    r = FakeRedis()
    digest = stt.file_hash(clip)
    r.kv[f"transcribe:result:{digest}"] = stt.Transcript(
        status="done", text="Habari, nataka kasoki.", lang="sw").to_cache()
    p = HintAware("I need two trays")
    on.setattr(stt, "call_provider", p)
    out = run(stt.transcribe_file(clip, redis=r))
    assert out.text == "I need two trays" and not out.cached


# ── the hint, from the live catalogue ────────────────────────────────────────

CATALOG = json.load(open(__file__.rsplit("/", 1)[0] + "/fixtures/catalog_snapshot_2026_10_05.json",
                         encoding="utf-8"))


def test_the_hint_is_built_from_the_catalogue():
    h = sv.build_hint(CATALOG)
    assert len(h) <= sv.HINT_MAX_CHARS
    low = h.lower()
    # the words a speech model gets wrong, from today's hub names
    for w in ("chasuble", "ciborium", "aspergillum", "tallit", "thurible", "surplice",
              "mitre", "crozier", "cincture", "chalice", "cassock", "pectoral cross",
              "communion cups"):
        assert w in low, w
    # how customers say them (core/vernacular), and the payment words
    for w in ("kasoki", "stola", "shati ya kola", "sinia", "vikombe vya ushirika",
              "chemise pastorale", "m-pesa", "paybill"):
        assert w in low, w
    # a list, each phrase once, no sentence to hand back
    parts = [x.strip() for x in h.split(",")]
    assert len(parts) == len({x.lower() for x in parts})
    assert "." not in h and "habari" not in low and "nataka" not in low


def test_the_hint_respects_its_cap():
    assert len(sv.build_hint(CATALOG, max_chars=300)) <= 300
    assert sv.build_hint([]) .startswith("kasoki")          # no catalogue: the spoken words


def test_live_hint_reads_the_cached_catalogue_and_caches_itself(monkeypatch):
    sv._cache.clear()
    r = FakeRedis()
    assert run(sv.live_hint(r)) is None                       # nothing cached → static list
    assert run(sv.live_hint(None)) is None
    r.kv[hub_client._LAST_GOOD_KEY] = json.dumps(CATALOG)
    h = run(sv.live_hint(r))
    assert h and "ciborium" in h
    calls = []
    monkeypatch.setattr(sv, "build_hint", lambda items: calls.append(1) or "x")
    assert run(sv.live_hint(r)) == h and calls == []          # cached per catalogue


def test_the_engine_sends_the_live_hint_and_guards_it(on, clip):
    """The catalogue in redis → its words go with the request; an echo of
    THOSE words is caught the same way."""
    sv._cache.clear()
    r = FakeRedis()
    r.kv[hub_client._CACHE_KEY] = json.dumps(CATALOG)
    p = HintAware("Nataka sinia ya vikombe arobaini.")
    on.setattr(stt, "call_provider", p)
    out = run(stt.transcribe_file(clip, redis=r))
    assert "ciborium" in p.hints[0] and p.hints[1] == ""
    assert out.text == "Nataka sinia ya vikombe arobaini."


def test_the_owners_override_still_wins(on, clip):
    from app.core.config import settings
    on.setattr(settings, "transcribe_vocabulary", "Bethany House")
    p = HintAware("Nataka kasoki.", echo="Nataka kasoki.")
    on.setattr(stt, "call_provider", p)
    out = run(stt.transcribe_file(clip, redis=FakeRedis()))
    assert p.hints[0] == "Bethany House" and out.text == "Nataka kasoki." and len(p.hints) == 1
