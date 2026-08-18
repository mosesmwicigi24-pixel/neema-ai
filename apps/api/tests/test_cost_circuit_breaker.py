"""The cost-surprise probe (owner, 2026-08-18): "examine and probe for any
failure to ensure we don't get cost spending surprises."

The audit walked every model call site and found the system full of per-SCOPE
guards (per call, per turn, per post, per message) but nothing per-DAY — and
two genuine infinite loops where a BILLED compose whose delivery then failed
was quietly regenerated on a timer:

  · reply_sweeper: a stuck Meta DM re-ran a full model turn every ~5 minutes
    for up to 23 hours (~276 turns) when delivery failed for any non-window
    reason (dead page token, blocked sender).
  · actions.process_due: a follow-up whose send raised stayed `planned` and
    was recomposed every 60 seconds — a model turn a minute, forever.

These tests pin the fixes: a daily spend breaker (economy → light model,
stop → refuse before buying a token, riding the proven out-of-credit failure
path), three-strike bounds on both loops, and pricing that can never
under-report an unknown model.
"""
import asyncio
import types

import pytest

import app.agent.runtime as runtime
from app.agent.llm import FakeLLM, LLMResponse
from app.core.config import settings
from app.services import ai_budget


# ── minimal fakes (patterns from test_agent_flow) ────────────────────────────

class _Res:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._many)

    def all(self):
        return self._many


class _FakeDB:
    def __init__(self, results, gets=None):
        self._results, self._i = list(results), 0
        self._gets = gets or {}

    async def execute(self, *a, **k):
        r = self._results[self._i]
        self._i += 1
        return r

    async def get(self, model, _id):
        return self._gets.get(model.__name__)

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _Redis:
    """Just enough redis: a dict + the calls the breaker and bounds use.
    Anything else the code touches resolves to a harmless async no-op."""

    def __init__(self, store=None):
        self.kv = dict(store or {})

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]

    async def incrbyfloat(self, k, v):
        self.kv[k] = float(self.kv.get(k, 0.0)) + float(v)
        return self.kv[k]

    async def expire(self, k, s):
        return True

    def __getattr__(self, name):
        async def _noop(*a, **kw):
            return None
        return _noop


def _day_key() -> str:
    return ai_budget._day_key()


def _turn_db():
    # run_turn's per-turn queries: User, standing-orders, learned-rules, history.
    user = types.SimpleNamespace(name="Moses")
    return _FakeDB([_Res(one=user), _Res(one=None), _Res(one=None), _Res(many=[])])


# ── the meter ────────────────────────────────────────────────────────────────

def test_spend_accumulates_per_utc_day():
    r = _Redis()
    asyncio.run(ai_budget.add_spend(r, 0.031))
    asyncio.run(ai_budget.add_spend(r, 0.02))
    assert asyncio.run(ai_budget.spent_today(r)) == pytest.approx(0.051)
    # zero/negative/None never touch the counter
    asyncio.run(ai_budget.add_spend(r, 0))
    asyncio.run(ai_budget.add_spend(None, 5.0))
    assert asyncio.run(ai_budget.spent_today(r)) == pytest.approx(0.051)


def test_mode_ladder_ok_economy_stop():
    assert asyncio.run(ai_budget.mode(_Redis({_day_key(): "10.0"}))) == "ok"
    assert asyncio.run(ai_budget.mode(_Redis({_day_key(): "45.0"}))) == "economy"
    assert asyncio.run(ai_budget.mode(_Redis({_day_key(): "60.0"}))) == "stop"


def test_a_zero_rung_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ai_daily_stop_usd", 0.0)
    assert asyncio.run(ai_budget.mode(_Redis({_day_key(): "999"}))) == "economy"
    monkeypatch.setattr(settings, "ai_daily_budget_usd", 0.0)
    assert asyncio.run(ai_budget.mode(_Redis({_day_key(): "999"}))) == "ok"


def test_the_breaker_fails_open():
    """A redis hiccup must cost a metric, never a sale — the worst day this
    module may cause is one where it did nothing."""
    class _Broken:
        def __getattr__(self, name):
            async def _boom(*a, **kw):
                raise RuntimeError("redis down")
            return _boom
    assert asyncio.run(ai_budget.mode(None)) == "ok"
    assert asyncio.run(ai_budget.mode(_Broken())) == "ok"
    asyncio.run(ai_budget.add_spend(_Broken(), 1.0))      # must not raise


# ── the gates inside run_turn ────────────────────────────────────────────────

