"""The checker after the audit of 2026-11-05 (Mama Beth's chat): the three
things that passed and should not have, and the rewrite that made replies
longer.

  "shall I search for the price in our hub to confirm it for you?"  → INTERNAL TALK
  "Let me confirm the Bible with our team and get back to you."     → PROMISE ONLY
  "For Pentecost, the lady Reverend wears violet (purple)."         → UNSUPPORTED CUSTOM (model rule)
  the rewrite's "keep … the closing question"                        → gone
"""
import app.main  # noqa: F401 — registers models
from app.agent import review as rv

ROWS = [{"name": "Incense Burner / Thurible", "price": 15000, "price_usd": 150, "currency": "KES"}]


def test_naming_the_hub_or_a_hold_is_internal_talk():
    for line in ("Which colour would you like — and shall I search for the price in our hub to confirm it for you?",
                 "Shall I hold the Bishop's set while you decide on the lady Reverend's colour?",
                 "Let me check our system for that.",
                 "I'll reserve it for you until Friday."):
        assert rv.internal_talk(line), line
    for line in ("The incense burner is KES 15,000. How many do you need?",
                 "Yes, the rod is included in the KES 60,500.",
                 "Our shop is at Sonalux Building, Moi Avenue."):
        assert rv.internal_talk(line) is None, line


def test_a_promise_in_place_of_an_answer_in_hand_is_flagged():
    assert rv.promise_only("Let me confirm the Bible with our team and get back to you right away.", ROWS)
    assert rv.promise_only("Ngoja nihakikishe na timu.", ROWS)
    # the answer given → not a promise-only reply
    assert rv.promise_only("The thurible is KES 15,000 — let me confirm the delivery day with the team.", ROWS) is None
    # nothing priced in hand → not this finding (the item rule / reviewer reads it)
    assert rv.promise_only("Let me confirm that with our team.", []) is None
    assert rv.promise_only("Let me confirm that with our team.", [{"name": "x", "price": 0}]) is None


def test_the_rules_carry_the_two_new_kinds():
    out = rv.rule_findings("How much is the incense burner?",
                           "Let me check our hub and get back to you.", ROWS,
                           tool_results=[{"tool": "search_catalog", "out": {"results": ROWS}}])
    kinds = {f["kind"] for f in out}
    assert {"internal", "promise"} <= kinds
    assert all(not f["hard"] for f in out if f["kind"] in ("internal", "promise"))
    clean = rv.rule_findings("How much is the incense burner?",
                             "The Incense Burner is KES 15,000. How many do you need?", ROWS,
                             tool_results=[{"tool": "search_catalog", "out": {"results": ROWS}}])
    assert not [f for f in clean if f["kind"] in ("internal", "promise")]


def test_the_reviewer_reads_sixteen_turns_of_four_hundred():
    t = [{"role": "user", "content": f"turn {i} " + "x" * 500} for i in range(30)]
    text = rv.conversation_text(t)
    assert text.count("\n") + 1 == rv.REVIEW_TURNS == 16
    assert all(len(line) <= len("Customer: ") + rv.REVIEW_TURN_CHARS for line in text.splitlines())
    assert "turn 14" in text and "turn 13" not in text


def test_the_reviewer_is_asked_the_three_new_questions(monkeypatch):
    import asyncio
    captured = {}

    class _LLM:
        async def complete(self, system, messages, tools=()):
            captured["prompt"] = messages[0]["content"]
            import types
            return types.SimpleNamespace(text="verdict=pass | issues=-")
    monkeypatch.setattr("app.agent.runtime.build_llm", lambda **k: _LLM())
    asyncio.run(rv.reviewer_verdict("Plz assist for pentacost churches",
                                    "For Pentecost, the lady Reverend wears violet.", ROWS, mode="dm"))
    p = captured["prompt"]
    assert "9. UNSUPPORTED CUSTOM" in p and "'wears'" in p
    assert "10. INTERNAL TALK" in p and "11. PROMISE ONLY" in p
    assert "Never fail for tone, warmth, length or emoji" in p


def test_the_rewrite_no_longer_demands_a_closing_question():
    block = rv.rewrite_block(["x"], "A long draft.", ROWS, "KES", [], mode="dm")
    assert "closing question" not in block
    assert "NO LONGER than the held draft" in block
    assert "each fact said ONCE" in block
    assert "never name our hub" in block
    assert "end with a question only if it moves the order" in block
