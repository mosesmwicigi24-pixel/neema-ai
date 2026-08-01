"""The outcome self-check (services/selfcheck.py): best-effort subsystems fail
silently by design, so an hourly probe asserts their OUTCOMES actually landed.
Born from a real miss — three note-writers used MsgSender.agent (no such
member) for weeks and every swallowed AttributeError looked like quiet."""
import asyncio
import json

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.core.config import settings
from app.services import selfcheck as sc


class _KV:
    """In-memory stand-ins for app_settings.get_value/set_value."""
    def __init__(self, initial=""):
        self.stored = initial

    async def get(self, db, key):
        return self.stored

    async def set(self, db, key, value):
        self.stored = value


class _Redis:
    def __init__(self):
        self.published = []

    async def publish(self, ch, payload):
        self.published.append((ch, json.loads(payload)))

    async def zcount(self, *a):
        return 0


def _patch_kv(monkeypatch, kv):
    monkeypatch.setattr("app.services.app_settings.get_value", kv.get)
    monkeypatch.setattr("app.services.app_settings.set_value", kv.set)


def test_new_findings_notify_once_not_hourly(monkeypatch):
    """The same finding must not nag every hour — only a NEW one pings."""
    kv = _KV()
    _patch_kv(monkeypatch, kv)

    async def bad_probe(db, redis):
        return ["media dir not writable"]
    monkeypatch.setattr(sc, "PROBES", [("p", bad_probe)])

    r = _Redis()
    out1 = asyncio.run(sc.run_checks(None, r))
    assert out1 == ["media dir not writable"]
    assert len(r.published) == 1
    assert r.published[0][1]["type"] == "selfcheck"

    # Second run, same finding, findings persisted from run 1 → no new ping.
    out2 = asyncio.run(sc.run_checks(None, r))
    assert out2 == out1
    assert len(r.published) == 1


def test_a_crashing_probe_is_a_finding_not_a_silent_pass(monkeypatch):
    """The checker must not have the disease it cures."""
    kv = _KV()
    _patch_kv(monkeypatch, kv)

    async def boom(db, redis):
        raise RuntimeError("db gone")
    monkeypatch.setattr(sc, "PROBES", [("exploder", boom)])

    out = asyncio.run(sc.run_checks(None, None))
    assert len(out) == 1 and "exploder" in out[0] and "db gone" in out[0]


def test_healthy_run_clears_stored_findings(monkeypatch):
    kv = _KV(json.dumps({"at": "x", "findings": ["old problem"]}))
    _patch_kv(monkeypatch, kv)

    async def fine(db, redis):
        return []
    monkeypatch.setattr(sc, "PROBES", [("p", fine)])

    r = _Redis()
    assert asyncio.run(sc.run_checks(None, r)) == []
    assert r.published == []                       # nothing new to announce
    assert json.loads(kv.stored)["findings"] == []  # health line goes green


def test_health_line_reads_the_last_run(monkeypatch):
    kv = _KV(json.dumps({"at": "x", "findings": []}))
    _patch_kv(monkeypatch, kv)
    assert "all checks passing" in asyncio.run(sc.health_line(None))

    kv.stored = json.dumps({"at": "x", "findings": ["a", "b", "c", "d"]})
    line = asyncio.run(sc.health_line(None))
    assert line.startswith("🩺") and "a; b; c" in line and "d" not in line

    kv.stored = ""                                  # never ran → no line at all
    assert asyncio.run(sc.health_line(None)) == ""


def test_deferred_probe_counts_only_stale_entries(monkeypatch):
    class _R:
        async def zcount(self, key, lo, hi):
            from app.services.hub_events import DEFER_ZSET
            assert key == DEFER_ZSET
            return 3
    out = asyncio.run(sc._probe_deferred_events(None, _R()))
    assert out and "3 deferred hub event(s)" in out[0]
    assert asyncio.run(sc._probe_deferred_events(None, None)) == []


def test_stuck_actions_probe_respects_the_flag(monkeypatch):
    monkeypatch.setattr(settings, "agent_initiative", False, raising=False)
    assert asyncio.run(sc._probe_stuck_actions(None, None)) == []


def test_media_dir_probe_reports_the_fix(monkeypatch, tmp_path):
    # chmod can't make a dir unwritable for root (the test container's user),
    # so use a path whose PARENT is a file — open() fails for any user.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    monkeypatch.setattr("app.routers.media.MEDIA_DIR", str(blocker / "media"))
    out = asyncio.run(sc._probe_media_dir(None, None))
    assert out and "chown" in out[0]                # actionable, not just alarming

    monkeypatch.setattr("app.routers.media.MEDIA_DIR", str(tmp_path))
    assert asyncio.run(sc._probe_media_dir(None, None)) == []
