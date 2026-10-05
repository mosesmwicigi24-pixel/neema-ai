"""Cycle 8 — failure recovery and the backfill, on a real Postgres with real
(extensionless, like production) audio files.

Recovery (services/transcript_recovery.sweep): restart-orphaned queued /
processing notes and calls · two sweepers at once · provider outage → bounded,
spaced retries · poison files never retried · budget refusals retried when the
day rolls over · Redis down · old work left to the backfill · duplicate work.

Backfill (python -m app.scripts.backfill_transcripts): dry run writes nothing
and estimates · execute transcribes notes AND calls · extensionless files ·
stops before the cap and leaves the rest untouched · idempotent rerun · old
notes never wake the agent nor rewrite a newer inbox preview · refuses when
transcription is off.
"""
import json
import os
import shutil
import types
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from tests import test_voice_notes_db as vn
from tests.test_security_db import fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = vn.pytestmark
rig, clips = vn.rig, vn.clips
run = vn.run

WA = "254744000001"
NOW = datetime.now(timezone.utc)


def _conv(rig, wa=WA, preview="[audio received]"):
    from app.models.conversation import Conversation

    async def go():
        async with rig.maker() as db:
            c = Conversation(id=uuid.uuid4(), wa_id=wa, channel="whatsapp", external_id=wa,
                             last_message_preview=preview)
            db.add(c)
            await db.commit()
            return c.id
    return run(go())


def _note(rig, clip, *, status=None, minutes_ago=30, wa=WA, conv=None, text="[audio received]", name=None):
    """An inbound voice-note row whose audio sits in the media dir WITHOUT an
    extension (how every note was saved before 2026-10-05)."""
    from app.models.message import Message, MsgDirection, MsgSender
    fname = name or f"wa_{uuid.uuid4().hex[:12]}"
    shutil.copy(clip, os.path.join(rig.media_dir, fname))
    mid = uuid.uuid4()

    async def go():
        async with rig.maker() as db:
            db.add(Message(id=mid, channel="whatsapp", wa_id=wa, external_id=wa, conversation_id=conv,
                           direction=MsgDirection.inbound, sender=MsgSender.user, text=text,
                           media_type="audio", media_url=f"https://neema.test/api/admin/media/{fname}",
                           transcript_status=status,
                           created_at=NOW - timedelta(minutes=minutes_ago)))
            await db.commit()
    run(go())
    return mid


def _call(rig, cid, clip, *, status="queued", ended_minutes_ago=30, wa=WA, summary=None):
    from app.models.call import Call
    fname = f"call_{uuid.uuid4().hex[:10]}.webm"
    shutil.copy(clip, os.path.join(rig.media_dir, fname))

    async def go():
        async with rig.maker() as db:
            at = NOW - timedelta(minutes=ended_minutes_ago)
            db.add(Call(call_id=cid, wa_id=wa, status="completed", duration=20, started_at=at - timedelta(seconds=20),
                        ended_at=at, recording_url=f"https://neema.test/api/admin/media/{fname}",
                        transcript_status=status, summary=summary))
            await db.commit()
    run(go())


async def _msg(rig, mid):
    from app.models.message import Message
    async with rig.maker() as db:
        return await db.get(Message, mid)


def _setup(rig):
    from app.services import call_transcribe as ct

    async def no_publish(cid):
        return None
    rig.monkeypatch.setattr(ct, "_publish_update", no_publish)
    rig.monkeypatch.setattr(ct, "_redis", lambda: rig.redis)
    rig.llm.answers["calls"] = json.dumps({"summary": "Wants a red cope.", "next_action": "Send photos"})
    rig.provider.answers = [("Nataka kapa nyekundu.", "sw")]


def sweep(rig, now=None, redis="rig"):
    from app.services import transcript_recovery as tr
    return run(tr.sweep(rig.redis if redis == "rig" else redis, now=now or NOW))


# ═════════════════════════════════════════════════════════════════════════════
# Recovery
# ═════════════════════════════════════════════════════════════════════════════

