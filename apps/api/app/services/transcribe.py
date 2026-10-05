"""Speech → text. ONE engine for every voice note and every call recording.

Why this exists (cycle 4, 2026-10-05). In 30 days production received 87
voice notes and 15 recorded calls and transcribed none of them:

  · WhatsApp voice notes — wa_native rehosted each note with
    `mimetypes.guess_extension("audio/ogg")`, which is None on the slim
    Python image (no /etc/mime.types), so every note was saved as a bare
    `wa_<media id>` with no extension. The configured provider
    (faster_whisper) is not installed → ImportError, swallowed; the OpenAI
    fallback then uploaded an extensionless file, which OpenAI refuses
    (format is read from the file name) → logged, None. The agent got
    "(the customer sent a audio)" and told customers she can't listen.
  · Messenger / Instagram audio — same fallback chain, guessing the
    extension from the CDN content-type.
  · Call recordings — whisper_enabled=False, so nothing was ever scheduled;
    and on a manual run faster_whisper would have failed to import.

What the engine guarantees, whatever the caller:

  · Normalised input: ffmpeg decodes ANY container (ogg/opus, mp4/aac,
    webm, amr, extensionless) to 16 kHz mono MP3 — one format every
    provider accepts — measuring the duration and the peak level in the
    same pass. A file ffmpeg cannot decode is `failed:corrupt`.
  · Limits: raw size, duration (voice notes 10 min, calls 60 min), a
    timeout per provider request, and retries with backoff on the failures
    that heal (timeout, 429, 5xx, connection) — never on a refusal (400,
    401). Long audio goes in 10-minute pieces.
  · Silence costs nothing: a peak below transcribe_silence_db is `silent`
    without a provider call; a provider answer that is only a known
    no-speech artefact ("♪", "[Music]", "Thanks for watching!") is too.
  · A daily cost ceiling with a counter (redis, UTC day), RESERVED before
    the call and refunded on a failure the provider can't have billed (a
    timed-out request stays counted), so two concurrent notes can't both
    squeeze under it. The spend also feeds the AI breaker's day total.
  · Idempotency: the same audio bytes are transcribed once — the result is
    cached by content hash for 30 days and a lock absorbs concurrent
    duplicates (Meta redelivers webhooks).
  · Never raises. Every outcome is a Transcript whose `status` says what
    happened in words the team can read: done | silent | failed:<reason>.

The transcript is DATA — the customer's words. Nothing here ever treats it
as an instruction; callers hand it to the agent as the customer's turn.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field

from app.core.config import settings

_log = logging.getLogger("neema.transcribe")

# Reasons a transcription can fail. Short on purpose: they are stored on the
# row (`failed:<reason>`, VARCHAR(40)) and shown to the team as plain words.
REASON_WORDS = {
    "disabled": "transcription is switched off",
    "no_provider": "no transcription provider is configured",
    "no_file": "the audio file is missing",
    "too_large": "the audio file is too large",
    "too_long": "the recording is longer than the limit",
    "corrupt": "the audio could not be decoded",
    "decode_timeout": "the audio took too long to decode (the server was busy)",
    "over_budget": "today's transcription budget is used up",
    "provider_timeout": "the transcription service timed out",
    "provider_busy": "the transcription service was rate-limited",
    "provider_unreachable": "the transcription service could not be reached",
    "provider_error": "the transcription service failed",
    "provider_auth": "the transcription key was refused",
    "provider_rejected": "the transcription service refused the audio",
    "busy": "another worker is transcribing this audio",
    "error": "an unexpected error",
    "analysis": "the AI summary couldn't be made (the transcript is kept)",
}

# USD per audio minute. gpt-4o-transcribe is token-billed; OpenAI quotes it at
# ≈$0.006/min. Unknown models are priced HIGH so the ceiling never under-counts.
PRICE_PER_MIN = {
    "whisper-1": 0.006,
    "gpt-4o-transcribe": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
    "whisper-large-v3": 0.111 / 60,         # Groq
    "whisper-large-v3-turbo": 0.04 / 60,    # Groq
    "faster_whisper": 0.0,                  # on our own CPU
}
_UNKNOWN_PRICE = 0.012

# What Whisper-family models emit for silence or music. Matched against the
# WHOLE transcript only (a real note that merely contains "thank you" stays).
_ARTEFACTS = {
    "thanks for watching", "thank you for watching", "thanks for watching!",
    "please subscribe", "like and subscribe",
    "subtitles by the amara.org community", "subtitles by amara.org",
    "music", "[music]", "(music)", "[silence]", "(silence)", "[no speech]",
    "[blank_audio]", "[ silence ]", "...", "…",
}
_MUSIC_ONLY = re.compile(r"^[\s♪♫🎵🎶.\-–—*]*$")

# Words the transcriber should spell right — a vocabulary hint, never an
# instruction. OpenAI's guide says a prompt "should match the audio language",
# and an English-only prompt can nudge a Swahili note toward an English
# rendering; so the hint is deliberately bilingual and noun-only. Replace (or
# blank, to send none) with TRANSCRIBE_VOCABULARY.
VOCABULARY = (
    "Bethany House, Nairobi. Habari, nataka kasoki. Cassock, chasuble, alb, stole, "
    "surplice, cope, clergy shirt, collar, mitre, zucchetto, pectoral cross, "
    "mkate wa komunio, vikombe vya komunio, sinia, M-Pesa, Paybill, KES, shilingi."
)
KEYWORDS = ("Bethany House", "cassock", "kasoki", "chasuble", "alb", "stole", "surplice",
            "clergy shirt", "mitre", "zucchetto", "komunio", "M-Pesa", "Paybill", "KES")
LANGUAGES = ("en", "sw", "fr")    # what our customers speak (gpt-transcribe's hint)


def vocabulary() -> str:
    v = settings.transcribe_vocabulary
    return VOCABULARY if v is None else v.strip()


BACKOFF = (1.0, 4.0, 10.0)     # seconds before retry 1, 2, 3 (±20% jitter)
_CACHE_TTL = 30 * 86400
_LOCK_TTL = 900
_SPEND_TTL = 3 * 86400

# ISO-639-1 for the language names Whisper's verbose_json returns.
_LANG_ISO = {
    "english": "en", "swahili": "sw", "french": "fr", "portuguese": "pt",
    "spanish": "es", "german": "de", "italian": "it", "arabic": "ar",
    "amharic": "am", "somali": "so", "kinyarwanda": "rw", "luganda": "lg",
    "yoruba": "yo", "hausa": "ha", "zulu": "zu", "xhosa": "xh", "afrikaans": "af",
    "dutch": "nl", "russian": "ru", "bulgarian": "bg", "chinese": "zh",
    "hindi": "hi", "indonesian": "id", "korean": "ko", "japanese": "ja",
    "shona": "sn", "lingala": "ln", "malagasy": "mg",
}
ISO_NAME = {v: k.capitalize() for k, v in _LANG_ISO.items()}


def lang_code(lang: str | None) -> str | None:
    """'Swahili' / 'swahili' / 'sw' / 'sw-KE' → 'sw'. None when unknown/blank."""
    s = (lang or "").strip().lower()
    if not s:
        return None
    if s in _LANG_ISO:
        return _LANG_ISO[s]
    base = s.split("-")[0].split("_")[0]
    if len(base) == 2 and base.isalpha():
        return base
    # "Swahili and English" / "mostly swahili, some sheng" — the first
    # language named (the analysis lists the main one first). Before cycle 6
    # this stored the raw phrase cut to 12 characters ("swahili and ").
    for w in re.findall(r"[a-z]+", s):
        if w in _LANG_ISO:
            return _LANG_ISO[w]
        if w == "sheng":
            return "sw"
    return base if len(base) == 3 and base.isalpha() else None


def lang_name(lang: str | None) -> str | None:
    c = lang_code(lang)
    if not c:
        return None
    return ISO_NAME.get(c, c.capitalize())


@dataclass
class Transcript:
    status: str                       # done | silent | failed:<reason>
    text: str = ""
    lang: str | None = None           # ISO-639-1 when known
    lang_source: str | None = None    # "provider" (the model said) | "guess" (word lists)
    duration_s: float = 0.0
    provider: str = ""
    model: str = ""
    cost_usd: float = 0.0
    cached: bool = False
    timings_ms: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "done" and bool(self.text.strip())

    @property
    def reason(self) -> str | None:
        return self.status.split(":", 1)[1] if self.status.startswith("failed:") else None

    def to_cache(self) -> str:
        return json.dumps({"status": self.status, "text": self.text, "lang": self.lang,
                           "lang_source": self.lang_source, "duration_s": self.duration_s, "provider": self.provider,
                           "model": self.model})

    @classmethod
    def from_cache(cls, raw) -> "Transcript | None":
        try:
            d = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            return cls(status=str(d["status"]), text=str(d.get("text") or ""),
                       lang=d.get("lang"), lang_source=d.get("lang_source"),
                       duration_s=float(d.get("duration_s") or 0),
                       provider=str(d.get("provider") or ""), model=str(d.get("model") or ""),
                       cached=True)
        except Exception:
            return None


def failed(reason: str, **kw) -> Transcript:
    return Transcript(status=f"failed:{reason}", **kw)


def describe(status: str | None) -> str:
    """A stored status → words for the team ("over_budget" → "today's …")."""
    s = (status or "").strip()
    if s.startswith("failed:"):
        return REASON_WORDS.get(s[7:], s[7:].replace("_", " "))
    if s == "silent":
        return "no speech was heard (silence or music)"
    return s


# ── provider selection ───────────────────────────────────────────────────────

def provider() -> str:
    return (settings.whisper_provider or "openai").strip().lower()


def model_for(prov: str | None = None) -> str:
    p = prov or provider()
    if p == "openai":
        return (settings.transcribe_model or "gpt-4o-transcribe").strip()
    if p == "groq":
        return (settings.groq_transcribe_model or "whisper-large-v3").strip()
    return "faster_whisper"


def price_per_min(model: str) -> float:
    return PRICE_PER_MIN.get((model or "").strip().lower(), _UNKNOWN_PRICE)


def configured() -> str | None:
    """None when the engine can run; otherwise the failure reason."""
    if not settings.whisper_enabled:
        return "disabled"
    p = provider()
    if p == "openai":
        return None if settings.openai_api_key else "no_provider"
    if p == "groq":
        return None if settings.groq_api_key else "no_provider"
    try:
        import importlib.util
        return None if importlib.util.find_spec("faster_whisper") else "no_provider"
    except Exception:
        return "no_provider"


# ── ffmpeg: one decode pass → normalised mp3 + duration + peak level ─────────

_MAXVOL = re.compile(r"max_volume:\s*(-?[\d.]+|-inf)\s*dB")
_TIME = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_DUR = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


async def _run(cmd: list[str], timeout: float) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise
    return proc.returncode or 0, (err or b"").decode("utf-8", "replace")


def _secs(m) -> float:
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


async def normalise(src: str, dst: str, max_seconds: int) -> tuple[float, float | None]:
    """Decode `src` (any container, any or no extension) to 16 kHz mono MP3 at
    `dst`, reading at most max_seconds+1 of it. Returns (duration_s, peak_db).
    Raises ValueError("corrupt") when ffmpeg cannot decode a second of it."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed")
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", src,
           "-t", str(int(max_seconds) + 1), "-vn", "-ac", "1", "-ar", "16000",
           "-af", "volumedetect", "-c:a", "libmp3lame", "-b:a", "48k", dst]
    rc, err = await _run(cmd, timeout=max(60, max_seconds / 10))
    if rc != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
        raise ValueError("corrupt")
    times = _TIME.findall(err)
    if times:
        h, m, s = times[-1]
        dur = int(h) * 3600 + int(m) * 60 + float(s)
    else:
        d = _DUR.search(err)
        dur = _secs(d) if d else 0.0
    mv = _MAXVOL.search(err)
    peak = None
    if mv:
        peak = float("-inf") if mv.group(1) == "-inf" else float(mv.group(1))
    if dur <= 0.05:
        raise ValueError("corrupt")
    return dur, peak


