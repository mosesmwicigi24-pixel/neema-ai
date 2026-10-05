"""Cycle 7 — calls & audio performance, MEASURED (real Postgres, real ffmpeg,
the provider faked at realistic latencies). Each test prints a `[measure]`
line (run with -s to see them) and asserts a budget with headroom, so a
regression fails here rather than in a customer's chat.

  1. webhook ack for a voice note while the provider takes 3 s
  2. voice note → the agent's resolved turn, provider at 1 / 2 / 4 s
  3. ffmpeg normalise cost by audio length (10 s … 30 min)
  4. 10 voice notes at once: wall time, peak provider concurrency
  5. a burst must not starve the shared thread pool (everything else in the
     app that uses asyncio.to_thread waits behind blocked provider calls)
  6. the thread endpoint with 50 call cards + 120 voice notes: query count
     and time
"""
import asyncio
import os
import subprocess
import tempfile
import threading
import time
import types
import uuid

import sqlalchemy as sa

from tests import test_call_cards_db as cards
from tests import test_voice_notes_db as vn
from tests.test_security_db import _as, fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = vn.pytestmark
rig, clips = vn.rig, vn.clips
run = vn.run
env = cards.env


def _gen(path, secs, freq=440):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={secs}", "-c:a", "libopus", "-b:a", "24k",
                    "-f", "ogg", path], check=True)


# 1 ──────────────────────────────────────────────────────────────────────────
def test_webhook_ack_never_waits_for_the_provider(rig, clips):
    rig.provider.answers = [("Habari, nataka stole moja ya kijani.", "sw")]
    rig.provider.delay = 3.0
    ack = run(vn.whatsapp_voice(rig, "254733000001", "wamid.p1", clips[0]))
    print(f"\n[measure] webhook ack with a 3 s provider: {ack:.0f} ms")
    assert ack < 1000


# 2 ──────────────────────────────────────────────────────────────────────────
def test_voice_note_to_agent_turn_latency(rig, clips):
    """Debounce is 1 s in the rig (production: WHATSAPP_DEBOUNCE_SECONDS=30,
    which then dominates — a note's words are in long before the window
    closes)."""
    from app.services import wa_native
    out = {}
    for i, delay in enumerate((1.0, 2.0, 4.0)):
        rig.provider.answers = [(f"Nataka kasoki {i + 2}.", "sw")]
        rig.provider.delay = delay
        rig.turns.clear()
        wa = f"25473300010{i}"
        vn.serve_clip(rig, clips[i + 1])
        t0 = time.perf_counter()

        async def go():
            await wa_native.handle_webhook(vn.wa_payload(wa, f"wamid.p2.{i}"), rig.redis)
            for _ in range(400):
                if rig.turns:
                    return time.perf_counter() - t0
                await asyncio.sleep(0.02)
            raise AssertionError("no turn")
        took = run(go())
        run(vn.drain_tasks())
        assert "🎤 (voice note): Nataka kasoki" in rig.turns[0]["text"], rig.turns
        out[delay] = took
    print("\n[measure] voice note → agent turn (debounce 1 s): "
          + " · ".join(f"provider {d:.0f}s → {t:.2f}s" for d, t in out.items()))
    for d, t in out.items():
        # max(debounce, provider) + translation + DB + the 0.25 s poll
        assert t < max(1.0, d) + 1.5, out


# 3 ──────────────────────────────────────────────────────────────────────────
def test_ffmpeg_normalise_cost_by_length(tmp_path):
    from app.services import transcribe as stt
    rows = []
    for secs in (10, 60, 300, 1800):
        src = str(tmp_path / f"a{secs}")            # extensionless, like production notes
        _gen(src, secs)
        with tempfile.TemporaryDirectory() as d:
            t = time.perf_counter()
            dur, peak = run(stt.normalise(src, os.path.join(d, "o.mp3"), 3600))
            ms = (time.perf_counter() - t) * 1000
            out_kb = os.path.getsize(os.path.join(d, "o.mp3")) / 1024
        rows.append((secs, os.path.getsize(src) / 1024, ms, out_kb))
        assert abs(dur - secs) < 1.0
    print("\n[measure] ffmpeg normalise: " + " · ".join(
        f"{s}s audio ({kb:.0f} KB in → {ok:.0f} KB out) {ms:.0f} ms" for s, kb, ms, ok in rows))
    # a 30-minute call decodes well inside its timeout (max(60, 3600/10) s)
    assert rows[-1][2] < 60_000
    # roughly linear: per-second cost of a long file ≤ 3× the short one's
    assert rows[-1][2] / 1800 <= 3 * max(rows[0][2] / 10, 1)


