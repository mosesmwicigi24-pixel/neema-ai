"""Three ways Neema went silent on a customer who was still talking.

Reported from the live inbox:
  · WhatsApp — a colleague answered once, and the AI never spoke again.
  · A comment asking "How to order" got "Message us on WhatsApp" instead of an
    answer, on a post that was performing well.

The causes were separate, and all three end in the same place — a customer left
without a reply:

  1. INTERCEPT WAS A ONE-WAY DOOR. Only a manual Release (or a full conversation
     wipe) could return a thread to `ai`; no time-based release existed anywhere.
  2. AN UNREADABLE ATTACHMENT MUTED HER. Any inbound media that wasn't a photo or
     voice note auto-switched the thread to human mode — so a customer sending a
     VIDEO of the item they wanted silenced the AI permanently.
  3. THE PER-POST AGENT CAP ANSWERED WITH A PITCH. Past 30 agent replies on a
     post, the comment path stopped running the agent and fell back to a canned
     WhatsApp line — so the better a post performed, the worse it was answered.
"""
import asyncio
import types
from datetime import datetime, timedelta, timezone

# Full ORM registry so Conversation's relationships resolve.
import app.models.agent, app.models.message, app.models.intercept  # noqa: F401
import app.models.person, app.models.user  # noqa: F401

import app.agent.runtime as rt
from app.core.config import settings
from app.models.conversation import Conversation, InterceptMode
from app.models.intercept import InterceptAction
from app.services import auto_release


# ── 1. a quiet human-held thread comes back to the AI ────────────────────────

class _FakeDB:
    """Serves the conversation list, then the 'last human touch' scalar."""
    def __init__(self, convs, last_touch):
        self._convs, self._last_touch = convs, last_touch
        self.added, self.committed = [], False
        self._call = 0

    async def execute(self, *a, **k):
        self._call += 1
        if self._call == 1:
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(all=lambda: self._convs))
        return types.SimpleNamespace(scalar_one_or_none=lambda: self._last_touch)

    def add(self, obj): self.added.append(obj)
    async def commit(self): self.committed = True
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


def _run_sweep(monkeypatch, conv, last_touch, minutes=45):
    monkeypatch.setattr(settings, "auto_release_minutes", minutes, raising=False)
    db = _FakeDB([conv], last_touch)
    monkeypatch.setattr(auto_release, "AsyncSessionLocal", lambda: db, raising=False)
    import app.database
    monkeypatch.setattr(app.database, "AsyncSessionLocal", lambda: db, raising=False)
    return asyncio.run(auto_release.sweep_auto_release(None)), db


def _held_conv():
    c = Conversation(wa_id="254712345678", channel="whatsapp", external_id="254712345678")
    c.intercept_mode = InterceptMode.human
    c.intercept_since = datetime.now(timezone.utc) - timedelta(hours=3)
    c.assigned_agent_id = None
    return c


def test_quiet_thread_is_released_back_to_ai(monkeypatch):
    conv = _held_conv()
    stale = datetime.now(timezone.utc) - timedelta(minutes=90)   # colleague long gone
    n, db = _run_sweep(monkeypatch, conv, stale)
    assert n == 1
    assert conv.intercept_mode == InterceptMode.ai      # Neema can answer again
    assert conv.assigned_agent_id is None and conv.intercept_since is None
    # …and the handover is visible, not mysterious
    assert db.added[0].action == InterceptAction.release
    assert "no agent reply for 45 minutes" in db.added[0].note


def test_active_colleague_is_left_alone(monkeypatch):
    """Someone replying right now must not have the thread taken off them."""
    conv = _held_conv()
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    n, db = _run_sweep(monkeypatch, conv, recent)
    assert n == 0
    assert conv.intercept_mode == InterceptMode.human
    assert db.added == []


def test_abandoned_intercept_with_no_reply_is_released(monkeypatch):
    """Taken over, then never spoken in — falls back to intercept_since."""
    conv = _held_conv()                                  # intercepted 3h ago
    n, _ = _run_sweep(monkeypatch, conv, None)           # no human message ever
    assert n == 1 and conv.intercept_mode == InterceptMode.ai


def test_sweep_can_be_disabled(monkeypatch):
    conv = _held_conv()
    n, _ = _run_sweep(monkeypatch, conv, None, minutes=0)
    assert n == 0 and conv.intercept_mode == InterceptMode.human


# ── 2. an attachment she can't open must not mute her ────────────────────────

def test_prompt_tells_her_what_to_do_with_an_unreadable_attachment():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(country_iso="KE", currency="KES")
    assert "AN ATTACHMENT YOU CANNOT OPEN" in p
    assert "send a\n  PHOTO" in p or "PHOTO" in p
    assert "never say \"nobody can help\"" in p


def test_media_escalation_no_longer_switches_to_human_mode():
    """The source of the mute: media handling must write a FLAG, not an intercept."""
    import inspect
    from app.services import n8n_bridge
    src = inspect.getsource(n8n_bridge.upsert_message)
    # the flag is written…
    assert "InterceptAction.flag" in src
    # …and the line that muted the AI is gone
    assert "conv.intercept_mode  = InterceptMode.human" not in src
    assert "stays in AI mode" in src or "LEAVE THE THREAD IN AI MODE" in src


# ── 3. a buying comment gets an answer, not a pitch ──────────────────────────

def test_over_cap_buying_comment_gets_the_product_link():
    """'How to order' with no agent answer (over cap) → the product page."""
    out = rt._comment_public_reply(
        "", dm_sent=False, link="https://neema.example/api/o/ABC", name_tag=" Johnny",
        seed="johnny",
        product_link="https://bethanyhouse.co.ke/product/aluminium-tray?ref=AB12CD")
    assert "bethanyhouse.co.ke/product/aluminium-tray?ref=AB12CD" in out
    assert "Johnny" in out
    # the canned line that actually went out is gone
    assert "Message us on WhatsApp and we'll help you order right away" not in out


def test_over_cap_lines_all_carry_the_link_and_sell_nothing_false():
    for line in rt._OVER_CAP_POOL:
        assert "{link}" in line and "{name}" in line
        assert "WhatsApp" not in line          # the page IS the answer


def test_still_neutral_when_we_cannot_identify_the_product():
    out = rt._comment_public_reply("", dm_sent=False, link="", name_tag=" Grace",
                                   seed="grace", product_link="")
    assert out in [p.replace("{name}", " Grace") for p in rt._NEUTRAL_ACK_POOL]
