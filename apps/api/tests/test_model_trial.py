"""The usage review (owner, 2026-10-30: "check the usage and advise,
maintaining … intelligence, empathy, smartness and alert and humanness";
then "go ahead with all"):

- the meter priced Sonnet 5 at $3/$15 — Anthropic's standard price is
  $2/$10 — so the $40 economy rung moved customers to the light model at
  ~$27 of real spend;
- half the replies were rewritten — the gate now counts WHICH check fired;
- the 5.5 generation as a trial: same care (Sonnet 5.5 at `high`), thinking
  passed back unchanged, room for it in max_tokens, and a refused or rejected
  request answered on the previous model — never a silent customer.
"""
import asyncio
import types

import pytest

import app.main  # noqa: F401 — registers models before runtime import
from app.agent import llm as llm_mod, review
from app.core.ai_pricing import estimate_cost_usd
from app.core.config import Settings, settings


def test_the_meter_prices_at_anthropics_standard_rates():
    # 1M fresh in + 1M out
    assert estimate_cost_usd("claude-sonnet-5", 1_000_000, 1_000_000) == pytest.approx(12.0)
    assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.0)
    assert estimate_cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.6)
    # cache reads: $0.20 on Sonnet 5, half that on Sonnet 5.5
    assert estimate_cost_usd("claude-sonnet-5", 1_000_000, 0, cached_tokens=1_000_000) == pytest.approx(0.2)
    assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 0, cached_tokens=1_000_000) == pytest.approx(0.1)
    # writes: 1.25x (5 min) and 2x (1 h) of input
    assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 0, cache_write_tokens=1_000_000) == pytest.approx(2.5)
    assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 0, cache_write_tokens=1_000_000,
                             cache_write_1h_tokens=1_000_000) == pytest.approx(4.0)


def test_the_trial_defaults_and_their_way_back():
    f = Settings.model_fields
    assert f["tier2_model"].default == "claude-sonnet-5-5"
    assert f["tier2_model_light"].default == "claude-haiku-5-5"
    assert f["tier2_max_tokens"].default >= 4096
    assert llm_mod.fallback_model("claude-sonnet-5-5") == "claude-sonnet-5"
    assert llm_mod.fallback_model("claude-haiku-5-5") == "claude-haiku-4-5"
    assert llm_mod.fallback_model("claude-sonnet-5") is None


def test_each_model_is_asked_for_what_it_takes():
    assert llm_mod._model_params("claude-sonnet-5-5") == {"output_config": {"effort": "high"}}
    assert llm_mod._model_params("claude-haiku-5-5") == {"output_config": {"effort": "low"}}
    assert llm_mod._model_params("claude-haiku-4-5") == {}       # rejects effort
    assert llm_mod._model_params("claude-sonnet-5") == {}


def test_thinking_is_passed_back_unchanged_and_never_read_as_words():
    blocks = [types.SimpleNamespace(type="thinking", thinking="", signature="sig-1"),
              types.SimpleNamespace(type="text", text="Our cassock is KES 13,000."),
              {"type": "redacted_thinking", "data": "xyz"},
              types.SimpleNamespace(type="tool_use", id="t1", name="search_catalog", input={"q": "x"})]
    r = llm_mod._blocks_to_response(blocks)
    assert r.assistant_content[0] == {"type": "thinking", "thinking": "", "signature": "sig-1"}
    assert {"type": "redacted_thinking", "data": "xyz"} in r.assistant_content
    assert r.text == "Our cassock is KES 13,000." and r.tool_calls[0].name == "search_catalog"
    words = review.transcript_text([{"role": "assistant", "content": r.assistant_content}])
    assert words == [("assistant", "Our cassock is KES 13,000.")]


class _Client:
    """messages.create: scripted per model — an exception, or a response."""
    def __init__(self, script):
        self.script, self.calls = script, []
        self.messages = self

    async def create(self, **kw):
        self.calls.append(kw)
        out = self.script[kw["model"]]
        if isinstance(out, Exception):
            raise out
        return out


def _resp(text="Hello Pastor!", stop="end_turn"):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)], stop_reason=stop,
        stop_details=types.SimpleNamespace(category="general_harms") if stop == "refusal" else None,
        usage=types.SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                    cache_creation_input_tokens=0, cache_creation=None))