# 4 + 5 ──────────────────────────────────────────────────────────────────────
def _burst(rig, clips, n, delay, probe=False, pool=None):
    """n voice notes transcribed at once (the engine directly). Returns
    (wall_s, peak_concurrent_provider_calls, probe_wait_ms)."""
    from app.services import transcribe as stt
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def provider(path, prov, model):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        time.sleep(delay)
        with lock:
            live["now"] -= 1
        return ("Nataka stole.", "sw")
    rig.monkeypatch.setattr(stt, "call_provider", provider)
    files = []
    d = tempfile.mkdtemp()
    for i in range(n):
        p = os.path.join(d, f"wa_burst{i}")
        _gen(p, 3, freq=300 + 37 * i)                 # distinct bytes → no cache hits
        files.append(p)

    async def go():
        if pool:
            import concurrent.futures
            asyncio.get_running_loop().set_default_executor(concurrent.futures.ThreadPoolExecutor(pool))
        t0 = time.perf_counter()
        tasks = [asyncio.create_task(stt.transcribe_file(p, redis=rig.redis)) for p in files]
        wait_ms = None
        if probe:
            await asyncio.sleep(delay / 2)            # the burst is in the providers now
            t = time.perf_counter()
            await asyncio.to_thread(lambda: None)     # any other to_thread user in the app
            wait_ms = (time.perf_counter() - t) * 1000
        res = await asyncio.gather(*tasks)
        assert all(r.status == "done" for r in res), [r.status for r in res]
        return time.perf_counter() - t0, wait_ms
    wall, wait_ms = run(go())
    return wall, live["peak"], wait_ms