def test_restart_orphaned_notes_are_heard_fresh_ones_left_alone(rig, clips):
    _setup(rig)
    old_q = _note(rig, clips[0], status="queued", minutes_ago=20)
    old_p = _note(rig, clips[1], status="processing", minutes_ago=40)
    fresh_q = _note(rig, clips[2], status="queued", minutes_ago=2)
    fresh_p = _note(rig, clips[3], status="processing", minutes_ago=5)
    out = sweep(rig)
    assert out["notes"] == 2
    a, b = run(_msg(rig, old_q)), run(_msg(rig, old_p))
    assert (a.transcript_status, b.transcript_status) == ("done", "done")
    assert a.text == "Nataka kapa nyekundu." and a.transcript_lang == "sw"
    assert run(_msg(rig, fresh_q)).transcript_status == "queued"        # may still be in flight
    assert run(_msg(rig, fresh_p)).transcript_status == "processing"
    assert len(rig.provider.calls) == 2
    # the decoded file was the extensionless original
    assert all(os.path.basename(p) == "audio.mp3" for p in rig.provider.calls)


def test_two_sweepers_at_once_transcribe_each_note_once(rig, clips):
    import asyncio
    from app.services import transcript_recovery as tr
    _setup(rig)
    rig.provider.delay = 0.3
    ids = [_note(rig, clips[i], status="processing", minutes_ago=30 + i) for i in range(3)]

    async def both():
        return await asyncio.gather(tr.sweep(rig.redis, now=NOW), tr.sweep(rig.redis, now=NOW))
    run(both())
    assert [run(_msg(rig, i)).transcript_status for i in ids] == ["done"] * 3
    assert len(rig.provider.calls) == 3


def test_provider_outage_is_retried_spaced_and_bounded(rig, clips):
    from app.services import transcript_recovery as tr
    _setup(rig)
    rig.provider.answers = [TimeoutError("down")]
    mid = _note(rig, clips[4], status="failed:provider_timeout", minutes_ago=30)
    t = NOW
    tries = 0
    for step in range(12):                       # an outage lasting most of a day
        before = len(rig.provider.calls)
        sweep(rig, now=t)
        if len(rig.provider.calls) > before:
            tries += 1
        t += timedelta(minutes=30)
    # each sweep retry = 1 engine run (+ its own in-request retries)
    assert tries == tr.MAX_RETRIES
    assert run(_msg(rig, mid)).transcript_status == "failed:provider_timeout"
    # immediately after a retry, the next sweep waits (spacing)
    mid2 = _note(rig, clips[5], status="failed:provider_busy", minutes_ago=30)
    sweep(rig, now=NOW)
    n = len(rig.provider.calls)
    sweep(rig, now=NOW + timedelta(minutes=1))
    assert len(rig.provider.calls) == n
    # provider back: the next due retry succeeds
    rig.provider.answers = [("Back again.", "en")]
    sweep(rig, now=NOW + timedelta(minutes=11))
    assert run(_msg(rig, mid2)).transcript_status == "done"


def test_poison_files_are_never_retried(rig, clips, tmp_path):
    _setup(rig)
    junk = tmp_path / "junk"
    junk.write_bytes(b"\x00not audio at all" * 200)
    stuck_junk = _note(rig, str(junk), status="queued", minutes_ago=30)
    failed = _note(rig, clips[6], status="failed:corrupt", minutes_ago=30)
    too_long = _note(rig, clips[7], status="failed:too_long", minutes_ago=30)
    sweep(rig)
    assert run(_msg(rig, stuck_junk)).transcript_status == "failed:corrupt"
    for i in range(3):
        sweep(rig, now=NOW + timedelta(hours=i + 1))
    assert run(_msg(rig, stuck_junk)).transcript_status == "failed:corrupt"
    assert run(_msg(rig, failed)).transcript_status == "failed:corrupt"
    assert run(_msg(rig, too_long)).transcript_status == "failed:too_long"
    assert rig.provider.calls == []                                     # nothing sent, ever


def test_budget_refusal_waits_for_the_day_to_roll_over(rig, clips):
    from app.services import transcribe as stt
    _setup(rig)
    mid = _note(rig, clips[8], status="failed:over_budget", minutes_ago=30)
    rig.redis.kv[stt._spend_key()] = str(rig.settings.transcribe_daily_cap_usd)   # today: spent
    sweep(rig)
    assert run(_msg(rig, mid)).transcript_status == "failed:over_budget" and rig.provider.calls == []
    rig.redis.kv.pop(stt._spend_key())                                  # a new UTC day: nothing spent
    sweep(rig)
    assert run(_msg(rig, mid)).transcript_status == "done"


