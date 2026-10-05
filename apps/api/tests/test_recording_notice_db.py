"""The written recording / transcription notice (owner decision — wording
awaits the owner's approval, so it ships OFF): one short line, once per
customer, the first time one of their calls connects while recording is on;
only inside Meta's 24 h customer-service window; idempotent under replayed
webhooks and simultaneous calls. Off = nothing sent, nothing written.

Real Postgres; skips cleanly without one.
"""
import asyncio
import uuid

import pytest
import sqlalchemy as sa

from tests.test_security_db import _reachable, _sync_url, fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = pytest.mark.skipif(
    not _sync_url() or not _reachable(_sync_url()),
    reason="needs a reachable Postgres (CI migrations job / Docker harness)")

WA = "254700888001"
PSID = "7123456789012345"
TEXT = "Calls with Bethany House may be recorded and transcribed so we can serve you better."


@pytest.fixture
def rig(fresh_db, monkeypatch):  # noqa: F811
    import types
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as database
    from app.core.config import settings
    from app.services import call_log, meta_send, n8n_bridge, recording_notice

    async_url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    maker = async_sessionmaker(create_async_engine(async_url, poolclass=NullPool),
                               class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)
    monkeypatch.setattr(call_log, "AsyncSessionLocal", maker)
    monkeypatch.setattr(settings, "call_recording_enabled", True)
    monkeypatch.setattr(settings, "call_recording_notice_text", TEXT)

    sent = []

    async def fake_waba(wa_id, text, context_wamid=None):
        if rig_ns.fail:
            raise RuntimeError("WABA error 400: (#131047) Re-engagement message")
        sent.append(("whatsapp", wa_id, text))
        return f"wamid.N{len(sent)}"

    async def fake_meta(recipient, text, page_id=None, human_agent=False, tag=None):
        assert not human_agent and not tag            # automated: the plain RESPONSE window only
        sent.append(("messenger", recipient, text))

    async def no_page(channel, ext):
        return None

    monkeypatch.setattr(n8n_bridge, "_send_waba", fake_waba)
    monkeypatch.setattr(meta_send, "send_meta_message", fake_meta)
    monkeypatch.setattr(meta_send, "page_of_contact", no_page)

    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE recording_notices, calls, messages, conversations, users, persons CASCADE"))
    rig_ns = types.SimpleNamespace(db_url=fresh_db, eng=eng, sent=sent, fail=False,
                                   settings=settings, notice=recording_notice, call_log=call_log)
    yield rig_ns
    eng.dispose()


def _enable(rig, on=True):
    rig.settings.call_recording_notice_enabled = on


@pytest.fixture(autouse=True)
def _restore_flag():
    from app.core.config import settings
    before = settings.call_recording_notice_enabled
    yield
    settings.call_recording_notice_enabled = before


def _inbound_message(rig, *, hours_ago=1, channel="whatsapp", conv=True):
    with rig.eng.begin() as c:
        cid = str(uuid.uuid4())
        if conv:
            c.execute(sa.text(
                "INSERT INTO conversations (id, wa_id, channel, external_id, intercept_mode, status, "
                "created_at, updated_at) VALUES (:id, :wa, :ch, :ext, 'ai', 'open', NOW(), NOW())"),
                {"id": cid, "wa": WA if channel == "whatsapp" else None, "ch": channel,
                 "ext": WA if channel == "whatsapp" else PSID})
        c.execute(sa.text(
            "INSERT INTO messages (id, wa_id, channel, external_id, conversation_id, direction, sender, "
            "text, created_at) VALUES (:id, :wa, :ch, :ext, :c, 'inbound', 'user', 'hi', "
            "NOW() - make_interval(hours => :h))"),
            {"id": str(uuid.uuid4()), "wa": WA if channel == "whatsapp" else None, "ch": channel,
             "ext": WA if channel == "whatsapp" else PSID, "c": cid if conv else None, "h": hours_ago})


def _ringing(rig, call_id, *, direction="inbound", channel="whatsapp", hours_ago=0):
    with rig.eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO calls (id, call_id, wa_id, channel, external_id, direction, status, started_at, "
            "transcript_status) "
            "VALUES (:id, :cid, :wa, :ch, :ext, :dir, 'ringing', NOW() - make_interval(hours => :h), 'none')"),
            {"id": str(uuid.uuid4()), "cid": call_id, "wa": WA if channel == "whatsapp" else None,
             "ch": channel, "ext": PSID if channel == "messenger" else None, "dir": direction,
             "h": hours_ago})


def _answer(rig, *call_ids):
    """Answer each call the real way (call_log.mark_answered), then let the
    answer path's background work finish."""
    async def go():
        for cid in call_ids:
            await rig.call_log.mark_answered(cid, None, None)
        while rig.notice._bg_tasks:
            await asyncio.gather(*list(rig.notice._bg_tasks))
    asyncio.run(go())


def _claims(rig):
    with rig.eng.connect() as c:
        return c.execute(sa.text("SELECT channel, recipient, call_id FROM recording_notices")).fetchall()


def _thread_notices(rig):
    with rig.eng.connect() as c:
        return c.execute(sa.text("SELECT count(*) FROM messages WHERE direction = 'outbound' "
                                 "AND text = :t"), {"t": TEXT}).scalar_one()


