"""Call transcription pipeline — provider dispatch, LLM summary, note-saving,
and the fire-and-forget scheduler. Mirrors the repo's fake-db style (no DB fixture).

Requires Python 3.11 (SQLAlchemy models). Imports app.main to register the mapper
so a real (transient) User() works with flag_modified.
"""
import asyncio
import types

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.services.call_transcribe as ct
import app.agent.memory as memory
from app.core.config import settings
from app.models.user import User


# ── fake db (queued results, records commits/adds/flushes) ───────────────────

class _Res:
    def __init__(self, one=None):
        self._one = one
    def scalar_one_or_none(self):
        return self._one


class _FakeDB:
    def __init__(self, results):
        self._results, self._i = list(results), 0
        self.commits = 0
        self.added = []
        self.flushes = 0
    async def execute(self, *a, **k):
        r = self._results[self._i]; self._i += 1
        return r
    def add(self, obj):
        self.added.append(obj)
    async def flush(self):
        self.flushes += 1
    async def commit(self):
        self.commits += 1


# ── provider dispatch ────────────────────────────────────────────────────────

def test_transcribe_sync_routes_by_provider(monkeypatch):
    monkeypatch.setattr(ct, "_transcribe_faster_whisper", lambda p: ("fw", "sw"))
    monkeypatch.setattr(ct, "_transcribe_openai", lambda p: ("oa", "en"))
    monkeypatch.setattr(ct, "_transcribe_groq", lambda p: ("gq", ""))

    monkeypatch.setattr(settings, "whisper_provider", "faster_whisper", raising=False)
    assert ct._transcribe_sync("x") == ("fw", "sw")
    monkeypatch.setattr(settings, "whisper_provider", "openai", raising=False)
    assert ct._transcribe_sync("x") == ("oa", "en")
    monkeypatch.setattr(settings, "whisper_provider", "groq", raising=False)
    assert ct._transcribe_sync("x") == ("gq", "")
    # Unknown provider falls back to the free self-hosted path.
    monkeypatch.setattr(settings, "whisper_provider", "weird", raising=False)
    assert ct._transcribe_sync("x") == ("fw", "sw")


# ── LLM summary ──────────────────────────────────────────────────────────────

def test_summarize_transcript_uses_light_model(monkeypatch):
    captured = {}

    class _FakeLLM:
        async def complete(self, *, system, messages, tools):
            captured.update(system=system, messages=messages, tools=tools)
            return types.SimpleNamespace(text="  Two cassocks, KES 9000, deliver Fri  ")

    monkeypatch.setattr("app.agent.runtime.build_llm", lambda model=None: _FakeLLM())
    out = asyncio.run(ct.summarize_transcript("Nataka cass mbili, how much? Ni 9000."))
    assert out == "Two cassocks, KES 9000, deliver Fri"          # stripped
    assert captured["messages"][0]["content"].startswith("Nataka")  # transcript passed through
    assert captured["tools"] == []                                # plain text gen


# ── save summary as a customer note keyed by phone ───────────────────────────

def test_save_call_note_appends_without_clobbering(monkeypatch):
    facts = []

    async def fake_add_fact(db, wa_id, fact, channel="whatsapp"):
        facts.append((wa_id, fact, channel))
        return [fact]

    monkeypatch.setattr(memory, "add_fact", fake_add_fact)
    user = User(wa_id="254700", phone="254700", state={"crm_notes": "Prefers black."})
    db = _FakeDB([_Res(one=user)])

    asyncio.run(ct._save_call_note(db, "254700", "Wants 2 cassocks; call back Fri."))

    notes = user.state["crm_notes"]
    assert "Prefers black." in notes                     # manual note preserved
    assert "Wants 2 cassocks" in notes                   # summary appended
    assert notes.index("Prefers black.") < notes.index("Wants 2 cassocks")
    assert db.commits >= 1
    assert facts and facts[0][0] == "254700" and "Wants 2 cassocks" in facts[0][1]


def test_save_call_note_creates_user_when_missing(monkeypatch):
    async def fake_add_fact(db, wa_id, fact, channel="whatsapp"):
        return [fact]

    monkeypatch.setattr(memory, "add_fact", fake_add_fact)
    db = _FakeDB([_Res(one=None)])

    asyncio.run(ct._save_call_note(db, "254711", "Bought a chalice."))
    assert db.added and isinstance(db.added[0], User)
    assert db.added[0].wa_id == "254711"
    assert "Bought a chalice." in (db.added[0].state or {}).get("crm_notes", "")
    assert db.flushes == 1


def test_save_call_note_ignores_blank(monkeypatch):
    monkeypatch.setattr(memory, "add_fact", lambda *a, **k: None)
    db = _FakeDB([])
    asyncio.run(ct._save_call_note(db, "254700", ""))   # no summary → no-op
    assert db.commits == 0


# ── scheduler ────────────────────────────────────────────────────────────────

def test_schedule_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "whisper_enabled", False, raising=False)
    ran = {"n": 0}

    async def fake_process(cid):
        ran["n"] += 1

    monkeypatch.setattr(ct, "_process", fake_process)
    ct.schedule_transcription("wacid.x")   # returns immediately, schedules nothing
    assert ran["n"] == 0


def test_schedule_runs_process_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "whisper_enabled", True, raising=False)
    ran = {}

    async def fake_process(cid):
        ran["cid"] = cid

    monkeypatch.setattr(ct, "_process", fake_process)

    async def go():
        ct.schedule_transcription("wacid.9")
        await asyncio.sleep(0.02)

    asyncio.run(go())
    assert ran.get("cid") == "wacid.9"
