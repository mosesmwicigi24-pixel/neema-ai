"""Make every turn cheaper without changing a word the model reads.

Measured before this change: ~10.4k tokens of prefix (7.5k system prompt + 3k
tool schemas) in front of every turn — and because the customer's NAME was
interpolated at the TOP of the system prompt, that whole prefix was distinct
per customer. The prompt cache never shared it: nearly every conversation paid
a full ~10k-token cache WRITE (1.25×) instead of a read (0.1×), and after any
5-minute quiet gap it paid again. The write was ~3¢ of a ~4.5¢ turn.

The fix is structural, not editorial: the rules block is now byte-identical
fleet-wide (per market bucket) and cached at a 1-hour TTL that outlives the
gaps BETWEEN customers, while everything about THIS customer — name, country,
call summaries, cross-channel history, deal guidance — rides in a second,
uncached system block behind it. Same words reach the model, reordered; the
per-conversation breakpoint on the newest message still covers the tail.

The same outage that taught us to watch for failures taught us to watch spend:
1h writes bill at 2× (not 1.25×), so pricing telemetry learned the split, and
the morning standup now says what the brain cost yesterday.
"""
import asyncio
import types

import pytest

from app.agent import llm as llm_mod
from app.agent.prompt import build_system_prompt, customer_context


# ── the rules block can no longer carry customer bytes ───────────────────────

def test_rules_block_cannot_take_customer_bytes():
    """The old signature accepted customer_name/country and interpolated them at
    the top of the prompt — one name cost the fleet-wide cache. The invariant is
    now enforced by the API surface itself."""
    with pytest.raises(TypeError):
        build_system_prompt(customer_name="Moses", currency="KES")
    with pytest.raises(TypeError):
        build_system_prompt(country="Kenya", currency="KES")


def test_rules_block_is_byte_identical_across_calls():
    a = build_system_prompt(country_iso="KE", currency="KES")
    b = build_system_prompt(country_iso="KE", currency="KES")
    assert a == b
    assert "SELL LIKE A CONSULTANT" in a          # the rules are all still there
    assert "You are speaking with" not in a       # the customer is not


def test_customer_context_carries_the_moved_lines():
    t = customer_context("Pastor Moses", "Kenya")
    assert "THIS CUSTOMER" in t
    assert "You are speaking with Pastor Moses." in t
    assert "They appear to be in Kenya." in t
    assert customer_context("", "") == ""         # unknown visitor → no block


# ── cache breakpoints: shared prefix at 1h, tail unmarked ────────────────────

def test_string_system_keeps_the_5_minute_breakpoint():
    """Single-string callers (classifier, drafts, distillation) are unchanged."""
    out = llm_mod._cached_system("You label comments precisely.")
    assert out == [{"type": "text", "text": "You label comments precisely.",
                    "cache_control": {"type": "ephemeral"}}]


def test_split_system_caches_block0_at_1h_and_leaves_the_tail_unmarked():
    out = llm_mod._cached_system(["RULES", "", "THIS CUSTOMER\n- Moses"])
    assert [b["text"] for b in out] == ["RULES", "THIS CUSTOMER\n- Moses"]
    assert out[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    # No marker on the tail: the per-conversation breakpoint on the newest
    # message covers it, and 1h entries must precede 5m ones anyway.
    assert "cache_control" not in out[1]


# ── run_turn actually sends the split ────────────────────────────────────────

def test_run_turn_sends_shared_rules_and_customer_tail_separately():
    import app.agent.runtime as runtime
    seen = {}

    class _RecLLM:
        async def complete(self, *, system, messages, tools):
            seen["system"] = system
            return types.SimpleNamespace(text="Karibu!", tool_calls=[],
                                         assistant_content=[], usage={})

    class _Res:
        def __init__(self, one=None, many=None):
            self._one, self._many = one, many or []
        def scalar_one_or_none(self): return self._one
        def scalars(self): return types.SimpleNamespace(all=lambda: self._many)

    class _FakeDB:
        def __init__(self, results): self._r, self._i = list(results), 0
        async def execute(self, *a, **k):
            r = self._r[self._i]; self._i += 1; return r

    # A name the rules text can't contain by coincidence (the prompt's own
    # examples legitimately say "Pastor Moses").
    user = types.SimpleNamespace(name="Zablon Wanjiru")
    db = _FakeDB([_Res(one=user), _Res(one=None), _Res(one=None), _Res(many=[])])
    out = asyncio.run(runtime.run_turn(db, None, "254700000001",
                                       "Habari, niaje", _RecLLM()))
    assert out == "Karibu!"
    rules, tail = seen["system"]                   # exactly two blocks
    assert "SELL LIKE A CONSULTANT" in rules
    assert "Zablon" not in rules                   # shared block stays shareable
    assert "You are speaking with" not in rules
    assert "THIS CUSTOMER" in tail and "Zablon Wanjiru" in tail
    assert "Kenya" in tail                         # +254 → they appear to be in Kenya


# ── billing honesty: 1h writes cost 2×, not 1.25× ────────────────────────────

def test_1h_cache_writes_bill_at_2x():
    from app.core.ai_pricing import estimate_cost_usd
    # Sonnet 5: $3/MTok input. 10k tokens all written to cache:
    assert estimate_cost_usd("claude-sonnet-5", 10_000, 0,
                             cache_write_tokens=10_000) == 0.0375           # 1.25×
    assert estimate_cost_usd("claude-sonnet-5", 10_000, 0,
                             cache_write_tokens=10_000,
                             cache_write_1h_tokens=10_000) == 0.06          # 2×
    # Mixed write: 6k at 1h + 4k at 5m.
    assert estimate_cost_usd("claude-sonnet-5", 10_000, 0,
                             cache_write_tokens=10_000,
                             cache_write_1h_tokens=6_000) == 0.051
    # A 1h figure larger than the total write is clamped, never double-billed.
    assert estimate_cost_usd("claude-sonnet-5", 10_000, 0,
                             cache_write_tokens=10_000,
                             cache_write_1h_tokens=99_000) == 0.06


def test_turn_totals_carry_the_1h_split():
    """run_turn's accumulator must sum the new usage key, or telemetry
    silently under-bills every shared-prefix write."""
    import inspect
    import app.agent.runtime as runtime
    src = inspect.getsource(runtime.run_turn)
    assert "cache_write_1h_tokens" in src


# ── the owner sees the spend every morning ───────────────────────────────────

def _standup_db(spend_row):
    class _R:
        def __init__(self, scalar=None, many=None, row=None):
            self._s, self._m, self._row = scalar, many or [], row
        def scalar_one(self): return self._s
        def scalars(self): return types.SimpleNamespace(all=lambda: self._m)
        def one(self): return self._row

    class _FakeDB:
        def __init__(self, results): self._r, self._i = list(results), 0
        async def execute(self, *a, **k):
            r = self._r[self._i]; self._i += 1; return r
    # convs, won, approvals, findings, then the spend row; the health and
    # demand queries fall off the end and their try/except absorbs it.
    return _FakeDB([_R(scalar=7), _R(scalar=2), _R(scalar=0), _R(many=[]),
                    _R(row=spend_row)])


def test_standup_reports_yesterdays_ai_spend():
    from app.jobs.self_qa import compose_standup
    out = asyncio.run(compose_standup(_standup_db((1.234, 56))))
    assert "AI spend: $1.23 across 56 model call(s)." in out


def test_standup_stays_quiet_when_nothing_was_spent():
    from app.jobs.self_qa import compose_standup
    out = asyncio.run(compose_standup(_standup_db((0, 0))))
    assert "AI spend" not in out