def test_ten_voice_notes_at_once(rig, clips):
    from app.core.config import settings
    limit = getattr(settings, "transcribe_concurrency", None)
    wall, peak, _ = _burst(rig, clips, 10, 2.0)
    print(f"\n[measure] 10 notes at once, provider 2 s: wall {wall:.2f}s · peak provider calls {peak}"
          f" (limit {limit})")
    assert limit and peak <= limit
    # waves of `limit`: ceil(10/limit) × 2 s + decode
    assert wall < -(-10 // limit) * 2.0 + 3.0


def test_a_burst_never_starves_the_shared_thread_pool(rig, clips):
    """Provider calls are blocking HTTP run via asyncio.to_thread. Unbounded,
    a burst bigger than the default executor (min(32, cpu+4) threads — 8 on a
    small VPS) parks every other to_thread caller in the app behind requests
    that may each take up to 90 s."""
    n = 40
    wall, peak, wait_ms = _burst(rig, clips, n, 1.0, probe=True, pool=8)
    print(f"\n[measure] {n}-note burst on an 8-thread pool: another to_thread caller waited "
          f"{wait_ms:.0f} ms · peak provider calls {peak} · wall {wall:.1f}s")
    assert wait_ms < 500


def test_a_voice_note_never_queues_behind_long_calls(rig, clips):
    """Four hour-long recordings land at once (provider 3 s each, standing in
    for minutes); a voice note arriving with them is heard in ~one provider
    round, not after every call."""
    from app.services import transcribe as stt
    def provider(path, prov, model):
        time.sleep(3.0)
        return ("Agent: hello. Customer: I want a cope.", "en")
    rig.monkeypatch.setattr(stt, "call_provider", provider)
    d = tempfile.mkdtemp()
    calls = []
    for i in range(4):
        p = os.path.join(d, f"call{i}.webm")
        _gen(p, 20, freq=500 + 11 * i)
        calls.append(p)
    note = os.path.join(d, "wa_note")
    _gen(note, 3, freq=1700)

    async def go():
        t0 = time.perf_counter()
        ct = [asyncio.create_task(stt.transcribe_file(p, kind="call", redis=rig.redis)) for p in calls]
        await asyncio.sleep(0.05)
        r = await stt.transcribe_file(note, kind="voice_note", redis=rig.redis)
        note_s = time.perf_counter() - t0
        await asyncio.gather(*ct)
        return r, note_s, time.perf_counter() - t0
    r, note_s, all_s = run(go())
    print(f"\n[measure] voice note beside 4 long calls: heard after {note_s:.2f}s (all calls done {all_s:.2f}s)")
    assert r.status == "done"
    assert note_s < 4.5, note_s


def test_a_turn_waiting_for_a_note_polls_gently(rig):
    """A turn whose voice note is still being transcribed polls the row until
    it is in (bounded by WAIT_SECONDS). Measured: queries spent waiting 6 s."""
    from app.services import voice_notes
    from app.models.message import Message, MsgDirection, MsgSender
    import app.database as database
    mid = uuid.uuid4()

    async def seed():
        async with rig.maker() as db:
            db.add(Message(id=mid, channel="whatsapp", wa_id="254733000777", external_id="254733000777",
                           direction=MsgDirection.inbound, sender=MsgSender.user, text="[audio received]",
                           media_type="audio", media_url="x", transcript_status="processing"))
            await db.commit()
    run(seed())
    counter = types.SimpleNamespace(n=0)
    engine = database.AsyncSessionLocal.kw["bind"]

    def before(*a):
        counter.n += 1
    sa.event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        t = time.perf_counter()
        line = run(voice_notes.resolve(voice_notes.token(mid), channel="whatsapp", key="254733000777",
                                       wait_seconds=6))
        took = time.perf_counter() - t
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", before)
    print(f"\n[measure] a turn waiting 6 s for a note: {counter.n} queries ({took:.1f}s)")
    assert "still being transcribed" in line
    assert counter.n <= 15, counter.n


# 6 ──────────────────────────────────────────────────────────────────────────
def test_thread_endpoint_query_count_with_many_cards_and_notes(env):
    for i in range(55):
        cards._call(env, f"wacid.q{i}", status="completed" if i % 2 else "missed",
                    agent="ann" if i % 2 else None, duration=60 if i % 2 else None,
                    minutes_ago=10 + i, recording="r.webm" if i % 3 == 0 else None,
                    transcript_status="done" if i % 3 == 0 else "none",
                    summary="Wants a cope." if i % 3 == 0 else None,
                    insights={"prices": ["KES 9,000"], "next_action": "Send photo"} if i % 3 == 0 else None)
    eng = sa.create_engine(env.db_url)
    with eng.begin() as c:
        for i in range(120):
            c.execute(sa.text(
                "INSERT INTO messages (id, wa_id, channel, external_id, conversation_id, direction, sender, "
                "text, media_type, media_url, transcript_status, transcript_lang, translated_text, "
                "translated_from, created_at) VALUES (:id, :wa, 'whatsapp', :wa, :c, 'inbound', 'user', "
                ":t, 'audio', 'https://x/api/admin/media/wa_n', :ts, 'sw', 'I want a cope', 'Swahili', "
                "NOW() - make_interval(mins => :m))"),
                {"id": str(uuid.uuid4()), "wa": cards.WA, "c": env.ids["conv"], "t": "Nataka kapa",
                 "ts": ("done", "queued", "failed:over_budget", "silent")[i % 4], "m": i})
    eng.dispose()

    import app.database as database
    counter = types.SimpleNamespace(n=0)
    engine = database.AsyncSessionLocal.kw["bind"]

    def before(conn, cursor, statement, params, context, executemany):
        counter.n += 1
    sa.event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        url = f"/api/admin/conversations/{env.ids['conv']}/messages"
        env.client.get(url, headers=_as(env.ids["ann"]))          # warm
        counter.n = 0
        t = time.perf_counter()
        r = env.client.get(url, headers=_as(env.ids["ann"]))
        ms = (time.perf_counter() - t) * 1000
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", before)
    assert r.status_code == 200
    items = r.json()
    n_calls = sum(1 for i in items if i.get("event_kind") == "call")
    n_voice = sum(1 for i in items if i.get("media_type") == "audio")
    print(f"\n[measure] thread: {len(items)} items ({n_calls} call cards, {n_voice} voice notes) · "
          f"{counter.n} queries · {ms:.0f} ms · {len(r.content) / 1024:.0f} KB")
    assert n_calls == 50
    assert counter.n <= 25, counter.n          # constant, never per item
