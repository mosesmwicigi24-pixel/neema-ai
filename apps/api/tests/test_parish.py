"""Parish accounts — the institution behind the individual.

Rev Grace, the secretary and the choir master are three contacts but ONE buyer.
Pinned here: name dedup (one row per church), safe attachment (a second church
never silently overwrites the first), the whole-system ripples — merge carries
the parish AND measurements, seasonal outreach sends one message per parish —
and the tool wiring on every channel.
"""
import asyncio
import types

import app.main  # noqa: F401 — registers models
import app.agent.tools as tools
from app.services import parish as ps
from app.models.parish import Parish
from app.models.person import Person


# ── one row per church ───────────────────────────────────────────────────────

def test_the_same_church_normalises_to_one_key():
    assert ps.normalise("St. Mary's Nakuru") == "st marys nakuru"
    assert ps.normalise("  st  MARYS   nakuru ") == "st marys nakuru"
    assert ps.normalise("Saint Marys Nakuru") == "st marys nakuru"   # saint → st
    assert ps.normalise(None) == ""


def test_noise_is_not_a_parish():
    for junk in ("", "ok", "yes", "hmm", "no"):
        assert ps.is_plausible_parish(junk) is False
    for real in ("St Mary's Nakuru", "Holy Family Basilica", "cathedral",
                 "ACK Emmanuel Church", "Deliverance Ministries"):
        assert ps.is_plausible_parish(real) is True


class _DB:
    def __init__(self, existing=None, person=None):
        self.existing, self.person = existing, person
        self.added, self.commits, self.flushes = [], 0, 0
    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalar_one_or_none=lambda: self.existing)
    async def get(self, model, pk):
        return self.person
    def add(self, o):
        self.added.append(o)
    async def flush(self):
        self.flushes += 1
    async def commit(self):
        self.commits += 1


def test_find_or_create_reuses_the_existing_row():
    existing = Parish(name="St Mary's Nakuru", norm="st marys nakuru")
    db = _DB(existing=existing)
    got = asyncio.run(ps.find_or_create(db, "Saint Marys Nakuru", location="Nakuru"))
    assert got is existing
    assert db.added == []                            # no duplicate row
    assert existing.location == "Nakuru"             # location backfilled, not clobbered


def test_find_or_create_creates_once_for_a_new_church():
    db = _DB(existing=None)
    got = asyncio.run(ps.find_or_create(db, "Holy  Family   Basilica"))
    assert got is db.added[0]
    assert got.name == "Holy Family Basilica"        # display form tidied
    assert got.norm == "holy family basilica"
    assert asyncio.run(ps.find_or_create(db, "ok")) is None   # noise → nothing


# ── attaching people ─────────────────────────────────────────────────────────

def test_attach_is_idempotent_but_never_silently_reassigns():
    parish = Parish(name="St Mary's", norm="st marys")
    parish.id = "PARISH-1"
    person = Person()
    person.parish_id = None

    db = _DB(existing=parish, person=person)
    assert asyncio.run(ps.attach_person(db, "P1", "St Marys")) is parish
    assert person.parish_id == "PARISH-1"
    # same church again → fine
    assert asyncio.run(ps.attach_person(db, "P1", "st marys")) is parish
    # a DIFFERENT church → refused (a human decides), affiliation unchanged
    other = Parish(name="Holy Trinity Parish", norm="holy trinity parish")
    other.id = "PARISH-2"
    db2 = _DB(existing=other, person=person)
    assert asyncio.run(ps.attach_person(db2, "P1", "Holy Trinity Parish")) is None
    assert person.parish_id == "PARISH-1"


# ── whole-system ripple: merge carries parish AND measurements ───────────────

def test_merge_source_carries_parish_and_measurements():
    import inspect
    from app.services import merge
    src = inspect.getsource(merge)
    assert "parish_id" in src                # institution follows the person
    assert '"measurements"' in src           # sizes survive a merge (gap fixed)


# ── whole-system ripple: one seasonal message per parish ─────────────────────

def test_seasonal_outreach_sends_one_message_per_parish():
    from app.jobs.seasonal_outreach import dedupe_by_parish
    rows = [
        {"wa_id": "A", "parish_id": "P1", "last_bought": "2025-12-01"},
        {"wa_id": "B", "parish_id": "P1", "last_bought": "2025-12-15"},   # most recent
        {"wa_id": "C", "parish_id": "P2", "last_bought": "2025-11-01"},
        {"wa_id": "D", "parish_id": None, "last_bought": "2025-10-01"},   # individual
    ]
    keep, dropped = dedupe_by_parish(rows)
    kept_ids = [r["wa_id"] for r in keep]
    assert "B" in kept_ids and "A" not in kept_ids   # most recent buyer speaks
    assert "C" in kept_ids                            # sole member passes
    assert "D" in kept_ids                            # no parish → individual
    assert [r["wa_id"] for r in dropped] == ["A"]
    # nobody vanishes
    assert len(keep) + len(dropped) == len(rows)


# ── the tool, on every channel ───────────────────────────────────────────────

def test_tool_is_registered_everywhere():
    from app.agent.runtime import MESSENGER_TOOLS
    assert "save_parish" in tools._HANDLERS
    assert any(t["name"] == "save_parish" for t in tools.TOOLS)
    assert "save_parish" in {t["name"] for t in MESSENGER_TOOLS}


def test_tool_attaches_and_banks_a_memory_fact(monkeypatch):
    captured = {}

    async def fake_person_id(ctx):
        return "P1"

    async def fake_attach(db, person_id, name, location=None):
        captured.update(person_id=person_id, name=name, location=location)
        p = Parish(name="St Mary's Nakuru", norm="st marys nakuru")
        return p

    async def fake_fact(db, wa_id, fact, channel="whatsapp"):
        captured["fact"] = fact
        return [fact]

    monkeypatch.setattr(tools, "_person_id_of", fake_person_id)
    monkeypatch.setattr(ps, "attach_person", fake_attach)
    monkeypatch.setattr(tools.memorymod, "add_fact", fake_fact)

    ctx = tools.ToolContext(db=object(), redis=None, wa_id="254700000001")
    out = asyncio.run(tools._save_parish(
        {"name": "St Mary's Nakuru", "location": "Nakuru"}, ctx))
    assert out["ok"] is True and out["parish"] == "St Mary's Nakuru"
    assert captured["person_id"] == "P1" and captured["location"] == "Nakuru"
    assert captured["fact"] == "church: St Mary's Nakuru"   # survives channels via memory


def test_tool_degrades_gracefully_without_a_person(monkeypatch):
    async def no_person(ctx):
        return None

    async def fake_fact(db, wa_id, fact, channel="whatsapp"):
        return [fact]

    monkeypatch.setattr(tools, "_person_id_of", no_person)
    monkeypatch.setattr(tools.memorymod, "add_fact", fake_fact)
    ctx = tools.ToolContext(db=object(), redis=None, wa_id="web_abc")
    out = asyncio.run(tools._save_parish({"name": "St Mary's Nakuru"}, ctx))
    assert out["ok"] is False and "memory" in out["note"]
    assert "error" in asyncio.run(tools._save_parish({}, ctx))