async def split(src: str, seconds: int, workdir: str) -> list[str]:
    """Cut a normalised MP3 into `seconds`-long pieces (stream copy — fast)."""
    pattern = os.path.join(workdir, "piece%03d.mp3")
    rc, _err = await _run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", src,
                           "-f", "segment", "-segment_time", str(int(seconds)),
                           "-c", "copy", pattern], timeout=120)
    pieces = sorted(os.path.join(workdir, f) for f in os.listdir(workdir)
                    if f.startswith("piece") and f.endswith(".mp3"))
    if rc != 0 or not pieces:
        return [src]
    return pieces


# ── providers (BLOCKING — always called via asyncio.to_thread) ───────────────

def _openai_transcribe(path: str, model: str) -> tuple[str, str | None]:
    """One OpenAI transcription request. The file goes up with its `.mp3`
    name — the SDK's own docs: "The request must include enough format
    metadata for the file to be identified" (the extensionless notes failed
    exactly there)."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key,
                    timeout=float(settings.transcribe_timeout_seconds), max_retries=0)
    hint = vocabulary()
    with open(path, "rb") as f:
        kw: dict = {"model": model, "file": f}
        if model == "whisper-1":
            # verbose_json carries the detected language ("swahili").
            kw["response_format"] = "verbose_json"
        elif model == "gpt-transcribe":
            # Newer model: guided by keywords + the languages we expect.
            kw.update(response_format="json", keywords=list(KEYWORDS), languages=list(LANGUAGES))
            hint = ""
        else:
            kw["response_format"] = "json"      # the only format gpt-4o-*transcribe take
        if hint:
            kw["prompt"] = hint
        resp = client.audio.transcriptions.create(**kw)
    text = (getattr(resp, "text", "") or "").strip()
    return text, lang_code(getattr(resp, "language", None))


def _groq_transcribe(path: str, model: str) -> tuple[str, str | None]:
    from groq import Groq
    client = Groq(api_key=settings.groq_api_key,
                  timeout=float(settings.transcribe_timeout_seconds), max_retries=0)
    with open(path, "rb") as f:
        kw: dict = {"model": model, "file": f, "response_format": "verbose_json"}
        if vocabulary():
            kw["prompt"] = vocabulary()
        resp = client.audio.transcriptions.create(**kw)
    return (getattr(resp, "text", "") or "").strip(), lang_code(getattr(resp, "language", None))


def _local_transcribe(path: str, model: str) -> tuple[str, str | None]:
    from app.services import call_transcribe as ct
    text, lang = ct._transcribe_faster_whisper(path)
    return text, lang_code(lang)


def call_provider(path: str, prov: str, model: str) -> tuple[str, str | None]:
    """BLOCKING. One request to the chosen backend → (text, iso_lang|None).
    The single seam tests replace."""
    if prov == "openai":
        return _openai_transcribe(path, model)
    if prov == "groq":
        return _groq_transcribe(path, model)
    return _local_transcribe(path, model)


def classify(exc: BaseException) -> tuple[str, bool]:
    """(reason, retryable) for a provider failure — by status code and class
    name, so it works for openai, groq and httpx errors alike."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "Timeout" in type(exc).__name__:
        return "provider_timeout", True
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if status == 429:
        return "provider_busy", True
    if status is not None and status >= 500:
        return "provider_error", True
    if status in (401, 403):
        return "provider_auth", False
    if status is not None and 400 <= status < 500:
        return "provider_rejected", False
    if "Connection" in type(exc).__name__:
        return "provider_unreachable", True
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "no_provider", False
    return "provider_error", False


