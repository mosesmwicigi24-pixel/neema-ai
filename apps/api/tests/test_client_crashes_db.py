"""App crash reports — the Android app sends what made it close, and the owner
can read it (owner, 2026-09-27: "Neema closed because this app has a bug" with
no way to say why). Real Postgres through the real admin routes; skips cleanly
without a database."""
import uuid

from tests import test_calls_db as _calls, test_security_db as _sec
from tests.test_security_db import _as

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark


def _report(**kw):
    r = {"id": str(uuid.uuid4()), "at": "2026-09-27T18:35:02Z", "kind": "crash", "thread": "main",
         "summary": "java.lang.IllegalArgumentException: Key \"c1\" was already used",
         "trace": "java.lang.IllegalArgumentException: Key \"c1\" was already used\n\tat a.b(SourceFile:12)",
         "app_version": "1.0.0", "build": "61", "device": "samsung SM-S918B", "sdk": 35}
    r.update(kw)
    return r


def test_a_crash_report_is_kept_and_the_owner_reads_it(env, world):
    rep = _report()
    assert env.client.post("/api/admin/client-crashes", json=rep, headers=_as(world["ann"])).json() == {"ok": True}
    rows = env.client.get("/api/admin/client-crashes", headers=_as(world["boss"])).json()
    got = next(r for r in rows if r["id"] == rep["id"])
    assert got["id"] == rep["id"] and got["kind"] == "crash" and got["build"] == "61"
    assert got["agent_name"] == "Ann Wanjiru" and got["sdk"] == 35
    assert "already used" in got["summary"] and "SourceFile:12" in got["trace"]


def test_the_same_report_sent_twice_is_kept_once(env, world):
    rep = _report()
    for _ in range(3):
        assert env.client.post("/api/admin/client-crashes", json=rep, headers=_as(world["ann"])).status_code == 200
    rows = env.client.get("/api/admin/client-crashes", headers=_as(world["boss"])).json()
    assert [r["id"] for r in rows].count(rep["id"]) == 1


def test_only_admins_read_reports_and_only_signed_in_apps_send_them(env, world):
    assert env.client.get("/api/admin/client-crashes", headers=_as(world["ann"])).status_code == 403
    assert env.client.post("/api/admin/client-crashes", json=_report()).status_code in (401, 403)


def test_odd_or_oversized_fields_never_break_the_report(env, world):
    rep = _report(kind="weird", sdk="35", trace="x" * 200_000, summary=None, thread=12)
    assert env.client.post("/api/admin/client-crashes", json=rep, headers=_as(world["ann"])).status_code == 200
    got = next(r for r in env.client.get("/api/admin/client-crashes", headers=_as(world["boss"])).json()
               if r["id"] == rep["id"])
    assert got["kind"] == "crash" and got["sdk"] == 0 and len(got["trace"]) == 60_000
    assert env.client.post("/api/admin/client-crashes", json={"kind": "crash"},
                           headers=_as(world["ann"])).status_code == 422
