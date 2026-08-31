"""Second adversarial audit of Neema's prompt system (2026-08-08) — the fixes.

Round one (test_meta_audit.py) built the precedence ladder and merged the mood
rules. This round found seam defects — places where a CHANNEL ADDENDUM or a
BACKGROUND JOB contradicted doctrine the core prompt gets right:

 F1  The Messenger/Instagram addendum said "if something isn't in the
     catalogue, say so" — ordering Neema to speak the absence on exactly the
     channels where new customers arrive, against NEVER SPEAK THE ABSENCE.
 F2  The follow-up scheduler consulted the 24h window, human-held state, deal
     total and nudge count — but not open grievances: a refill ping could fire
     into a thread with an unresolved complaint.
 F3  The ready-made door was urgency-gated ("when they need it fast"), though
     the owner's rule is ready-made FIRST for vestments, always.
 F4  The comment-reply identification ladder put OUR RECORDS last, inviting
     the model to re-guess a shiny frame against a team override.
 F5  The unlinked cross-channel jumper ("I commented on your IG post", said on
     WhatsApp with no link in context) had no rule — fabrication risk.
 F6  check_order_status's description advertised only "where's my order?",
     though the PAID-claim rule and complaint step 2 both depend on it.
 F7  The website chat's failure fallback apologised and asked the visitor to
     retry — no hold line, no dashboard flag, nobody alerted.
"""
import asyncio
import inspect
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent.prompt import build_system_prompt


def _flat_prompt() -> str:
    return " ".join(build_system_prompt(country_iso="KE", currency="KES").split())


# ── F1: the Meta addendum no longer speaks the absence ───────────────────────

def test_meta_addendum_confirms_availability_never_denies_it():
    from app.agent.runtime import _meta_addendum
    a = " ".join(_meta_addendum("USD").split())
    assert "if something isn't in the catalogue, say so" not in a
    assert "NEVER say we don't have it" in a
    assert "NEVER SPEAK THE ABSENCE" in a
    assert "check_availability" in a


# ── F2: the scheduler never nudges into a flagged thread ─────────────────────

class _QueueDB:
    """Returns queued counts in call order: needs_approval queries the recent
    Intercept flags first, then (when a deal is passed) the sent-nudge count."""
    def __init__(self, counts):
        self._counts = list(counts)
    async def execute(self, *a, **k):
        n = self._counts.pop(0)
        return types.SimpleNamespace(scalar_one=lambda: n)


def test_flagged_conversation_gates_scheduled_sends():
    from app.models.conversation import InterceptMode
    from app.services import actions as act
    conv = types.SimpleNamespace(id="c1", intercept_mode=InterceptMode.ai)
    small = types.SimpleNamespace(id="d1", items_snapshot=[{"qty": 1, "price": 500}])
    # A flag inside the last 7 days → the action waits for a human.
    out = asyncio.run(act.needs_approval(_QueueDB([1]), small, conv, in_window=True))
    assert out is not None and "flagged" in out
    # No flags → the same small fresh deal auto-sends as before.
    out2 = asyncio.run(act.needs_approval(_QueueDB([0, 0]), small, conv, in_window=True))
    assert out2 is None


def test_flag_gate_queries_a_seven_day_window():
    from app.services import actions as act
    src = inspect.getsource(act.needs_approval)
    assert "InterceptAction.flag" in src
    assert "timedelta(days=7)" in src
    # The docstring gate list names the new rule for the next reader.
    assert "flagged for the team" in inspect.getsource(act).split("async def")[0]


# ── F3: the ready-made door opens for every vestment buyer, not the rushed ───

def test_ready_made_door_is_not_urgency_gated():
    flat = _flat_prompt()
    assert "When they need it fast" not in flat
    assert "ALWAYS open the ready-made door in the SAME breath as the custom one" in flat
    assert "whatever their pace, urgency signalled or not" in flat


# ── F4: our records outrank the shiny frame ──────────────────────────────────

def test_comment_ladder_reads_records_first():
    from app.agent.runtime import _public_comment_addendum
    a = " ".join(_public_comment_addendum("USD").split())
    assert a.index("OUR RECORDS of this post") < a.index("the post's CAPTION")
    assert a.index("the post's CAPTION") < a.index("ACTUALLY shows")
    assert "never re-guess it from the frame" in a
    # The rungs the Asraya fix pinned are all still present.
    assert "features over finish" in a
    assert "Give both closest options rather than guessing" in a


# ── F5: the unlinked cross-channel jumper is bridged, never bluffed ──────────

def test_unlinked_jumper_gets_a_bridge_not_a_bluff():
    flat = _flat_prompt()
    assert "never pretend to see that conversation" in flat
    assert "never make the gap their problem" in flat
    assert "ONE bridging question" in flat


# ── F6: the order-status tool advertises its verification duties ─────────────

def test_check_order_status_description_covers_payment_claims():
    from app.agent.tools import TOOLS
    desc = next(t for t in TOOLS if t["name"] == "check_order_status")["description"]
    assert "VERIFY any payment claim" in desc
    assert "never confirm payment without it" in desc
    assert "complaint" in desc


# ── F7: a failed web turn holds warmly and flags the team ────────────────────

def test_web_chat_failure_uses_the_hold_line_and_flags():
    from app.routers import web_chat
    src = inspect.getsource(web_chat)
    assert "hit a snag" not in src                      # the retry-apology is gone
    assert "_hold_line(" in src
    assert "InterceptAction.flag" in src
    assert "agent:holdline:web:" in src                 # flags at most once per 2h