async def _attempts(path: str, prov: str, model: str) -> tuple[str, str | None]:
    """The provider call with a hard timeout and backoff retries. Raises the
    last error (classified by the caller)."""
    tries = 1 + max(0, int(settings.transcribe_retries))
    backoff = BACKOFF
    last: BaseException | None = None
    for i in range(tries):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(call_provider, path, prov, model),
                timeout=float(settings.transcribe_timeout_seconds) * 1.25 + 1)
        except Exception as exc:              # noqa: BLE001 — classified below
            last = exc
            reason, retryable = classify(exc)
            _log.warning("transcribe: %s/%s attempt %d/%d failed (%s): %s",
                         prov, model, i + 1, tries, reason, str(exc)[:200])
            if not retryable or i == tries - 1:
                raise
            await asyncio.sleep(backoff[min(i, len(backoff) - 1)] * (0.8 + 0.4 * random.random()))
    raise last or RuntimeError("no attempt made")


# ── the daily ceiling ────────────────────────────────────────────────────────

def _spend_key() -> str:
    from datetime import datetime, timezone
    return "transcribe:spend:" + datetime.now(timezone.utc).strftime("%Y%m%d")


async def spent_today(redis) -> float:
    if redis is None:
        return 0.0
    try:
        raw = await redis.get(_spend_key())
        return float(raw.decode() if isinstance(raw, bytes) else raw) if raw is not None else 0.0
    except Exception:
        return 0.0


