"""The giveaway thread's test harness (app.jobs.eval_giveaway): its checks,
its cases, and the guards that keep it off Facebook and off a real database."""
import inspect

import pytest

import app.main  # noqa: F401
from app.jobs import eval_giveaway as eg


def test_the_checks_read_a_turn_the_way_the_directive_does():
    silent = {"expect": "silent"}
    assert eg.check_turn(silent, "") == [] and eg.check_turn(silent, "Amen to that!")
    reply = {"expect": "reply", "must_not": [eg.PRICE, eg.SELL, eg.WELCOME], "must": [r"gift|free"],
             "max_words": 12}
    assert eg.check_turn(reply, "") == ["no reply where one was needed"]
    assert eg.check_turn(reply, "It is a gift, Pastor.") == []
    bad = eg.check_turn(reply, "Welcome to Bethany House! Our Cassock is KES 13,000 — place your order.")
    assert len(bad) >= 3 and any("KES 1" in b for b in bad) and any("missing" in b for b in bad)
    assert any("too long" in f for f in eg.check_turn(reply, "It is a gift " * 6))
    anyway = {"expect": "any", "must_not": [eg.PROCEDURE]}
    assert eg.check_turn(anyway, "") == []
    assert eg.check_turn(anyway, "Our team will be selecting one recipient — follow us.")


@pytest.mark.parametrize("text", ["KES 13,000", "$130", "13,000 shillings", "USD 200"])
def test_a_price_is_recognised(text):
    import re
    assert re.search(eg.PRICE, text, re.IGNORECASE)


def test_the_cases_cover_the_owners_thread_and_the_directives_list():
    ids = {c["id"]: c for c in eg.CASES}
    assert len(ids) == 6
    thread = ids["give-001"]["turns"]
    assert thread[1]["text"].startswith("Bethany House Pentecostal") and thread[1]["thread"]
    assert thread[-1] == {"text": "Thank you", "thread": True, "expect": "silent"}
    assert "gift me" in ids["give-002"]["turns"][0]["text"]
    assert all(t.get("expect") in (None, "reply", "silent", "any") for c in eg.CASES for t in c["turns"])
    import app.agent.runtime as rt
    assert rt.is_campaign_post(eg.CAPTION) and not rt.campaign_is_draw(eg.CAPTION)


def test_nothing_reaches_facebook_and_only_a_local_database_is_used(monkeypatch):
    src = inspect.getsource(eg.run)
    for send in ("reply_to_comment", "send_private_reply", "like_comment"):
        assert f"meta_send.{send}" in src
    assert src.index("_local_db_only()") < src.index("import redis")
    from app.core.config import settings
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@db.internal:5432/neema")
    with pytest.raises(SystemExit):
        eg._local_db_only()
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@127.0.0.1:5432/neema")
    eg._local_db_only()


def test_the_summary_counts_turns_and_failure_kinds():
    s = eg.summarise([{"turns": [{"reply": "It is a gift.", "failures": []},
                                 {"reply": "", "failures": []},
                                 {"reply": "KES 1", "failures": ["said what it should not: “KES 1”"]}]}])
    assert s["turns"] == 3 and s["passed"] == 2 and s["replies"] == 2 and s["silent"] == 1
    assert s["failure_kinds"] == {"said what it should not": 1}