def test_off_by_default_nothing_is_sent_or_written(rig):
    from app.core.config import Settings
    assert Settings.model_fields["call_recording_notice_enabled"].default is False
    _enable(rig, False)
    _inbound_message(rig)
    _ringing(rig, "wacid.OFF")
    async def go():
        await rig.call_log.mark_answered("wacid.OFF", None, None)
        assert not rig.notice._bg_tasks                    # no task is even created
        return await rig.notice.send_for_call("wacid.OFF")
    assert asyncio.run(go()) == rig.notice.DISABLED
    assert rig.sent == [] and _claims(rig) == [] and _thread_notices(rig) == 0
    with rig.eng.connect() as c:                            # the answer itself is unchanged
        assert c.execute(sa.text("SELECT status FROM calls WHERE call_id = 'wacid.OFF'")).scalar_one() == "answered"


def test_enabled_it_goes_once_per_customer_never_on_every_call(rig):
    _enable(rig)
    _inbound_message(rig)
    _ringing(rig, "wacid.A1")
    _answer(rig, "wacid.A1")
    assert rig.sent == [("whatsapp", WA, TEXT)]
    assert _claims(rig) == [("whatsapp", WA, "wacid.A1")]
    assert _thread_notices(rig) == 1                        # the team sees what was said
    _ringing(rig, "wacid.A2", direction="outbound")
    _answer(rig, "wacid.A2")
    assert len(rig.sent) == 1                                # the second call: nothing new
    assert asyncio.run(rig.notice.send_for_call("wacid.A2")) == rig.notice.ALREADY


def test_an_inbound_call_opens_the_window_on_its_own(rig):
    """A customer who calls without ever writing: their call is inside the
    24 h window (Meta: an inbound call opens it), so the notice can go."""
    _enable(rig)
    _ringing(rig, "wacid.CALLER")
    _answer(rig, "wacid.CALLER")
    assert rig.sent == [("whatsapp", WA, TEXT)]


def test_outside_the_24h_window_it_is_skipped_logged_and_not_claimed(rig, caplog):
    import logging
    _enable(rig)
    _inbound_message(rig, hours_ago=30)
    _ringing(rig, "wacid.OUT1", direction="outbound")
    with caplog.at_level(logging.INFO, logger="neema.calls"):
        _answer(rig, "wacid.OUT1")
    assert rig.sent == [] and _claims(rig) == []
    assert any("outside the 24 h window" in r.getMessage() for r in caplog.records)
    # they write again → the next connected call carries it
    _inbound_message(rig, hours_ago=0, conv=False)
    _ringing(rig, "wacid.OUT2", direction="outbound")
    _answer(rig, "wacid.OUT2")
    assert rig.sent == [("whatsapp", WA, TEXT)]


def test_replayed_webhooks_and_simultaneous_calls_send_one_notice(rig):
    _enable(rig)
    _inbound_message(rig)
    _ringing(rig, "wacid.D1")
    _answer(rig, "wacid.D1", "wacid.D1", "wacid.D1")         # Meta replays the answer
    assert len(rig.sent) == 1
    # two of their calls connect at the same instant, before any claim exists
    with rig.eng.begin() as c:
        c.execute(sa.text("TRUNCATE recording_notices"))
    rig.sent.clear()
    _ringing(rig, "wacid.S1")
    _ringing(rig, "wacid.S2")

    async def both():
        return await asyncio.gather(rig.notice.send_for_call("wacid.S1"),
                                    rig.notice.send_for_call("wacid.S2"))
    outcomes = asyncio.run(both())
    assert sorted(outcomes) == sorted([rig.notice.SENT, rig.notice.ALREADY])
    assert len(rig.sent) == 1 and len(_claims(rig)) == 1


def test_a_failed_send_gives_the_claim_back_for_a_later_call(rig):
    _enable(rig)
    _inbound_message(rig)
    _ringing(rig, "wacid.F1")
    rig.fail = True
    assert asyncio.run(rig.notice.send_for_call("wacid.F1")) == rig.notice.FAILED
    assert rig.sent == [] and _claims(rig) == [] and _thread_notices(rig) == 0
    rig.fail = False
    _ringing(rig, "wacid.F2")
    _answer(rig, "wacid.F2")
    assert rig.sent == [("whatsapp", WA, TEXT)]


def test_no_recording_no_notice(rig):
    _enable(rig)
    rig.settings.call_recording_enabled = False
    _inbound_message(rig)
    _ringing(rig, "wacid.NOREC")
    assert asyncio.run(rig.notice.send_for_call("wacid.NOREC")) == rig.notice.RECORDING_OFF
    assert rig.sent == []


def test_messenger_inside_its_window_once_outside_skipped(rig):
    _enable(rig)
    _ringing(rig, "mcall.NOCONV", channel="messenger")
    assert asyncio.run(rig.notice.send_for_call("mcall.NOCONV")) == rig.notice.OUTSIDE_WINDOW
    _inbound_message(rig, channel="messenger")
    _ringing(rig, "mcall.M1", channel="messenger")
    _answer(rig, "mcall.M1")
    assert rig.sent == [("messenger", PSID, TEXT)]
    assert _claims(rig) == [("messenger", PSID, "mcall.M1")]
