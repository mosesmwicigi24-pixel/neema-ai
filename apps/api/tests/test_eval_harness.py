"""The intelligence evaluation harness, model-free: the case-set loader
validates labels, the split is stable, the floors scorer and the turn
verdicts judge what they claim, the sandbox swaps and restores the
customer-reaching tools, and the summary carries Wilson intervals."""
from __future__ import annotations

import pytest

from app.jobs import eval_cases, eval_floors, eval_run


def test_the_case_set_loads_and_every_case_has_a_next_action():
    cases = eval_cases.load()
    assert cases, "no cases"
    for c in cases:
        for t in c["turns"]:
            assert t["expect"]["next"] in eval_cases.NEXT_ACTIONS
    cov = eval_cases.coverage(cases)
    assert cov["cases"] == len(cases) and cov["turns"] >= len(cases)


def test_the_split_is_stable_and_disjoint():
    cases = eval_cases.load()
    d1, h1 = eval_cases.split(cases)
    d2, h2 = eval_cases.split(list(reversed(cases)))
    assert {c["id"] for c in d1} == {c["id"] for c in d2}
    assert not ({c["id"] for c in d1} & {c["id"] for c in h1})
    assert len(d1) + len(h1) == len(cases)


def test_a_bad_label_is_refused(tmp_path, monkeypatch):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id":"x-1","source":"independent","categories":["simple-enquiry"],'
                   '"turns":[{"user":"hi","expect":{"next":"dance"}}]}\n', encoding="utf-8")
    monkeypatch.setattr(eval_cases, "HERE", tmp_path)
    with pytest.raises(ValueError):
        eval_cases.load("bad.jsonl")


def test_wilson_interval_is_sane():
    p, lo, hi = eval_floors.wilson(90, 100)
    assert abs(p - 0.9) < 1e-9 and 0.82 < lo < 0.9 < hi < 0.96
    assert eval_floors.wilson(0, 0) == (0.0, 0.0, 0.0)


def test_the_floors_scorer_reports_misses_by_case():
    cases = [{"id": "t-1", "source": "independent", "categories": ["opt-out"], "lang": "en",
              "turns": [{"user": "Please stop messaging me", "expect": {"next": "stop_ack", "said": "stop",
                                                                         "opt_out": True, "lang": "en"}},
                        {"user": "How much is a stole?", "expect": {"next": "quote", "said": None,
                                                                    "opt_out": False, "length_kind": "short"}}]}]
    res = eval_floors.score(cases)
    assert res["metrics"]["said"]["all"]["k"] == 2
    assert res["metrics"]["opt_out"]["all"]["k"] == 2
    assert res["metrics"]["length_kind"]["all"]["k"] == 1
    assert res["misses"] == []        # "Please stop messaging me" reads as English since W2


def _turn(next_, **exp):
    return {"user": "x", "expect": {"next": next_, **exp}}


