"""The conversation budget and the bot shield, record-only (owner,
2026-11-04: "go ahead with the … cooling-off plan" — 15 replies a day plus
10 for every step toward the order; a suspected bot gets one line, silence
and a colleague). Buying WORDS earn nothing — "do you have a wife" and "send
me 100 shillings" were a sale to the old pacing; PROGRESS earns room."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import app.main  # noqa: F401 — registers models
from app.agent import conversation_budget as cb
from app.core.config import settings


class _Redis:
    def __init__(self):
        self.kv, self.sets, self.h = {}, {}, {}

    async def incrby(self, k, n):
        self.kv[k] = int(self.kv.get(k, 0)) + int(n)
        return self.kv[k]

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        return True

    async def expire(self, *a):
        return True

    async def sadd(self, k, v):
        s = self.sets.setdefault(k, set())
        if v in s:
            return 0
        s.add(v)
        return 1

    async def scard(self, k):
        return len(self.sets.get(k, set()))

    async def hincrby(self, k, f, n):
        self.h.setdefault(k, {})[f] = self.h.setdefault(k, {}).get(f, 0) + n

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))


@pytest.fixture
def wired(monkeypatch):
    recorded = []

    async def _record(**kw):
        recorded.append(kw)

    async def _not_in_play(db, channel, key):
        return False
    monkeypatch.setattr(cb, "record", _record)
    monkeypatch.setattr("app.agent.cooling.business_in_play", _not_in_play)
    monkeypatch.setattr(settings, "pacing_budget_mode", "shadow", raising=False)
    return recorded


def _turn(r, text="tell me more", *, tools=None, seen=None, reply="Of course!", **kw):
    return asyncio.run(cb.assess(r, None, channel="whatsapp", key="254700000001", user_text=text,
                                 reply=reply, tool_log=tools or [], seen_products=seen or [], **kw))


def test_the_defaults_the_owner_agreed():
    from app.core.config import Settings
    f = Settings.model_fields
    assert f["pacing_budget_mode"].default == "shadow"
    assert (f["pacing_budget_base"].default, f["pacing_budget_per_step"].default) == (15, 10)


def test_chat_with_no_progress_would_be_shortened_then_paused(wired):
    r = _Redis()
    out = [_turn(r, "do you have a wife") for _ in range(15)]
    assert not any(out)                                  # 15 replies are free
    assert _turn(r, "send me 100 shillings")[0]["decision"] == "shorten"
    for _ in range(9):
        _turn(r, "blue")
    assert _turn(r, "pray for me pastor")[0]["decision"] == "pause"
    assert [x["decision"] for x in wired] == ["shorten", "pause"]   # once each per day
    assert wired[0]["counts"]["budget"] == 15


def test_every_step_toward_the_order_earns_ten_more_replies(wired):
    r = _Redis()
    for i in range(14):
        _turn(r, "how much is it?")
    _turn(r, "I want the black one in L", tools=[{"tool": "update_cart", "out": {"total": 13000}}])
    _turn(r, "and the stole?", seen=[{"slug": "single-sided-stole", "name": "Single Sided Stole"}])
    # 16 replies, two steps of progress → budget 35: replies 17–35 are free
    for _ in range(19):
        assert _turn(r, "ok and what else") == []
    assert _turn(r, "hmm")[0]["decision"] == "shorten"
    assert wired[-1]["counts"]["budget"] == 35


def test_a_failed_tool_or_an_item_already_seen_is_no_progress(wired):
    r = _Redis()
    _turn(r, "x", seen=[{"slug": "cassock"}])
    assert cb.progress_in([{"tool": "create_order", "out": {"error": "hub down"}}], 0) == 0
    assert cb.progress_in([{"tool": "search_catalog", "out": {}}], 0) == 0
    assert cb.progress_in([{"tool": "create_order", "out": {"ok": True}}], 1) == 2


def test_a_buyer_past_the_budget_alerts_the_team_and_is_never_paused(wired, monkeypatch):
    async def _in_play(db, channel, key):
        return True
    monkeypatch.setattr("app.agent.cooling.business_in_play", _in_play)
    r = _Redis()
    for _ in range(40):
        _turn(r, "chat")
    assert [x["decision"] for x in wired] == ["alert"]


def test_the_same_price_asked_again_would_be_repeated_briefly(wired):
    r = _Redis()
    seen = [{"slug": "cassock", "name": "Cassock"}]
    _turn(r, "how much?", seen=seen, reply="Our cassock is KES 13,000.")
    _turn(r, "how much again?", seen=seen, reply="It is KES 13,000.")
    out = _turn(r, "and the price?", seen=seen, reply="KES 13,000, made to measure.")
    assert out and out[0]["decision"] == "repeat_price"


def test_the_bot_score_reads_the_thread():
    t0 = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(4):
        rows.append(("outbound", t0 + timedelta(minutes=i), "Our cassock is KES 13,000, made to measure in your colour."))
        rows.append(("inbound", t0 + timedelta(minutes=i, seconds=2), "Thank you for contacting us, we will get back to you shortly."))
    score, why = cb.bot_score(rows)
    assert score >= 4 and any("within 4 seconds" in w for w in why) and "auto-reply text" in why
    human = [("outbound", t0, "Which colour would you like?"),
             ("inbound", t0 + timedelta(minutes=3), "Black please, size L")]
    assert cb.bot_score(human) == (0, [])
    echo = [("outbound", t0, "Our cassock is KES 13,000, tailored to your measurements in Nairobi."),
            ("inbound", t0 + timedelta(minutes=1), "Our cassock is KES 13,000 tailored to your measurements in Nairobi")]
    assert "our own words echoed back" in cb.bot_score(echo)[1]
    assert cb.bot_score([], hour_count=40, shared_by=6)[0] >= 4


def test_under_a_post_a_fourth_exchange_would_move_to_dm_and_a_copied_comment_is_spam(wired):
    r = _Redis()
    for i in range(3):
        assert _turn(r, "how much is this lovely cope?", public_comment=True, post_id="p1") == [] or i
    out = _turn(r, "still waiting", public_comment=True, post_id="p1")
    assert out[0]["decision"] == "move_to_dm"
    for post in ("p2", "p3"):
        out = _turn(r, "how much is this lovely cope?", public_comment=True, post_id=post)
    assert any(x["decision"] == "spam" for x in out)


def test_off_and_closers_record_nothing(wired, monkeypatch):
    r = _Redis()
    assert _turn(r, "thanks", closer=True) == []
    monkeypatch.setattr(settings, "pacing_budget_mode", "off", raising=False)
    for _ in range(30):
        assert _turn(r, "chat") == []


def test_the_turn_reply_is_never_touched():
    import inspect
    import app.agent.runtime as runtime
    src = inspect.getsource(runtime.run_turn)
    assert "await _cb.assess(" in src
    i = src.index("await _cb.assess(")
    assert "reply =" not in src[i: i + 600]          # record-only: the reply stands


def test_the_checker_keeps_its_own_models():
    from app.agent import review
    assert review._reviewer_model("hi", "Hello!") == settings.review_model_light == "claude-haiku-4-5"
    assert review._reviewer_model("I have paid", "Thank you") == settings.review_model_main == "claude-sonnet-5"