async def _reserve(redis, usd: float) -> bool:
    """Atomically reserve `usd` of today's ceiling. False = over budget. Fails
    OPEN on a redis error (a metric is lost, never a customer's words) — but
    the global AI stop still applies."""
    try:
        from app.services import ai_budget
        if await ai_budget.mode(redis) == "stop":
            return False
    except Exception:
        pass
    cap = float(settings.transcribe_daily_cap_usd or 0)
    if redis is None or usd <= 0:
        return True
    try:
        key = _spend_key()
        new = float(await redis.incrbyfloat(key, round(usd, 6)))
        await redis.expire(key, _SPEND_TTL)
        if cap > 0 and new > cap + 1e-9:
            await redis.incrbyfloat(key, -round(usd, 6))
            return False
        return True
    except Exception:
        return True


async def _refund(redis, usd: float) -> None:
    if redis is None or usd <= 0:
        return
    try:
        await redis.incrbyfloat(_spend_key(), -round(usd, 6))
    except Exception:
        pass


async def _meter(redis, model: str, usd: float) -> None:
    """Feed the AI breaker's day total + its breakdown (purpose 'transcribe')."""
    try:
        from app.services import ai_budget
        await ai_budget.meter_flat(model, usd, purpose="transcribe", redis=redis)
    except Exception:
        pass


