"""Measurements on file — a returning customer is never measured twice.

Sizes live on the PERSON (same store as the cart), so figures taken on the website
form or on Messenger are the figures Neema already knows on WhatsApp.
"""
import asyncio
import types

import app.main  # noqa: F401 — registers models
import app.agent.measurements as mm
import app.agent.tools as tools
from app.models.person import Person
from app.models.user import User


class _DB:
    """Serves a User by wa_id and its Person by id; counts commits."""
    def __init__(self, user=None, person=None):
        self.user, self.person, self.commits = user, person, 0
    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalar_one_or_none=lambda: self.user)
    async def get(self, model, pk):
        return self.person
    async def commit(self):
        self.commits += 1


def _linked(person_state=None, user_state=None):
    person = Person(state=person_state or {})
    user = User(wa_id="254700000001", phone="254700000001", state=user_state or {})
    user.person_id = "P1"
    return _DB(user=user, person=person), person, user


# ── shape helpers ────────────────────────────────────────────────────────────

def test_visible_hides_bookkeeping_and_blanks():
    m = {"chest": "42in", "length": "", "_updated_at": "x", "_source": "chat", "sleeve": "24in"}
    assert mm.visible(m) == {"chest": "42in", "sleeve": "24in"}


def test_describe_reads_as_one_human_line():
    assert mm.describe({"chest": "42in", "head_size": "58cm", "_source": "chat"}) == \
        "chest 42in · head size 58cm"
    assert mm.describe({}) == "" and mm.describe(None) == ""


# ── saving ───────────────────────────────────────────────────────────────────

def test_saves_onto_the_person_so_every_channel_sees_them():
    db, person, user = _linked()
    saved = asyncio.run(mm.save_measurements(db, "254700000001", {"Chest": " 42in "}))
    assert saved["chest"] == "42in"                       # normalised label + trimmed
    assert person.state["measurements"]["chest"] == "42in"   # on the PERSON
    assert "measurements" not in (user.state or {})          # not stranded on the user row
    assert saved["_source"] == "chat" and saved["_updated_at"]
    assert db.commits >= 1


def test_a_correction_never_wipes_the_rest():
    db, person, _ = _linked(person_state={"measurements": {
        "chest": "42in", "length": "58in", "sleeve": "24in"}})
    saved = asyncio.run(mm.save_measurements(db, "254700000001", {"chest": "44in"}))
    assert saved["chest"] == "44in"          # corrected
    assert saved["length"] == "58in"         # kept
    assert saved["sleeve"] == "24in"         # kept


def test_multi_word_labels_and_empty_input():
    db, person, _ = _linked()
    asyncio.run(mm.save_measurements(db, "254700000001", {"Head Size": "58cm", "waist": ""}))
    assert person.state["measurements"]["head_size"] == "58cm"
    assert "waist" not in person.state["measurements"]      # blanks are dropped
    # nothing usable → no write, no crash
    before = dict(person.state["measurements"])
    asyncio.run(mm.save_measurements(db, "254700000001", {}))
    assert person.state["measurements"] == before


def test_unresolvable_contact_is_a_noop_not_a_crash():
    db = _DB(user=None, person=None)
    assert asyncio.run(mm.save_measurements(db, "unknown", {"chest": "42in"})) == {}


def test_reading_back_what_was_saved():
    db, _, _ = _linked(person_state={"measurements": {"chest": "42in", "_source": "website form"}})
    got = asyncio.run(mm.get_measurements(db, "254700000001"))
    assert got["chest"] == "42in"
    assert mm.describe(got) == "chest 42in"


# ── the tool Neema calls ─────────────────────────────────────────────────────

def test_tool_saves_and_tells_the_model_not_to_re_ask(monkeypatch):
    captured = {}

    async def fake_save(db, key, fields, channel="whatsapp", source="chat"):
        captured.update(key=key, fields=fields, channel=channel, source=source)
        return {**fields, "_source": source, "_updated_at": "now"}

    monkeypatch.setattr(mm, "save_measurements", fake_save)
    ctx = tools.ToolContext(db=object(), redis=None, wa_id="PSID1", channel="messenger")
    out = asyncio.run(tools._save_measurements({"measurements": {"chest": "42in"}}, ctx))

    assert out["ok"] is True
    assert out["measurements"] == {"chest": "42in"}       # bookkeeping keys stripped
    assert "same measurements as last time" in out["note"]
    assert captured["channel"] == "messenger" and captured["source"] == "chat"


def test_tool_rejects_a_bad_payload():
    ctx = tools.ToolContext(db=object(), redis=None, wa_id="X", channel="whatsapp")
    assert "error" in asyncio.run(tools._save_measurements({}, ctx))
    assert "error" in asyncio.run(tools._save_measurements({"measurements": "42in"}, ctx))


def test_tool_is_registered_everywhere_it_is_needed():
    from app.agent.runtime import MESSENGER_TOOLS
    assert "save_measurements" in tools._HANDLERS
    assert any(t["name"] == "save_measurements" for t in tools.TOOLS)
    # made-to-order sells on Messenger/IG too
    assert "save_measurements" in {t["name"] for t in MESSENGER_TOOLS}


# ── the CRM surfaces them ────────────────────────────────────────────────────

def test_crm_exposes_sizes_from_whichever_store_holds_them():
    from app.routers.crm import _measurements_of
    person = {"measurements": {"chest": "42in", "_source": "chat"}}
    assert _measurements_of(person, None) == {"chest": "42in"}
    assert _measurements_of(None, {"measurements": {"length": "58in"}}) == {"length": "58in"}
    assert _measurements_of(None, {}) == {}