def test_run_turn_refuses_before_buying_a_single_token_at_the_stop():
    r = _Redis({_day_key(): "75.0"})
    llm = FakeLLM([{"text": "this must never be produced"}])
    with pytest.raises(ai_budget.DailyBudgetExceeded):
        asyncio.run(runtime.run_turn(_turn_db(), r, "254700000001", "hello", llm))
    assert llm._i == 0, "the model was consulted despite the stop"


def test_the_stop_reads_as_budget_on_the_health_card():
    """The refusal rides the same path as an out-of-credit day — so the health
    classifier must name it correctly, mark it actionable, and never confuse
    it with a real billing failure."""
    from app.services.agent_health import ACTIONABLE, classify, describe
    exc = ai_budget.DailyBudgetExceeded(ai_budget.exceeded_message(61.2, 60.0))
    assert classify(exc) == "budget"
    assert "budget" in ACTIONABLE
    line = describe({"kind": "budget", "count": 7, "error": str(exc)})
    assert "ceiling" in line and "AI_DAILY_STOP_USD" in line


def test_run_turn_downgrades_to_the_light_model_in_economy(monkeypatch):
    seen = {}

    def _fake_build(model=None):
        seen["model"] = model
        return FakeLLM([{"text": "answered on the light model"}])

    monkeypatch.setattr(runtime, "build_llm", _fake_build)

    class _MainLLM:                        # what a caller built before the gate
        _model = settings.tier2_model

        async def complete(self, **kw):
            raise AssertionError("main model used past the soft budget")

    out = asyncio.run(runtime.run_turn(
        _turn_db(), _Redis({_day_key(): "45.0"}), "254700000001", "hello", _MainLLM()))
    assert out == "answered on the light model"
    assert seen["model"] == settings.tier2_model_light


def test_under_budget_nothing_changes():
    llm = FakeLLM([{"text": "normal day, normal answer"}])
    out = asyncio.run(runtime.run_turn(
        _turn_db(), _Redis({_day_key(): "3.5"}), "254700000001", "hello", llm))
    assert out == "normal day, normal answer"


def test_every_metered_turn_feeds_the_day_counter():
    """The breaker is only as good as its meter: the turn's estimated cost
    (same table as the standup) must land in today's counter even when the
    DB-side usage row fails — a down database must never blind the breaker."""
    class _UsageLLM:
        _model = "claude-sonnet-5"

        async def complete(self, **kw):
            return LLMResponse(
                assistant_content=[{"type": "text", "text": "ok"}], text="ok",
                usage={"input_tokens": 1000, "output_tokens": 100,
                       "cache_read_tokens": 9000, "cache_write_tokens": 0,
                       "cache_write_1h_tokens": 0})

    r = _Redis()
    asyncio.run(runtime.run_turn(_turn_db(), r, "254700000001", "hello", _UsageLLM()))
    # 1000 fresh @ $3/M + 9000 cache-read @ $0.30/M + 100 out @ $15/M
    assert r.kv[_day_key()] == pytest.approx(0.0072)


def test_comment_labeler_skips_the_model_under_stop(monkeypatch):
    """Under a stop the whole comment funnel must run at $0: the labeler falls
    to its uncertainty default without a call, and the canned sell pools
    (real product, real price) carry the replies."""
    def _no_build(model=None):
        raise AssertionError("labeler called the model during a budget stop")
    monkeypatch.setattr(runtime, "build_llm", _no_build)
    out = asyncio.run(runtime.classify_comment_intent(
        "how much for the chasuble?", redis=_Redis({_day_key(): "80.0"})))
    assert out == "high"


# ── pricing can never under-report ──────────────────────────────────────────

def test_an_unknown_model_bills_at_sonnet_class_rates():
    """A renamed/new model must trip the breaker EARLY, never slip under it:
    under-reporting is the exact blindness the breaker exists to prevent."""
    from app.core.ai_pricing import estimate_cost_usd
    unknown = estimate_cost_usd("claude-totally-new-9", 1_000_000, 1_000_000)
    sonnet = estimate_cost_usd("claude-sonnet-5", 1_000_000, 1_000_000)
    assert unknown >= sonnet == pytest.approx(18.0)


# ── the sweeper's three strikes ──────────────────────────────────────────────

def _sweep_fixtures():
    from app.models.message import MsgDirection
    msg = types.SimpleNamespace(id=42, text="where is my order?", media_type=None,
                                media_url=None, external_id="psid1", created_at=None)
    conv = types.SimpleNamespace(channel="messenger", wa_id=None,
                                 external_id="psid1", person_id=None)
    sessions = [
        _FakeDB([_Res(many=[(msg, conv)])]),                       # the sweep query
        _FakeDB([_Res(one=MsgDirection.inbound), _Res(one=None)]),  # recheck + page id
    ]

    class _Sess:
        def __init__(self):
            self.db = sessions.pop(0)

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *a):
            return False
    return _Sess