def test_redis_down_recovers_stuck_notes_but_never_retries_failures(rig, clips):
    _setup(rig)
    stuck = _note(rig, clips[9], status="queued", minutes_ago=30)
    failed = _note(rig, clips[0], status="failed:provider_error", minutes_ago=30, name="wa_other")
    sweep(rig, redis=None)
    assert run(_msg(rig, stuck)).transcript_status == "done"
    assert run(_msg(rig, failed)).transcript_status == "failed:provider_error"


def test_orphaned_and_failed_calls_get_their_brief_once(rig, clips):
    from app.services import transcript_recovery as tr
    _setup(rig)
    _call(rig, "wacid.r8.q", clips["call"], status="queued", ended_minutes_ago=20)
    _call(rig, "wacid.r8.p", clips["call"], status="processing", ended_minutes_ago=120)
    _call(rig, "wacid.r8.fresh", clips["call"], status="processing", ended_minutes_ago=10)
    _call(rig, "wacid.r8.f", clips["call"], status="failed:provider_busy", ended_minutes_ago=30)
    _call(rig, "wacid.r8.done", clips["call"], status="done", summary="Already briefed.")
    out = sweep(rig)
    assert out["calls"] == 3
    rows = {c: run(vn.call_row(rig, c)) for c in ("wacid.r8.q", "wacid.r8.p", "wacid.r8.fresh",
                                                     "wacid.r8.f", "wacid.r8.done")}
    assert [rows[c].transcript_status for c in ("wacid.r8.q", "wacid.r8.p", "wacid.r8.f")] == ["done"] * 3
    assert rows["wacid.r8.q"].summary == "Wants a red cope."
    assert rows["wacid.r8.fresh"].transcript_status == "processing"
    assert rows["wacid.r8.done"].summary == "Already briefed."
    # the same audio (one recording copied) was paid for once — the engine's cache
    assert len(rig.provider.calls) == 1
    # one CRM note per call, even when swept again
    sweep(rig, now=NOW + timedelta(hours=2))
    from app.models.user import User

    async def notes():
        async with rig.maker() as db:
            u = (await db.execute(sa.select(User).where(User.wa_id == WA))).scalar_one()
            return u.state
    st = run(notes())
    # two hours on, the once-fresh call is stale too and gets its brief; the
    # three already briefed are not noted again
    assert sorted(st["call_note_ids"]) == ["wacid.r8.f", "wacid.r8.fresh", "wacid.r8.p", "wacid.r8.q"]
    assert st["crm_notes"].count("\U0001F4DE Call (") == 4
    assert tr.CALL_STUCK_MIN >= 60


def test_old_work_is_left_to_the_backfill(rig, clips):
    _setup(rig)
    old = _note(rig, clips[1], status="queued", minutes_ago=5 * 24 * 60)
    sweep(rig)
    assert run(_msg(rig, old)).transcript_status == "queued" and rig.provider.calls == []


def test_sweeper_is_a_no_op_while_transcription_is_off(rig, clips):
    _setup(rig)
    rig.monkeypatch.setattr(rig.settings, "whisper_enabled", False)
    mid = _note(rig, clips[2], status="queued", minutes_ago=30)
    assert sweep(rig) == {"notes": 0, "calls": 0, "skipped": 0}
    assert run(_msg(rig, mid)).transcript_status == "queued"


# ═════════════════════════════════════════════════════════════════════════════
# Backfill command
# ═════════════════════════════════════════════════════════════════════════════

def _args(**kw):
    from app.scripts.backfill_transcripts import parse_since
    d = dict(execute=False, since=parse_since("30d"), kind="all", limit=500, max_usd=None)
    d.update(kw)
    return types.SimpleNamespace(**d)


def _backfill(rig, **kw):
    from app.scripts import backfill_transcripts as bf
    lines = []
    rep = run(bf.run(_args(**kw), redis=rig.redis, out=lines.append))
    return rep, lines


