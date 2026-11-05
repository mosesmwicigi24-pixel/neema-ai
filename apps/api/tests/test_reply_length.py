"""THE REPLY-LENGTH TARGET (audit, 2026-11-05): a short ask earns a short
reply; the target is computed, handed to the writer, and a long reply is
recorded — never trimmed."""
import asyncio

import app.main  # noqa: F401 — registers models
from app.agent import reply_length as rl
from app.core.config import settings


def test_mama_beths_messages_get_short_targets():
    assert rl.target_for("Is it included there")["kind"] == "short"
    assert rl.target_for("Even the fible")["kind"] == "short"
    assert rl.target_for("How much is bishop man complete clothes")["kind"] == "short"
    assert rl.target_for("Which particular colour for lady rev")["kind"] == "short"
    assert rl.target_for("thanks", closer=True)["kind"] == "ack"
    assert rl.target_for("Hello", greeting=True)["kind"] == "ack"


def test_detail_complaints_and_long_messages_get_room():
    assert rl.target_for("May see the complete set of lady reverend plz, what's included?")["kind"] == "detail"
    assert rl.target_for("Tell me about the Cassock Set and the Cope set, and what each comes with")["kind"] == "detail"
    assert rl.target_for("Which colour? And how long does delivery take?")["kind"] == "detail"
    assert rl.target_for("The tray arrived broken and nobody is answering", negative=True)["kind"] == "complaint"
    long_msg = " ".join(["word"] * 30)
    assert rl.target_for(long_msg)["kind"] == "default"
    assert rl.TARGETS["ack"] < rl.TARGETS["short"] < rl.TARGETS["question"] < rl.TARGETS["detail"]


def test_the_note_names_the_target_and_the_fact_first():
    n = rl.note(rl.target_for("Is it included there"))
    assert "at most 25 words" in n and "the fact first" in n and "a 4-word ask" in n
    assert rl.note({}) == ""


def test_measure_and_long():
    essay = ("Yes, Mama Beth — the shepherd's rod (staff) is already included in that KES 60,500 "
             "total. Would you like anything else added, or shall we settle delivery details?")
    m = rl.measure(essay)
    assert m["words"] == 28 and m["sentences"] == 2 and m["questions"] == 1
    t = rl.target_for("Is it included there")
    assert rl.is_long("Yes, the rod is included in the KES 60,500.", t) is None
    hit = rl.is_long(" ".join(["word"] * 40), t)
    assert hit and hit["target"] == 25 and hit["words"] == 40
    # an order summary is never capped
    assert rl.is_long(" ".join(["word"] * 80), t,
                      tool_log=[{"tool": "create_order", "out": {"ok": True}}]) is None
    assert rl.is_long(" ".join(["word"] * 80), t,
                      tool_log=[{"tool": "create_order", "out": {"error": "hub down"}}])


def test_a_long_reply_is_recorded_once_and_the_reply_is_untouched(monkeypatch):
    calls = []

    async def _record_all(redis, db, channel, key, decisions, counts):
        calls.append((decisions, counts))
        return []
    monkeypatch.setattr("app.agent.conversation_budget._record_all", _record_all)
    t = rl.target_for("Is it included there")
    long = " ".join(["word"] * 40)
    hit = asyncio.run(rl.record(object(), None, channel="whatsapp", key="k", reply=long, target=t, tool_log=[]))
    assert hit["words"] == 40
    (decisions, counts), = calls
    assert decisions[0][0] == "long" and "40 words" in decisions[0][1][0]
    assert counts == {"turns": 40, "budget": 25}
    assert asyncio.run(rl.record(object(), None, channel="whatsapp", key="k", reply="Yes.", target=t, tool_log=[])) is None
    monkeypatch.setattr(settings, "reply_length_record", False, raising=False)
    assert asyncio.run(rl.record(object(), None, channel="whatsapp", key="k", reply=long, target=t, tool_log=[])) is None


def test_run_turn_hands_the_target_over_and_never_trims():
    import inspect
    from app.agent import runtime
    from app.agent import conversation_budget as cb
    src = inspect.getsource(runtime.run_turn)
    assert src.index("_rl.target_for(") < src.index("llm.complete(system=sys_blocks")
    i = src.index("_rl2.record(")
    assert "reply =" not in src[i: i + 400]
    assert cb.DECISIONS["long"].startswith("Reply ran long")