# ── the engine ───────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    low = re.sub(r"\s+", " ", t.lower()).strip()
    if low in _ARTEFACTS or _MUSIC_ONLY.match(low):
        return ""
    return t


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def transcribe_file(path: str | None, *, kind: str = "voice_note", redis=None) -> Transcript:
    """Transcribe one audio file. kind = "voice_note" | "call" (sets the
    duration limit). Never raises; see the module docstring for guarantees."""
    t0 = time.perf_counter()
    if redis is None:
        # A caller that passed none still meets the daily ceiling, the cache
        # and the duplicate lock: the app's redis, attached at boot.
        try:
            from app.services import ai_budget
            redis = ai_budget._sink
        except Exception:
            redis = None
    try:
        out = await _transcribe(path, kind, redis)
    except Exception as exc:                  # noqa: BLE001 — the engine never raises
        _log.exception("transcribe: unexpected failure on %s: %s", path, exc)
        out = failed("error")
    out.timings_ms["total"] = round((time.perf_counter() - t0) * 1000, 1)
    _log.info("transcribe %s: %s (%.1fs audio, %s/%s, $%.4f, %.0f ms%s)", kind, out.status,
              out.duration_s, out.provider or "-", out.model or "-", out.cost_usd,
              out.timings_ms["total"], ", cached" if out.cached else "")
    return out


async def _transcribe(path: str | None, kind: str, redis) -> Transcript:
    why = configured()
    if why:
        return failed(why)
    if not path or not os.path.exists(path):
        return failed("no_file")
    size = os.path.getsize(path)
    if size == 0:
        return failed("corrupt")
    if size > int(settings.transcribe_max_bytes):
        return failed("too_large")

    prov, model = provider(), model_for()
    digest = await asyncio.to_thread(file_hash, path)
    ckey, lkey = f"transcribe:result:{digest}", f"transcribe:lock:{digest}"

    # Idempotency: the same bytes are transcribed once.
    if redis is not None:
        try:
            hit = await redis.get(ckey)
            if hit:
                cached = Transcript.from_cache(hit)
                if cached is not None:
                    return cached
            if not await redis.set(lkey, "1", nx=True, ex=_LOCK_TTL):
                # A twin delivery is mid-flight: wait for its answer.
                for _ in range(int(settings.transcribe_timeout_seconds) + 30):
                    await asyncio.sleep(1)
                    hit = await redis.get(ckey)
                    if hit and (cached := Transcript.from_cache(hit)) is not None:
                        return cached
                    if not await redis.get(lkey):
                        break
                return failed("busy")
        except Exception:
            pass

    try:
        result = await _work(path, kind, prov, model, redis)
        # Cache outcomes that would come out the same next time; a transient
        # failure (timeout, budget, 5xx) must stay retryable.
        if redis is not None and (result.status in ("done", "silent")
                                  or result.reason in ("corrupt", "too_long", "too_large")):
            try:
                await redis.set(ckey, result.to_cache(), ex=_CACHE_TTL)
            except Exception:
                pass
        return result
    finally:
        if redis is not None:
            try:
                await redis.delete(lkey)
            except Exception:
                pass


