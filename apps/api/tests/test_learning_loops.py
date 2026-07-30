"""Phase D — the learning loops: she reviews her work, reports, and improves."""
import asyncio
import types

from app.jobs import self_qa as qa


def test_repeated_question_detector():
    a = "Which colour would you like for the cassock?"
    b = "What colour would you like for your cassock?"
    assert qa.is_repeated_question(a, b)
    assert not qa.is_repeated_question(a, "And which size do you wear?")
    assert not qa.is_repeated_question("Thank you!", "Thank you!")   # no question marks


def test_find_issues_catches_reask_and_missed_close():
    msgs = [
        {"direction": "inbound",  "text": "I need a cassock"},
        {"direction": "outbound", "text": "Lovely! Which colour would you like for the cassock?"},
        {"direction": "inbound",  "text": "Purple"},
        {"direction": "outbound", "text": "Which colour would you like for your cassock?"},
        {"direction": "inbound",  "text": "How do I pay?"},
        {"direction": "outbound", "text": "We are located in Nairobi and ship worldwide."},
    ]
    kinds = [f["kind"] for f in qa.find_issues(msgs)]
    assert "repeated_question" in kinds
    assert "missed_close" in kinds


def test_close_marker_suppresses_missed_close():
    msgs = [
        {"direction": "inbound",  "text": "Ready to pay, send me the total"},
        {"direction": "outbound", "text": "Your order total is KES 36,000 — pay here: link"},
    ]
    assert qa.find_issues(msgs) == []


def test_distillation_stores_capped_proposals(monkeypatch):
    stored = {}

    async def fake_set(db, key, value):
        stored[key] = value
    monkeypatch.setattr("app.services.app_settings.set_value", fake_set)

    class _Rows:
        def __init__(self, items): self._i = items
        def scalars(self): return types.SimpleNamespace(all=lambda: self._i)

    fb = [types.SimpleNamespace(draft="Dear customer, ...", sent="Habari! ...")]
    qa_rows = [types.SimpleNamespace(kind="repeated_question")]

    class _DB:
        def __init__(self): self._q = [_Rows(fb), _Rows(qa_rows)]
        async def execute(self, *a, **k): return self._q.pop(0)

    class _LLM:
        async def complete(self, *, system, messages, tools):
            return types.SimpleNamespace(text="Open with Habari, never Dear\n"
                                              "Re-check the thread before asking colours\n"
                                              "Rule three\nRule four (dropped)")

    n = asyncio.run(qa.distill_weekly(_DB(), llm=_LLM()))
    assert n == 3                                     # capped at 3
    import json
    props = json.loads(stored["rule_proposals"])
    assert props[0]["status"] == "pending"
    assert "Habari" in props[0]["rule"]


def test_learned_rules_ride_the_standing_orders_block():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(currency="KES",
                            directives="Push copes\n\nLEARNED RULES (approved from "
                                       "experience — follow them):\n- Open with Habari")
    assert "LEARNED RULES" in p and "Open with Habari" in p


def test_proposal_routes_registered():
    from app.routers.crm import router
    paths = {r.path for r in router.routes}
    assert "/settings/proposals" in paths
    assert "/settings/proposals/{idx}/{verdict}" in paths
