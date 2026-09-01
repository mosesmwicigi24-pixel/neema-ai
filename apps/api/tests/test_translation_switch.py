"""A person must be able to stop the reading glass — and start it again.

Translation buys tokens on every foreign message. Before this, the only way to
stop it was `TRANSLATE_FOR_TEAM` in the box's .env plus a restart, which is not
something the owner can do at 9pm when the bill looks wrong. The switch now
lives in the database, with the environment value as its default, and Settings
carries the control.

Two properties matter more than the plumbing: OFF must actually stop the spend
in BOTH directions, and a settings failure must never decide the question by
accident — it falls back to the environment, never to silence.
"""
import asyncio
import pytest

import app.services.translate as tx
from app.core.config import settings
from app.services import app_settings as aps


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


class _Row:
    def __init__(self, value):
        self.value, self.updated_by = value, None


class _Res:
    def __init__(self, one=None):
        self._one = one
    def scalar_one_or_none(self):
        return self._one


class _DB:
    """A settings table with exactly one row in it (or none)."""
    def __init__(self, row=None):
        self.row, self.added, self.committed = row, [], False
    async def execute(self, *a, **k):
        return _Res(self.row)
    def add(self, obj):
        self.added.append(obj)
    async def commit(self):
        self.committed = True


# ── reading the switch ───────────────────────────────────────────────────────

def test_with_nothing_stored_the_environment_decides(monkeypatch):
    for env in (True, False):
        monkeypatch.setattr(settings, "translate_for_team", env, raising=False)
        assert asyncio.run(aps.get_translate_enabled(_DB(None), _Redis())) is env


@pytest.mark.parametrize("stored,expected", [("off", False), ("on", True)])
def test_the_stored_switch_overrides_the_environment(stored, expected, monkeypatch):
    # The env says the opposite of the stored value in both rows — whoever
    # touched the switch last is the one who meant it.
    monkeypatch.setattr(settings, "translate_for_team", not expected, raising=False)
    assert asyncio.run(aps.get_translate_enabled(_DB(_Row(stored)), _Redis())) is expected


def test_a_cached_answer_needs_no_database(monkeypatch):
    class _NoDB:
        async def execute(self, *a, **k):
            raise AssertionError("the cache should have answered")
    assert asyncio.run(aps.get_translate_enabled(_NoDB(), _Redis({"app:translate_enabled": "off"}))) is False
    assert asyncio.run(aps.get_translate_enabled(_NoDB(), _Redis({"app:translate_enabled": "on"}))) is True


def test_reading_it_warms_the_cache():
    r = _Redis()
    asyncio.run(aps.get_translate_enabled(_DB(_Row("off")), r))
    assert r.store["app:translate_enabled"] == "off"


def test_a_broken_database_falls_back_to_the_environment_not_to_silence(monkeypatch):
    class _Boom:
        async def execute(self, *a, **k):
            raise RuntimeError("db down")
    monkeypatch.setattr(settings, "translate_for_team", True, raising=False)
    assert asyncio.run(aps.get_translate_enabled(_Boom(), _Redis())) is True
    monkeypatch.setattr(settings, "translate_for_team", False, raising=False)
    assert asyncio.run(aps.get_translate_enabled(_Boom(), _Redis())) is False


def test_a_junk_value_in_the_row_is_not_trusted(monkeypatch):
    monkeypatch.setattr(settings, "translate_for_team", True, raising=False)
    assert asyncio.run(aps.get_translate_enabled(_DB(_Row("maybe")), _Redis())) is True


# ── flipping it ──────────────────────────────────────────────────────────────

def test_turning_it_off_takes_effect_immediately_not_in_five_minutes():
    # The cache is written with the row: an operator who kills this during a
    # spend scare means NOW, not at the end of the TTL.
    r, db = _Redis(), _DB(_Row("on"))
    assert asyncio.run(aps.set_translate_enabled(db, r, False)) is False
    assert db.committed and r.store["app:translate_enabled"] == "off"
    assert db.row.value == "off"


def test_the_first_flip_creates_the_row():
    db = _DB(None)
    asyncio.run(aps.set_translate_enabled(db, _Redis(), False))
    assert db.added and db.added[0].value == "off"


# ── what OFF actually stops ──────────────────────────────────────────────────

def test_off_stops_the_incoming_direction_before_a_single_token(monkeypatch):
    from app.agent import runtime
    monkeypatch.setattr(runtime, "build_llm",
                        lambda model=None: (_ for _ in ()).throw(
                            AssertionError("no model call when the switch is off")))
    r = _Redis({"app:translate_enabled": "off"})
    assert asyncio.run(tx._translate_thread(r, "conv", ["m1"])) == 0
    # …and it never even took the per-thread lock.
    assert "translate:lock:conv" not in r.store


def test_off_sends_the_humans_reply_through_untouched(monkeypatch):
    from app.agent import runtime
    monkeypatch.setattr(runtime, "build_llm",
                        lambda model=None: (_ for _ in ()).throw(
                            AssertionError("no model call when the switch is off")))
    out = asyncio.run(tx.translate_reply(None, _Redis({"app:translate_enabled": "off"}),
                                         "conv", "Thank you — the tray is $70."))
    assert out == {"text": "Thank you — the tray is $70.", "lang": None}


def test_on_lets_the_worker_past_the_switch(monkeypatch):
    # Proves the guard is a switch and not a wall: with it ON the worker gets
    # as far as its own lock/cooldown machinery.
    seen = {}

    class _R(_Redis):
        async def set(self, k, v, **kw):
            seen[k] = v
            return await super().set(k, v, **kw)
    r = _R({"app:translate_enabled": "on"})

    class _Sess:
        async def __aenter__(self):
            raise RuntimeError("far enough — the switch let us through")
        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _Sess())
    assert asyncio.run(tx._translate_thread(r, "conv", ["m1"])) == 0
    assert "translate:lock:conv" in seen


def test_the_scheduler_no_longer_reads_the_environment(monkeypatch):
    # The switch moved to the DB; the sync scheduler must not second-guess it
    # (it has no session to read it with). Empty input is still a no-op.
    monkeypatch.setattr(settings, "translate_for_team", False, raising=False)
    assert tx.schedule_thread_translation(_Redis(), "conv", []) is False

    started = []

    class _Task:                       # SimpleNamespace defines __eq__, so it
        def add_done_callback(self, _):  # is unhashable — and _tasks is a set.
            pass

    def _fake_create_task(coro, *a, **k):
        coro.close()                   # never awaited; don't warn about it
        started.append(1)
        return _Task()

    monkeypatch.setattr(tx.asyncio, "create_task", _fake_create_task)
    assert tx.schedule_thread_translation(_Redis(), "conv", ["m1"]) is True
    assert started == [1]