def test_sweeper_gives_up_after_three_attempts(monkeypatch):
    import app.services.reply_sweeper as sweeper
    monkeypatch.setattr(sweeper, "AsyncSessionLocal", _sweep_fixtures())
    escalated, ran = [], []

    async def _esc(channel, ext, note):
        escalated.append((channel, ext, note))
        return True

    async def _run(*a, **kw):
        ran.append(a)
        return True

    async def _not_paused(*a, **kw):
        return False
    monkeypatch.setattr(runtime, "escalate_to_human", _esc)
    monkeypatch.setattr(runtime, "_run_and_send_meta", _run)
    monkeypatch.setattr(runtime, "_is_paused", _not_paused)

    r = _Redis({"agent:missed:tries:42": 3})       # three strikes already burned
    sent = asyncio.run(sweeper.sweep_missed_replies(r))
    assert sent == 0
    assert not ran, "a 4th model turn was generated for an undeliverable thread"
    assert escalated and escalated[0][0] == "messenger"
    assert "3 times" in escalated[0][2]


def test_sweeper_still_tries_while_strikes_remain(monkeypatch):
    import app.services.reply_sweeper as sweeper
    monkeypatch.setattr(sweeper, "AsyncSessionLocal", _sweep_fixtures())
    ran = []

    async def _run(*a, **kw):
        ran.append(a)
        return True

    async def _not_paused(*a, **kw):
        return False
    monkeypatch.setattr(runtime, "_run_and_send_meta", _run)
    monkeypatch.setattr(runtime, "_is_paused", _not_paused)

    r = _Redis()                                    # first attempt ever
    sent = asyncio.run(sweeper.sweep_missed_replies(r))
    assert sent == 1 and len(ran) == 1
    assert r.kv["agent:missed:tries:42"] == 1


# ── the actions scheduler's three strikes ────────────────────────────────────

def _action_world(monkeypatch, *, tries_burned: int):
    import app.services.actions as actions
    import app.services.hub_events as hub_events
    from datetime import datetime, timezone

    action = types.SimpleNamespace(
        id=7, status="planned", conversation_id=1, deal_id=None,
        due_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reason="deliver follow-up", draft="", kind="fit_check")
    conv = types.SimpleNamespace(id=1, channel="whatsapp", wa_id="254700000001",
                                 external_id=None, contact_name="Moses")
    db = _FakeDB([_Res(many=[action])], gets={"Conversation": conv, "Deal": None})

    monkeypatch.setattr(hub_events, "is_quiet_hours", lambda *a, **k: False)

    async def _in_window(*a, **k):
        return True
    monkeypatch.setattr(hub_events, "_within_window", _in_window)

    async def _no_gate(*a, **k):
        return None
    monkeypatch.setattr(actions, "needs_approval", _no_gate)
    monkeypatch.setattr(settings, "agent_initiative", True)

    composed, sent_out = [], []

    async def _compose(*a, **k):
        composed.append(a)
        return "A warm follow-up about your order."
    monkeypatch.setattr(actions, "_compose_follow_up", _compose)

    async def _never_repeats(*a, **k):
        return False
    monkeypatch.setattr(actions, "_repeats_earlier", _never_repeats)

    async def _send(*a, **k):
        sent_out.append(a)
    monkeypatch.setattr(actions, "_send", _send)

    r = _Redis({"actions:tries:7": tries_burned} if tries_burned else None)
    return actions, db, r, action, composed, sent_out


def test_a_failing_action_parks_for_a_human_after_three_attempts(monkeypatch):
    actions, db, r, action, composed, _ = _action_world(monkeypatch, tries_burned=3)
    done = asyncio.run(actions.process_due(db, r))
    assert done == 0
    assert not composed, "a 4th billed compose for an action that keeps failing"
    assert action.status == "needs_approval"
    assert "needs a human" in action.reason


def test_a_healthy_action_still_flows_and_counts_one_try(monkeypatch):
    actions, db, r, action, composed, sent_out = _action_world(monkeypatch, tries_burned=0)
    done = asyncio.run(actions.process_due(db, r))
    assert done == 1 and len(composed) == 1 and len(sent_out) == 1
    assert action.status == "sent"
    assert r.kv["actions:tries:7"] == 1