def _llm(client, model="claude-sonnet-5-5"):
    x = llm_mod.AnthropicLLM.__new__(llm_mod.AnthropicLLM)
    x._client, x._model, x._max_tokens, x._cache, x.purpose = client, model, 4096, False, "t"
    return x


def _metered(monkeypatch):
    seen = []

    async def _meter(model, usage, purpose="other", redis=None):
        seen.append(model)
        return 0.0
    monkeypatch.setattr("app.services.ai_budget.meter", _meter)
    return seen


def test_a_rejected_request_is_answered_on_the_previous_model(monkeypatch):
    from anthropic import BadRequestError
    seen = _metered(monkeypatch)
    bad = BadRequestError.__new__(BadRequestError)
    c = _Client({"claude-sonnet-5-5": bad, "claude-sonnet-5": _resp("Karibu sana!")})
    x = _llm(c)
    r = asyncio.run(x.complete(system="S", messages=[{"role": "user", "content": "hi"}], tools=[]))
    assert r.text == "Karibu sana!" and x.last_model == "claude-sonnet-5"
    assert [k["model"] for k in c.calls] == ["claude-sonnet-5-5", "claude-sonnet-5"]
    assert c.calls[0]["output_config"] == {"effort": "high"} and "output_config" not in c.calls[1]
    assert seen == ["claude-sonnet-5"]


def test_a_refusal_is_answered_on_the_previous_model_and_both_are_metered(monkeypatch):
    seen = _metered(monkeypatch)
    c = _Client({"claude-haiku-5-5": _resp("", stop="refusal"), "claude-haiku-4-5": _resp("You're welcome!")})
    x = _llm(c, "claude-haiku-5-5")
    r = asyncio.run(x.complete(system="S", messages=[{"role": "user", "content": "thanks"}], tools=[]))
    assert r.text == "You're welcome!" and seen == ["claude-haiku-5-5", "claude-haiku-4-5"]


def test_a_model_with_no_fallback_still_raises(monkeypatch):
    from anthropic import BadRequestError
    _metered(monkeypatch)
    bad = BadRequestError.__new__(BadRequestError)
    x = _llm(_Client({"claude-sonnet-5": bad}), "claude-sonnet-5")
    with pytest.raises(BadRequestError):
        asyncio.run(x.complete(system="S", messages=[{"role": "user", "content": "hi"}], tools=[]))


# ── why replies are rewritten, and each model's pass rate ───────────────────

class _Redis:
    def __init__(self):
        self.h = {}

    async def hincrby(self, key, field, n):
        self.h.setdefault(key, {}).setdefault(field, 0)
        self.h[key][field] += n

    async def expire(self, *a):
        return True

    async def hgetall(self, key):
        return dict(self.h.get(key, {}))


def test_the_gate_counts_which_check_fired_and_each_models_pass_rate():
    r = _Redis()
    for outcome, kinds, model in (("pass", (), "claude-sonnet-5-5"),
                                  ("pass", (), "claude-sonnet-5-5"),
                                  ("soft", ("reviewer",), "claude-sonnet-5-5"),
                                  ("rewritten", ("figures", "reviewer"), "claude-sonnet-5"),
                                  ("pass", (), "claude-sonnet-5")):
        asyncio.run(review.record_verdict(r, outcome, "messenger", kinds=kinds, model=model))
    view = review.verdict_view(asyncio.run(review.read_verdicts(r)))
    assert (view["passed"], view["rewritten"], view["soft"]) == (3, 1, 1)
    assert list(view["findings"]) == ["reviewer", "figures"] and view["findings"]["reviewer"] == 2
    assert view["by_model"]["claude-sonnet-5-5"]["first_draft_pass_pct"] == pytest.approx(66.7)
    assert view["by_model"]["claude-sonnet-5"]["first_draft_pass_pct"] == pytest.approx(50.0)


def test_the_review_names_its_checks():
    out = asyncio.run(review.review_reply("how much is the cope?", "The Cope is $999.", [],
                                          model_review=False))
    assert not out["ok"] and out["kinds"] and all(isinstance(k, str) for k in out["kinds"])
    ok = asyncio.run(review.review_reply("thanks", "You're welcome, God bless!", [], model_review=False))
    assert ok["ok"] and ok["kinds"] == []


def test_the_settings_object_matches_the_defaults():
    # a deploy with no env override runs the trial
    assert settings.model_fallbacks.startswith("claude-sonnet-5-5:claude-sonnet-5")