def _pre_fix_world(rig, clips):
    """What production holds: pre-fix notes (no status, placeholder text,
    extensionless files), an n8n-era transcribed note, a poison note, a note
    whose file is gone, a recorded call, and a newer message in the chat."""
    conv = _conv(rig, preview="[image received]")
    ids = {
        "a": _note(rig, clips[0], minutes_ago=3 * 24 * 60, conv=conv),
        "b": _note(rig, clips[1], minutes_ago=2 * 24 * 60, conv=conv, text=""),
        "c": _note(rig, clips[2], status="failed:no_provider", minutes_ago=24 * 60, conv=conv),
        "n8n": _note(rig, clips[3], minutes_ago=24 * 60, conv=conv, text="Habari, bei ya stole?"),
        "poison": _note(rig, clips[4], status="failed:corrupt", minutes_ago=24 * 60, conv=conv),
        "old": _note(rig, clips[5], minutes_ago=40 * 24 * 60, conv=conv),
    }
    gone = _note(rig, clips[6], minutes_ago=24 * 60, conv=conv)

    async def drop_file():
        m = await _msg(rig, gone)
        os.remove(os.path.join(rig.media_dir, m.media_url.rsplit("/", 1)[-1]))
    run(drop_file())
    ids["gone"] = gone
    _call(rig, "wacid.bf.1", clips["call"], status="recorded", ended_minutes_ago=2 * 24 * 60)
    # a later message in the chat: the inbox preview must stay its own
    from app.models.message import Message, MsgDirection, MsgSender

    async def later():
        async with rig.maker() as db:
            db.add(Message(id=uuid.uuid4(), channel="whatsapp", wa_id=WA, external_id=WA, conversation_id=conv,
                           direction=MsgDirection.inbound, sender=MsgSender.user, text="[image received]",
                           media_type="image", created_at=NOW - timedelta(minutes=5)))
            await db.commit()
    run(later())
    return conv, ids


def test_backfill_dry_run_writes_nothing_and_estimates(rig, clips):
    _setup(rig)
    conv, ids = _pre_fix_world(rig, clips)
    rep, lines = _backfill(rig)
    assert (rep["notes"], rep["calls"], rep["missing"]) == (3, 1, 1)
    # 3 notes × 3 s + a 20 s call ≈ 0.48 min at $0.006/min
    assert 0.4 < rep["minutes"] < 0.6 and rep["estimate_usd"] < 0.01
    assert any("dry run — nothing written" in x for x in lines)
    assert any("missing: note" in x for x in lines)
    assert rig.provider.calls == [] and rig.llm.calls == []
    assert run(_msg(rig, ids["a"])).transcript_status is None
    assert run(vn.call_row(rig, "wacid.bf.1")).transcript_status == "recorded"


def test_backfill_execute_transcribes_extensionless_notes_and_calls_idempotently(rig, clips):
    _setup(rig)
    conv, ids = _pre_fix_world(rig, clips)
    rep, lines = _backfill(rig, execute=True)
    assert rep["done"] == 4 and rep["results"] == {"done": 4}
    for k in ("a", "b", "c"):
        m = run(_msg(rig, ids[k]))
        assert m.transcript_status == "done" and m.text == "Nataka kapa nyekundu.", k
        assert m.translated_text and m.transcript_lang == "sw"
    assert run(_msg(rig, ids["n8n"])).text == "Habari, bei ya stole?"            # left alone
    assert run(_msg(rig, ids["poison"])).transcript_status == "failed:corrupt"
    assert run(_msg(rig, ids["old"])).transcript_status is None                 # outside --since
    assert run(_msg(rig, ids["gone"])).transcript_status is None                # missing file: not written
    c = run(vn.call_row(rig, "wacid.bf.1"))
    assert c.transcript_status == "done" and c.summary == "Wants a red cope."
    # old notes never wake the agent; the newer "[image received]" preview stays
    assert rig.turns == []

    async def preview():
        from app.models.conversation import Conversation
        async with rig.maker() as db:
            return (await db.get(Conversation, conv)).last_message_preview
    assert run(preview()) == "[image received]"
    # a rerun finds nothing left to do
    rep2, _ = _backfill(rig, execute=True)
    assert rep2["notes"] == 0 and rep2["calls"] == 0 and rep2["done"] == 0


def test_backfill_stops_before_the_cap_and_leaves_the_rest_untouched(rig, clips):
    _setup(rig)
    conv, ids = _pre_fix_world(rig, clips)
    # each 3 s note ≈ $0.0003; allow one and a half
    rep, lines = _backfill(rig, execute=True, kind="notes", max_usd=0.00045)
    assert rep["done"] == 1 and rep["stopped_at_cap"] is True
    statuses = sorted(str(run(_msg(rig, ids[k])).transcript_status) for k in ("a", "b", "c"))
    # newest first: "c" ran; "a" and "b" are untouched — never marked over_budget
    assert run(_msg(rig, ids["c"])).transcript_status == "done"
    assert statuses == ["None", "None", "done"]
    assert any("rerun to continue" in x for x in lines)


