"""WHERE THE MONEY WENT (owner, 2026-09-26: "heightened expenditure for a few
days"). Every model call is metered by the LLM client itself, by purpose and
by model, so the daily breaker sees the whole day — the reviewer on every
turn, every rewrite, every comment read, every vision read — and
/api/health says where it went."""
import asyncio
import inspect

import app.main  # noqa: F401
from app.agent import llm as llm_mod
from app.agent import runtime as rt
from app.core.config import settings
from app.services import ai_budget


class _R:
    def __init__(self):
        self.kv: dict = {}
        self.h: dict = {}

    async def get(self, k):
        return self.kv.get(k)

    async def incrbyfloat(self, k, v):
        self.kv[k] = float(self.kv.get(k, 0)) + float(v)
        return self.kv[k]

    async def expire(self, k, ttl):
        return True

    async def hincrbyfloat(self, k, f, v):
        self.h.setdefault(k, {})
        self.h[k][f] = float(self.h[k].get(f, 0)) + float(v)

    async def hincrby(self, k, f, n):
        self.h.setdefault(k, {})
        self.h[k][f] = int(self.h[k].get(f, 0)) + int(n)

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))


def test_every_call_is_metered_by_purpose_and_model():
    r = _R()
    usage = {"input_tokens": 2000, "cache_read_tokens": 20000, "cache_write_tokens": 3000,
             "cache_write_1h_tokens": 0, "output_tokens": 300}
    usd = asyncio.run(ai_budget.meter("claude-sonnet-5", usage, "whatsapp", redis=r))
    # 2000 fresh × $3 + 20000 cached × $0.30 + 3000 written × $3.75 + 300 out × $15, per million
    assert abs(usd - (0.006 + 0.006 + 0.01125 + 0.0045)) < 1e-6
    asyncio.run(ai_budget.meter("claude-haiku-4-5", {"input_tokens": 4000, "output_tokens": 40}, "reviewer", redis=r))
    asyncio.run(ai_budget.meter("claude-sonnet-5", usage, "whatsapp", redis=r))
    total = asyncio.run(ai_budget.spent_today(r))
    b = asyncio.run(ai_budget.read_breakdown(r))
    assert abs(total - (2 * usd + 0.0042)) < 1e-6 and b["today_usd"] == round(total, 2)
    assert list(b["by_purpose"]) == ["whatsapp", "reviewer"]              # dearest first
    w = b["by_purpose"]["whatsapp"]
    assert w["calls"] == 2 and w["in"] == 4000 and w["cached"] == 40000 and w["written"] == 6000 and w["out"] == 600
    assert b["by_purpose"]["reviewer"] == {"usd": 0.0042, "calls": 1, "in": 4000, "cached": 0, "written": 0, "out": 40}
    assert b["by_model"]["claude-sonnet-5"]["calls"] == 2 and b["by_model"]["claude-haiku-4-5"]["calls"] == 1
    assert b["soft_usd"] == float(settings.ai_daily_budget_usd) and b["stop_usd"] == float(settings.ai_daily_stop_usd)
    assert b["mode"] == "ok"
    # no redis anywhere: the cost is still returned, nothing breaks
    assert asyncio.run(ai_budget.meter("claude-sonnet-5", usage, "x", redis=None)) == usd
    assert asyncio.run(ai_budget.read_breakdown(None)) == {}


def test_the_client_meters_itself_and_the_turn_no_longer_meters_twice():
    src = inspect.getsource(llm_mod.AnthropicLLM)
    assert "await ai_budget.meter(self._model, r.usage, self.purpose)" in src
    assert 'purpose: str = "other"' in src
    turn = inspect.getsource(rt.run_turn)
    assert "ai_budget.add_spend(" not in turn                     # the client meters
    assert "await ai_budget.guard_turn(redis)" in turn             # the breaker still guards
    assert 'purpose=getattr(llm, "purpose", "turn")' in turn       # economy mode keeps the label
    assert 'purpose: str = "other"' in inspect.getsource(rt.build_llm)
    # the purposes the day is read by
    whole = inspect.getsource(rt)
    for label in ('purpose="whatsapp"', "purpose=channel", 'purpose="comment"', 'purpose="comment-read"', 'purpose="vision"'):
        assert label in whole, label
    from app.agent import review
    assert 'purpose="reviewer"' in inspect.getsource(review.reviewer_verdict)
    from app.routers import health
    assert 'out["spend"] = spend' in inspect.getsource(health)
    import app.main as m
    assert "_ai_budget.attach(redis)" in inspect.getsource(m)
    from app.services import translate
    assert "ai_budget.add_spend(" not in inspect.getsource(translate)   # metered once, by the client
