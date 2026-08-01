"""The cross-channel limb: a window-closed Meta question continues on the same
person's open channel (usually WhatsApp) instead of waiting for a human flag.
Armando was reachable the whole time — the spine knew his WhatsApp."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.models.conversation import InterceptMode
from app.services import reply_sweeper as rs


def _conv(channel, ext, person="p1", last=None):
    return SimpleNamespace(
        id=f"{channel}-{ext}", person_id=person, channel=channel,
        wa_id=(ext if channel == "whatsapp" else None), external_id=ext,
        intercept_mode=InterceptMode.ai, last_message_at=last)


_MSG = SimpleNamespace(text="Do you have metal jugs?", media_type=None,
                       media_url=None, created_at=datetime.now(timezone.utc))


class _DB:
    def __init__(self, sibs):
        self.sibs, self.added, self.committed = sibs, [], False

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def execute(self, q):
        rows = self.sibs

        class _R:
            def scalars(s): return s
            def all(s): return rows
        return _R()

    def add(self, row): self.added.append(row)
    async def commit(self): self.committed = True


def _wire(monkeypatch, db, *, quiet=False, windows=None, compose="Bridged reply!"):
    monkeypatch.setattr(rs, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr("app.services.hub_events.is_quiet_hours", lambda now=None: quiet)

    async def fake_window(_db, conv):
        return {"mode": (windows or {}).get(conv.channel, "closed")}
    monkeypatch.setattr("app.services.conversation.messaging_window", fake_window)

    async def fake_compose(_db, _redis, dest, src_channel, question):
        assert "metal jugs" in question
        return compose
    monkeypatch.setattr(rs, "_compose_bridge", fake_compose)

    sent = []

    async def fake_send(_db, _redis, conv, text):
        sent.append((conv.channel, conv.wa_id or conv.external_id, text))
    monkeypatch.setattr("app.services.actions._send", fake_send)
    return sent


def test_window_closed_question_continues_on_open_whatsapp(monkeypatch):
    src = _conv("messenger", "PSID1")
    db = _DB([_conv("whatsapp", "254700111222")])
    sent = _wire(monkeypatch, db, windows={"whatsapp": "open"})

    out = asyncio.run(rs._try_continue_elsewhere(None, src, _MSG))
    assert out is True
    assert sent == [("whatsapp", "254700111222", "Bridged reply!")]
    # The source thread explains itself — and its latest message is now
    # outbound, so the sweep de-queues it.
    assert db.committed
    note = db.added[0]
    assert note.media_type == "note" and note.conversation_id == src.id
    assert "continued this" in note.text and "254700111222" in note.text


def test_whatsapp_wins_when_several_doors_are_open(monkeypatch):
    src = _conv("messenger", "PSID1")
    ig = _conv("instagram", "IG9", last=datetime.now(timezone.utc))
    wa = _conv("whatsapp", "254700111222")
    db = _DB([ig, wa])
    sent = _wire(monkeypatch, db, windows={"whatsapp": "open", "instagram": "open"})

    assert asyncio.run(rs._try_continue_elsewhere(None, src, _MSG)) is True
    assert sent[0][0] == "whatsapp"


def test_no_person_or_no_siblings_means_no_continuation(monkeypatch):
    assert asyncio.run(rs._try_continue_elsewhere(
        None, _conv("messenger", "PSID1", person=None), _MSG)) is False

    db = _DB([])
    sent = _wire(monkeypatch, db, windows={"whatsapp": "open"})
    assert asyncio.run(rs._try_continue_elsewhere(
        None, _conv("messenger", "PSID1"), _MSG)) is False
    assert sent == []


def test_quiet_hours_defer_rather_than_send_or_flag(monkeypatch):
    """A Neema-initiated send waits for morning — the row stays queued."""
    db = _DB([_conv("whatsapp", "254700111222")])
    sent = _wire(monkeypatch, db, quiet=True, windows={"whatsapp": "open"})
    out = asyncio.run(rs._try_continue_elsewhere(None, _conv("messenger", "P1"), _MSG))
    assert out == "deferred" and sent == []


def test_every_door_shut_falls_back_to_the_human_flag(monkeypatch):
    db = _DB([_conv("whatsapp", "254700111222")])
    sent = _wire(monkeypatch, db, windows={"whatsapp": "closed"})
    assert asyncio.run(rs._try_continue_elsewhere(None, _conv("messenger", "P1"), _MSG)) is False
    assert sent == []


def test_escalation_loop_prefers_continuation_over_the_flag(monkeypatch):
    src = _conv("messenger", "PSID1")
    rows = [(_MSG, src)]

    async def fake_unanswered(since, until, limit): return rows
    monkeypatch.setattr(rs, "_unanswered_dms", fake_unanswered)

    async def not_seen(cid, at): return False
    monkeypatch.setattr(rs, "_already_escalated_since", not_seen)

    async def fake_continue(redis, conv, msg): return True
    monkeypatch.setattr(rs, "_try_continue_elsewhere", fake_continue)

    flagged = []

    async def fake_escalate(channel, ext, note):
        flagged.append(ext)
        return True
    monkeypatch.setattr("app.agent.runtime.escalate_to_human", fake_escalate)

    n = asyncio.run(rs.escalate_window_closed(None))
    assert n == 1 and flagged == []          # continued, never flagged

    # Deferred rows do NOTHING this pass — no send, no flag, still queued.
    async def fake_defer(redis, conv, msg): return "deferred"
    monkeypatch.setattr(rs, "_try_continue_elsewhere", fake_defer)
    n = asyncio.run(rs.escalate_window_closed(None))
    assert n == 0 and flagged == []