def test_turn_verdicts_catch_the_named_failures():
    case = {"id": "c", "lang": "en", "critical": True, "categories": ["opt-out"]}
    facts = {"tools": [], "review": "pass"}
    v = eval_run.check_turn(case, 0, _turn("silence"), "You're welcome!", facts,
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert "answered a closer (silence expected)" in v["failures"]
    v = eval_run.check_turn(case, 0, _turn("stop_ack"), "Noted, we will not message you again.", facts,
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert "opt-out not recorded" in v["failures"]
    v = eval_run.check_turn(case, 0, _turn("stop_ack"), "Noted.", facts,
                            opted_out=True, intercept_mode="ai", after_hold=False)
    assert v["passed"]
    v = eval_run.check_turn(case, 0, _turn("hold_ack"), "Sure — shall I start your order meanwhile?", facts,
                            opted_out=False, intercept_mode="ai", after_hold=True)
    assert "pitched after a request for time" in v["failures"]
    v = eval_run.check_turn(case, 0, _turn("hold_ack"), "Of course. Which day suits you?", facts,
                            opted_out=False, intercept_mode="ai", after_hold=True)
    assert "re-asked for a date the customer already gave" in v["failures"]
    v = eval_run.check_turn(case, 0, _turn("confirm_paid_check"), "Thank you for your payment!", facts,
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert "thanked for a payment not seen" in v["failures"]
    v = eval_run.check_turn(case, 0, _turn("escalate"), "Let me help you myself.", facts,
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert "did not hand to a person" in v["failures"]
    v = eval_run.check_turn(case, 0, _turn("escalate"), "A colleague will take this from here.",
                            {"tools": [{"tool": "handoff_to_human", "out": {}}], "review": "pass"},
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert v["passed"]
    v = eval_run.check_turn(case, 0, _turn("answer", forbid=["\\bhub\\b"]), "Let me search the hub.", facts,
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert any("forbidden" in f for f in v["failures"])
    v = eval_run.check_turn(case, 0, _turn("answer", tool="!create_order"), "Done.",
                            {"tools": [{"tool": "create_order", "out": {}}], "review": "pass"},
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert "called create_order (forbidden)" in v["failures"]
    v = eval_run.check_turn(case, 0, _turn("answer"), "Only 2 left, today only!", facts,
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert "manufactured urgency or scarcity" in v["failures"]


def test_tool_labels_are_mapped_onto_registered_tools():
    assert eval_run.canonical_tool("check_payment") == "check_order_status"
    assert eval_run.canonical_tool("!order") == "!create_order"
    assert eval_run.canonical_tool("search_catalog") == "search_catalog"
    case = {"id": "c", "lang": "en", "categories": ["payment"]}
    v = eval_run.check_turn(case, 0, _turn("confirm_paid_check", tool="check_payment"), "Checking now.",
                            {"tools": [{"tool": "check_order_status", "out": {}}], "review": "pass"},
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert v["passed"], v["failures"]


def test_figures_must_come_from_this_turns_tools():
    case = {"id": "c", "lang": "en", "categories": ["payment"]}
    tools = [{"tool": "search_catalog", "input": {}, "out": {"results": [{"name": "Stole", "price": 2500}]}}]
    v = eval_run.check_turn(case, 0, _turn("quote", figures="hub-only"), "The stole is KES 2,500.",
                            {"tools": tools, "review": "pass"}, opted_out=False, intercept_mode="ai",
                            after_hold=False)
    assert v["passed"], v["failures"]
    v = eval_run.check_turn(case, 0, _turn("quote", figures="hub-only"), "The stole is KES 3,000.",
                            {"tools": tools, "review": "pass"}, opted_out=False, intercept_mode="ai",
                            after_hold=False)
    assert any("not from this turn's tools" in f for f in v["failures"])


def test_language_continuity_checks_script_and_tongue():
    assert eval_run.language_ok("hi", "नमस्ते, कीमत है") is True
    assert eval_run.language_ok("hi", "Hello, the price is") is False
    assert eval_run.language_ok("sw", "Bei ya stola ni elfu mbili na mia tano, karibu.") is True
    assert eval_run.language_ok("sw", "The stole is two thousand five hundred.") is False
    assert eval_run.language_ok("fr", "Bonjour, le prix est de 25 dollars pour la chasuble.") is True
    assert eval_run.language_ok("en", "The stole is KES 2,500.") is True
    assert eval_run.language_ok("sheng", "Niaje, poa.") is None
    assert eval_run.language_ok("sw", "") is None


@pytest.mark.asyncio
async def test_the_sandbox_swaps_and_restores_the_customer_reaching_tools():
    from app.agent import tools as _t
    before = {n: _t._HANDLERS[n] for n in eval_run.SANDBOXED if n in _t._HANDLERS}
    assert before, "no sandboxed tool is registered"
    with eval_run._Sandbox() as box:
        for name in before:
            assert _t._HANDLERS[name] is not before[name]
        out = await _t._HANDLERS["create_order"]({"items": []}, type("Ctx", (), {"wa_id": "2547000 9001"})())
        assert out.get("sandbox") is True and box.calls[0]["tool"] == "create_order"
    for name, fn in before.items():
        assert _t._HANDLERS[name] is fn


def test_the_summary_carries_intervals_and_pass_k():
    def turn(passed, nxt="answer", lang="en", critical=False, judge=None):
        return {"i": 0, "user": "x", "reply": "y", "next": nxt, "critical": critical,
                "categories": ["simple-enquiry"], "lang": lang, "latency_s": 1.0, "error": None,
                "door": None, "verdict": {"passed": passed, "failures": [] if passed else ["x"],
                                          "observations": {"language_ok": True, "figures": [], "unverified": [],
                                                           "silent": False, "over_target": False,
                                                           "internal_talk": [], "review": "pass",
                                                           "judge": judge or []}}}
    results = [{"id": "a", "repeat": 1, "turns": [turn(True)]}, {"id": "a", "repeat": 2, "turns": [turn(False)]},
               {"id": "b", "repeat": 1, "turns": [turn(True)]}, {"id": "b", "repeat": 2, "turns": [turn(True)]}]
    s = eval_run.summarise(results, repeat=2)
    assert s["turns"]["k"] == 3 and s["turns"]["n"] == 4 and len(s["turns"]["ci95"]) == 2
    assert s["pass^2"]["k"] == 1 and s["pass^2"]["n"] == 2
    assert s["pass^1"]["k"] == 3 and s["pass^1"]["n"] == 4


def test_the_contact_for_a_case_is_a_throwaway_in_the_right_market():
    wa = eval_run.contact_for({"country": "TZ"}, 7)
    assert wa.startswith("2557000" + eval_run.EVAL_TAG) and wa.endswith("007")
    assert eval_run.contact_for({}, 1).startswith("2547000")


def test_the_rater_packet_lists_only_judged_turns(tmp_path):
    record = {"started": "now", "case_set": "abc", "cases": 1, "results": [{
        "id": "c-1", "turns": [
            {"i": 0, "user": "hi", "reply": "hello", "verdict": {"observations": {"judge": []}}},
            {"i": 1, "user": "my order is late", "reply": "I'm sorry — let me check.",
             "verdict": {"observations": {"judge": ["emotion"]}}}]}]}
    path = tmp_path / "packet.md"
    eval_run.write_packet(record, str(path))
    text = path.read_text(encoding="utf-8")
    assert "Item 1 — c-1 turn 1" in text and "emotion: ___" in text and "Item 2" not in text


def test_an_empty_reply_never_passes_where_a_reply_was_expected():
    case = {"id": "c", "lang": "en", "categories": ["simple-enquiry"]}
    for nxt in eval_run.REPLY_EXPECTED:
        v = eval_run.check_turn(case, 0, _turn(nxt), "", {"tools": [], "review": None},
                                opted_out=(nxt == "stop_ack"), intercept_mode="ai", after_hold=False)
        assert not v["passed"] and any("no reply where one was expected" in f for f in v["failures"]), nxt
    v = eval_run.check_turn(case, 0, _turn("answer", require=["stole"]), "", {"tools": [], "review": None},
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert any("required text missing" in f for f in v["failures"])
    v = eval_run.check_turn(case, 0, _turn("answer"), "", {"tools": [], "review": None, "error": "boom"},
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert any("turn raised" in f for f in v["failures"])
    v = eval_run.check_turn(case, 0, _turn("silence"), "", {"tools": [], "review": None},
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert v["passed"]


def test_the_default_sweep_leaves_the_blind_set_out():
    """The blind held-out file is scored only when named: the development
    split must never contain a blind case (verification pass 1, finding 6)."""
    swept = eval_cases.load()
    assert swept and not any(c.get("blind") for c in swept)
    assert not any(c["_file"] == "blind_heldout.jsonl" for c in swept)
    assert eval_cases.load("blind_heldout.jsonl") == []           # not even when named, unless asked
    assert not any(c.get("blind") for c in eval_cases.load("*.json*"))   # no pattern loophole (pass 2)
    blind = eval_cases.load("blind_heldout.jsonl", include_blind=True)
    assert blind and all(c.get("blind") for c in blind)
    assert eval_cases.load(include_blind=True) and len(eval_cases.load(include_blind=True)) == len(swept) + len(blind)
    dev, held = eval_cases.split(swept)
    assert not any(c.get("blind") for c in dev + held)


def test_the_runner_and_the_scorer_reach_the_blind_set_and_refuse_an_empty_run(tmp_path, monkeypatch):
    """Verification pass 2b: include_blind on both --file paths, pinned; an
    empty selection is never a green exit; a blind run withholds its misses."""
    import json
    import sys
    from app.jobs import eval_floors, eval_run

    blind = eval_run.select_cases("held-out", file="blind_heldout.jsonl")
    assert len(blind) == 120 and all(c.get("blind") for c in blind)          # --held-out means nothing with --file
    assert eval_run.select_cases("held-out", file="blind_heldout.jsonl", only="zzz") == []
    assert not any(c.get("blind") for c in eval_run.select_cases("all"))

    out = tmp_path / "blind.json"
    monkeypatch.setattr(sys, "argv", ["eval_floors", "--file", "blind_heldout.jsonl", "--json", str(out)])
    eval_floors._cli()
    rec = json.loads(out.read_text())
    assert rec["coverage"]["cases"] == 120 and rec["coverage"]["turns"] == 459
    assert rec["misses"] == [] and "blind" in rec["misses_withheld"]
    assert rec["metrics"]["said"]["all"]["n"] == 459

    monkeypatch.setattr(sys, "argv", ["eval_floors", "--file", "no_such_file.jsonl"])
    with pytest.raises(SystemExit) as e:
        eval_floors._cli()
    assert e.value.code == 2


def test_the_runner_process_can_configure_every_mapper():
    """CI, 2026-11-06: the eval process imported a hand-picked list of models,
    and in CI the first database use died on persons.parish_id → parishes
    before a single case ran. The runner now registers every model, as the
    API process does. This pins that registration (the old list happened to
    resolve in the local environment, so this is a guard, not a reproduction;
    the workflow run is the proof)."""
    import importlib
    from sqlalchemy.orm import clear_mappers, configure_mappers
    importlib.import_module("app.jobs.agent_eval")
    configure_mappers()                      # raises NoReferencedTableError when a model is missing
    assert clear_mappers is not None
