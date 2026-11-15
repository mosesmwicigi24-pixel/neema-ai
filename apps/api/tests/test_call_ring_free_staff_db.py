"""RING ONLY FREE STAFF (owner, 2026-11-15: "ring all free staff at once,
skipping only the busy ones"). A second call does not ring whoever is already
on a call; when everyone is on a call it rings everyone. Real Postgres through
the real webhook and admin routes; skips without one."""
import asyncio
import json

from tests import test_calls_db as _calls, test_security_db as _sec
from tests.test_calls_db import _ring
from tests.test_security_db import _as

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark


def _answer(env, cid, who):
    r = env.client.post(f"/api/admin/calls/{cid}/answer", json={"sdp": "v=0 a"}, headers=_as(who))
    assert r.status_code == 200, r.text


def test_a_second_call_skips_whoever_is_on_a_call(env, world):
    from app.services import call_log
    _ring(env, "wacid.free1", frm="254700111001")
    first = env.redis.events("incoming_call")[-1]
    assert "skip_agents" not in first                      # nobody is busy: everyone rings
    _answer(env, "wacid.free1", world["ann"])
    assert asyncio.run(call_log.busy_agents()) == {world["ann"]}

    _ring(env, "wacid.free2", frm="254700111002")
    second = env.redis.events("incoming_call")[-1]
    assert second["call_id"] == "wacid.free2" and second["skip_agents"] == [world["ann"]]
    frame = json.dumps(second)
    assert call_log.frame_is_for(frame, world["ann"]) is False
    assert call_log.frame_is_for(frame, world["ben"]) is True and call_log.frame_is_for(frame, world["boss"])
    # what follows the ring still reaches everyone
    assert call_log.frame_is_for(json.dumps({"type": "call_ended", "skip_agents": [world["ann"]]}), world["ann"])


def test_when_everyone_is_on_a_call_everyone_rings(env, world):
    for n, who in enumerate(("ann", "ben", "boss")):
        _ring(env, f"wacid.all{n}", frm=f"25470022200{n}")
        _answer(env, f"wacid.all{n}", world[who])
    _ring(env, "wacid.all9", frm="254700222009")
    assert "skip_agents" not in env.redis.events("incoming_call")[-1]


def test_hanging_up_frees_them_and_the_switch_turns_it_off(env, world, monkeypatch):
    from app.core.config import settings
    from app.services import call_log
    _ring(env, "wacid.sw1", frm="254700333001")
    _answer(env, "wacid.sw1", world["ben"])
    monkeypatch.setattr(settings, "call_ring_skip_busy", False, raising=False)
    _ring(env, "wacid.sw2", frm="254700333002")
    assert "skip_agents" not in env.redis.events("incoming_call")[-1]
    monkeypatch.setattr(settings, "call_ring_skip_busy", True, raising=False)
    r = env.client.post("/api/admin/calls/wacid.sw1/terminate", json={}, headers=_as(world["ben"]))
    assert r.status_code == 200
    assert world["ben"] not in asyncio.run(call_log.busy_agents())


def test_placing_a_call_makes_you_busy_and_pushes_skip_the_busy(env, world):
    from app.services import call_log, push
    asyncio.run(call_log.upsert_outbound("wacid.out1", "254700444001", agent_id=world["ann"], name="G"))
    assert world["ann"] in asyncio.run(call_log.busy_agents())
    import inspect
    src = inspect.getsource(push.send_call_event)
    assert 'event.get("skip_agents") if event.get("type") == "incoming_call"' in src
    assert "str(a) not in skip" in inspect.getsource(push._tokens)


def test_a_frame_that_cannot_be_read_is_delivered():
    from app.services import call_log
    assert call_log.frame_is_for("not json", "x")
    assert call_log.frame_is_for('{"type":"incoming_call","skip_agents":"oops"', "x")
    assert call_log.frame_is_for('{"type":"message"}', "x")