def test_backfill_refuses_when_transcription_is_off(rig, clips):
    _setup(rig)
    _pre_fix_world(rig, clips)
    rig.monkeypatch.setattr(rig.settings, "whisper_enabled", False)
    rep, lines = _backfill(rig, execute=True)
    assert rep.get("error") == "disabled" and rep["done"] == 0
    assert rig.provider.calls == []


def test_backfill_cli_requires_a_mode():
    import pytest
    from app.scripts import backfill_transcripts as bf
    with pytest.raises(SystemExit):
        bf.main([])
    with pytest.raises(SystemExit):
        bf.main(["--dry-run", "--execute"])


def test_an_old_note_heard_late_never_rewrites_a_newer_preview(rig, clips):
    """voice_notes._store set the inbox preview whenever it was a placeholder —
    so a recovered or backfilled OLD note replaced "[image received]" from a
    later message with words from days ago."""
    from app.services import voice_notes
    from app.models.conversation import Conversation
    from app.models.message import Message, MsgDirection, MsgSender
    _setup(rig)
    conv = _conv(rig, preview="[image received]")
    old = _note(rig, clips[7], minutes_ago=2 * 24 * 60, conv=conv)

    async def later():
        async with rig.maker() as db:
            db.add(Message(id=uuid.uuid4(), channel="whatsapp", wa_id=WA, external_id=WA, conversation_id=conv,
                           direction=MsgDirection.inbound, sender=MsgSender.user, text="[image received]",
                           media_type="image", created_at=NOW - timedelta(minutes=5)))
            await db.commit()
    run(later())
    assert run(voice_notes.interpret(old, redis=rig.redis)) == "done"

    async def preview():
        async with rig.maker() as db:
            return (await db.get(Conversation, conv)).last_message_preview
    assert run(preview()) == "[image received]"
    # …while the LATEST note still lights the preview with its words
    conv2 = _conv(rig, wa="254744000002")
    new = _note(rig, clips[8], minutes_ago=1, conv=conv2, wa="254744000002")
    assert run(voice_notes.interpret(new, redis=rig.redis)) == "done"

    async def preview2():
        async with rig.maker() as db:
            return (await db.get(Conversation, conv2)).last_message_preview
    assert run(preview2()) == "🎤 Nataka kapa nyekundu."


def test_a_late_failure_never_overwrites_heard_words(rig, clips):
    """Second adversarial pass: a recovery run racing a slow original (or a
    twin that gave up waiting, `failed:busy`) must not turn a done note or a
    briefed call back into a failure."""
    from app.services import call_transcribe as ct, transcribe as stt, voice_notes
    _setup(rig)
    mid = _note(rig, clips[9], status="done", text="Nataka kapa nyekundu.", minutes_ago=30)
    assert run(voice_notes._store(mid, stt.failed("busy"), None, None, None, rig.redis)) == "done"
    m = run(_msg(rig, mid))
    assert m.transcript_status == "done" and m.text == "Nataka kapa nyekundu."
    _call(rig, "wacid.r8.race", clips["call"], status="done", summary="Wants a red cope.")
    run(ct._set_status("wacid.r8.race", "failed:busy"))
    assert run(vn.call_row(rig, "wacid.r8.race")).transcript_status == "done"


def test_backfill_cli_end_to_end_dry_run_and_execute_guard(rig, clips, capsys):
    """The real entry point: --dry-run works without redis; --execute refuses
    without it (the daily budget couldn't be counted)."""
    from app.scripts import backfill_transcripts as bf
    _setup(rig)
    _pre_fix_world(rig, clips)
    rig.monkeypatch.setattr(rig.settings, "redis_url", "redis://127.0.0.1:1/0")
    assert bf.main(["--dry-run", "--since", "30d"]) == 0
    out = capsys.readouterr().out
    assert "backfill: 3 voice notes + 1 call recordings since 30d" in out and "dry run" in out
    assert bf.main(["--execute"]) == 2
    assert "refusing to --execute" in capsys.readouterr().out
    assert rig.provider.calls == []
