"""Handle the complaint — don't just pass it on.

Escalation used to mean Neema STOPPED TALKING: `handoff_to_human` sets
intercept_mode=human, and the missed-reply sweeper only picks up conversations
where intercept_mode == ai. So an escalated thread was also dropped from the
safety net that catches missed replies — a complaint at 11pm got one apology and
then silence until someone opened the dashboard. The angriest customer received
the least service.

The agreed design: Neema acknowledges, DIAGNOSES with her tools, tells the
customer what she found, and files a complete case for the team — who always
follow up and have the final word — while she STAYS in the conversation
answering factual questions. She may explain, correct and inform; she may never
promise money.
"""
import asyncio
import types

# Import the full ORM registry so Conversation's relationships (Agent, Message,
# Intercept) resolve when an Intercept is instantiated — matches the repo's
# FakeDB convention and keeps this module passing standalone.
import app.models.agent, app.models.message, app.models.intercept  # noqa: F401
import app.models.person, app.models.user  # noqa: F401
from app.agent.prompt import build_system_prompt
from app.agent.tools import TOOLS, ToolContext, _raise_complaint


def _tool(name: str) -> dict:
    return next(t for t in TOOLS if t["name"] == name)


class _Conv:
    def __init__(self):
        self.id = "conv-1"
        from app.models.conversation import InterceptMode
        self.intercept_mode = InterceptMode.ai


class _Res:
    def __init__(self, conv): self._conv = conv
    def scalars(self): return types.SimpleNamespace(
        first=lambda: self._conv, all=lambda: ([self._conv] if self._conv else []))
    def scalar_one_or_none(self): return self._conv


class _DB:
    def __init__(self, conv): self._conv, self.added, self.committed = conv, [], False
    async def execute(self, *a, **k): return _Res(self._conv)
    def add(self, obj): self.added.append(obj)
    async def commit(self): self.committed = True


# ── the tool files a complete case and does NOT mute Neema ───────────────────

def test_raise_complaint_files_a_case_without_muting_neema():
    from app.models.conversation import InterceptMode
    conv = _Conv()
    db = _DB(conv)
    ctx = ToolContext(db=db, redis=None, wa_id="254712345678", channel="whatsapp")
    out = asyncio.run(_raise_complaint({
        "issue": "Order arrived with the wrong collar size",
        "findings": "Order WA-1043, delivered 3 Aug; cart shows 16.5in, customer says 15in came",
        "wanted": "the correct size sent",
        "severity": "high",
    }, ctx))

    assert out["ok"] is True and out["logged"] is True and out["severity"] == "high"
    # THE POINT: the conversation stays in AI mode, so Neema keeps answering and
    # the missed-reply sweeper still covers the thread.
    assert conv.intercept_mode == InterceptMode.ai

    note = db.added[0].note
    assert "COMPLAINT (HIGH)" in note
    assert "wrong collar size" in note                 # what they said
    assert "WA-1043" in note                           # what Neema found
    assert "the correct size sent" in note             # what they want
    assert "colleague must follow up" in note


def test_raise_complaint_states_the_authority_boundary():
    """Money stays a human decision — the tool result says so every time."""
    ctx = ToolContext(db=_DB(_Conv()), redis=None, wa_id="254712345678", channel="whatsapp")
    out = asyncio.run(_raise_complaint({"issue": "late delivery"}, ctx))
    may, may_not = out["you_may"], out["you_may_not"]
    assert "order status" in may and "colleague" in may
    for forbidden in ("refund", "discount", "remake", "reshipment"):
        assert forbidden in may_not, forbidden
    # and she is told to stay, not to sign off
    assert "STAY with them" in out["next_step"]


def test_raise_complaint_requires_the_issue():
    ctx = ToolContext(db=_DB(_Conv()), redis=None, wa_id="254712345678", channel="whatsapp")
    assert "error" in asyncio.run(_raise_complaint({}, ctx))


def test_missing_conversation_still_tells_neema_to_keep_helping():
    ctx = ToolContext(db=_DB(None), redis=None, wa_id="PSID9", channel="messenger")
    out = asyncio.run(_raise_complaint({"issue": "no reply for days"}, ctx))
    assert out["logged"] is False
    assert "keep helping" in out["next_step"]


# ── the tool descriptions point complaints at the right door ─────────────────

def test_complaints_route_to_raise_complaint_not_handoff():
    assert "raise_complaint" in _tool("handoff_to_human")["description"]
    rc = _tool("raise_complaint")["description"]
    assert "COMPLETE CASE" in rc
    assert "check_order_status" in rc          # diagnose BEFORE filing
    assert "final word" in rc                  # a human always closes it
    assert "STAY in the conversation" in rc


# ── the protocol is in the prompt, in order ──────────────────────────────────

def test_prompt_carries_the_repair_protocol_in_order():
    p = build_system_prompt(country="Kenya", country_iso="KE", currency="KES")
    assert "WHEN SOMETHING HAS GONE WRONG" in p
    for step in ("ACKNOWLEDGE", "FIND OUT", "TELL THEM WHAT YOU FOUND",
                 "BRING IN A COLLEAGUE", "STAY WITH THEM"):
        assert step in p, step
    # diagnosis comes before escalation
    assert p.index("FIND OUT") < p.index("BRING IN A COLLEAGUE")
    # the boundary is explicit both ways
    assert "WHAT YOU MAY DO" in p and "WHAT YOU MAY NEVER DO" in p
    assert "never go silent" in p.lower()
    assert "Do not sell into a complaint" in p


def test_prompt_forbids_promising_money():
    p = build_system_prompt(country="Kenya", country_iso="KE", currency="KES")
    assert "promise or start a refund" in p
    assert "offer a discount" in p
    # …but never a flat refusal to the customer
    assert 'never "no"' in p