async def _work(path: str, kind: str, prov: str, model: str, redis) -> Transcript:
    max_s = int(settings.transcribe_call_max_seconds if kind == "call"
                else settings.transcribe_voice_max_seconds)
    timings: dict = {}
    with tempfile.TemporaryDirectory(prefix="neema-stt-") as work:
        norm = os.path.join(work, "audio.mp3")
        t = time.perf_counter()
        try:
            duration, peak = await normalise(path, norm, max_s)
        except ValueError:
            return failed("corrupt", provider=prov, model=model)
        except asyncio.TimeoutError:
            # Load (a burst of notes, a busy box), not proof the file is bad:
            # never cached as `corrupt`, so the same audio can be tried again.
            return failed("decode_timeout", provider=prov, model=model)
        timings["normalise"] = round((time.perf_counter() - t) * 1000, 1)
        base = dict(duration_s=round(duration, 2), provider=prov, model=model, timings_ms=timings)
        if duration > max_s + 0.5:
            return failed("too_long", **base)
        if peak is not None and peak < float(settings.transcribe_silence_db):
            return Transcript(status="silent", **base)

        usd = round(duration / 60.0 * price_per_min(model), 6)
        if not await _reserve(redis, usd):
            return failed("over_budget", **base)

        t = time.perf_counter()
        try:
            chunk = max(60, int(settings.transcribe_chunk_seconds))
            pieces = await split(norm, chunk, work) if duration > chunk + 1 else [norm]
            texts: list[str] = []
            lang: str | None = None
            for p in pieces:
                text, got = await _attempts(p, prov, model)
                if text.strip():
                    texts.append(text.strip())
                lang = lang or got
        except Exception as exc:              # noqa: BLE001
            reason, _ = classify(exc)
            if reason == "provider_timeout":
                # A request cut off by OUR timeout runs on in its thread and
                # reaches the provider, which bills it: the reservation stays
                # spent (refunding it let the ceiling be passed).
                await _meter(redis, model, usd)
            else:
                await _refund(redis, usd)
            timings["provider"] = round((time.perf_counter() - t) * 1000, 1)
            return failed(reason, **base)
        timings["provider"] = round((time.perf_counter() - t) * 1000, 1)

        await _meter(redis, model, usd)
        text = _clean(" ".join(texts))
        if not text:
            return Transcript(status="silent", cost_usd=usd, **base)
        guessed = None if lang else guess_lang(text)
        return Transcript(status="done", text=text, lang=lang or guessed,
                          lang_source="provider" if lang else ("guess" if guessed else None),
                          cost_usd=usd, **base)


# ── a cheap language guess (fallback when the model gives none) ──────────────

_FR = {"je", "tu", "nous", "vous", "le", "la", "les", "des", "est", "et", "pour",
       "bonjour", "merci", "combien", "avec", "une", "un", "pas", "oui", "voudrais",
       "prix", "coûte", "s'il", "plaît"}


def guess_lang(text: str) -> str | None:
    """'en' | 'sw' | 'fr' | None from word lists (the translator's own lists).
    Code-mixed Sheng with any real Swahili counts as 'sw' — it is what the
    team needs translated."""
    from app.services.translate import _ENGLISH, _SWAHILI, _WORD_RE
    words = [w.lower() for w in _WORD_RE.findall(text or "")]
    if not words:
        return None
    en = sum(w in _ENGLISH for w in words)
    sw = sum(w in _SWAHILI for w in words)
    fr = sum(w in _FR for w in words)
    best = max(en, sw, fr)
    if best == 0:
        return None
    if sw and sw >= max(1, en // 2) and sw >= fr:
        return "sw"
    if fr == best and fr > en:
        return "fr"
    return "en" if en == best else ("sw" if sw == best else "fr")


def status_kind(status: str | None) -> str:
    """A stored transcript status → its kind: none | recorded | queued |
    processing | done | silent | failed. Legacy `pending` is queued; bare
    `failed` (rows before 2026-10-05) is failed."""
    s = (status or "").strip()
    if not s:
        return "none"
    if s == "pending":
        return "queued"
    if s == "failed" or s.startswith("failed:"):
        return "failed"
    return s
