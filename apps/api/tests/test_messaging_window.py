"""Messaging windows: what a human may actually send, and saying so up front.

The live symptom: two Messenger threads flagged "the 24-hour window has closed",
a composer that gave no hint, and a send that Meta would refuse — while Meta in
fact allows a HUMAN AGENT seven days.
"""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.services import conversation as cs
from app.services import meta_send as ms


def _conv(channel="messenger"):
    return types.SimpleNamespace(id="c1", channel=channel,
                                 external_id="PSID1", wa_id=None)


def _db_with_inbound_at(ts):
    async def _latest(db, conv_id):
        return types.SimpleNamespace(created_at=ts) if ts else None
    return _latest


def _window(channel, age, monkeypatch):
    ts = None if age is None else datetime.now(timezone.utc) - age
    monkeypatch.setattr(cs, "_latest_inbound", _db_with_inbound_at(ts))
    return asyncio.run(cs.messaging_window(None, _conv(channel)))


def test_inside_24h_is_open(monkeypatch):
    w = _window("messenger", timedelta(hours=3), monkeypatch)
    assert w["mode"] == "open"


def test_messenger_past_24h_is_human_agent_once_meta_approves(monkeypatch):
    """The whole point: a person can still answer Armando on day 2 — once the
    app holds Meta's Human Agent approval (App Review)."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_human_agent_approved", True, raising=False)
    w = _window("messenger", timedelta(hours=30), monkeypatch)
    assert w["mode"] == "human_agent"
    assert "human agent" in w["reason"].lower()


def test_without_approval_the_banner_stops_promising(monkeypatch):
    """Live toast, 2026-08-19: "(#100) Cannot tag messages with 'HUMAN_AGENT'
    without prior approval" — while the banner above the composer read "you
    can still reply as a human agent". Until the flag says Meta approved, the
    window is honestly CLOSED, and the reason says exactly why."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_human_agent_approved", False, raising=False)
    w = _window("messenger", timedelta(hours=30), monkeypatch)
    assert w["mode"] == "closed"
    assert "approv" in w["reason"].lower() and "App Review" in w["reason"]
    # the countdown survives for the day approval lands
    assert w["human_agent_until"]


def test_the_health_line_names_app_review_not_the_token():
    from app.services.agent_health import describe
    line = describe({"kind": "meta", "count": 3, "error":
                     "Meta send message failed (400): (#100) Cannot tag messages "
                     "with 'HUMAN_AGENT' without prior approval."})
    assert "App Review" in line and "Human Agent" in line
    assert "page token itself is fine" in line


def test_messenger_past_seven_days_is_closed(monkeypatch):
    assert _window("messenger", timedelta(days=8), monkeypatch)["mode"] == "closed"


def test_whatsapp_has_no_human_agent_extension(monkeypatch):
    """WhatsApp offers no 7-day tag — outside 24h it's a template or nothing."""
    assert _window("whatsapp", timedelta(hours=30), monkeypatch)["mode"] == "closed"
    assert _window("whatsapp", timedelta(hours=3), monkeypatch)["mode"] == "open"


def test_comment_threads_have_no_window(monkeypatch):
    assert _window("facebook", timedelta(days=30), monkeypatch)["mode"] == "n/a"


def test_never_messaged_is_closed(monkeypatch):
    w = _window("messenger", None, monkeypatch)
    assert w["mode"] == "closed" and w["last_inbound_at"] is None


def test_human_agent_tag_is_on_the_wire(monkeypatch):
    """The tag is what Meta actually checks — pin the payload shape."""
    sent = {}

    async def fake_post(path, body, what, page_id=None):
        sent.update(body)
        return {}
    monkeypatch.setattr(ms, "_graph_post", fake_post)

    asyncio.run(ms.send_meta_message("PSID1", "hello", human_agent=True))
    assert sent["messaging_type"] == "MESSAGE_TAG"
    assert sent["tag"] == "HUMAN_AGENT"

    sent.clear()
    asyncio.run(ms.send_meta_message("PSID1", "hello"))
    assert sent["messaging_type"] == "RESPONSE"
    assert "tag" not in sent          # never tag a normal in-window reply
