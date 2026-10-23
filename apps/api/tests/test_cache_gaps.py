"""The gap tracker: how long each cached prefix waited between uses.

Whether a 1-hour conversation cache saves money or costs more depends only on
these gaps (services/cache_gaps), so the tally must bucket them exactly, sample
a conversation once per turn, and never cost a reply.
"""
import asyncio

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.services import cache_gaps as cg


class _R:
    def __init__(self):
        self.kv, self.h = {}, {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None, nx=None):
        self.kv[k] = v
        return True

    async def hincrby(self, k, f, n):
        self.h.setdefault(k, {})
        self.h[k][f] = self.h[k].get(f, 0) + n

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))

    async def expire(self, k, ttl):
        return True


SYS = ["shared rules", "this customer"]
TOOLS = [{"name": "search_catalog"}]
U = {"input_tokens": 10, "cache_read_tokens": 30000, "cache_write_tokens": 2000}


def _turn(*texts):
    out = []
    for i, t in enumerate(texts):
        out.append({"role": "user" if i % 2 == 0 else "assistant", "content": t})
    return out


def _run(r, msgs, at, purpose="whatsapp", system=SYS, tools=TOOLS):
    asyncio.run(cg.record(purpose, system, msgs, tools, U, redis=r, now=at))


def test_buckets_are_the_cache_ttls():
    assert cg.bucket(None) == "new"
    assert cg.bucket(0) == cg.bucket(299) == "under_5m"
    assert cg.bucket(300) == cg.bucket(3599) == "5m_1h"
    assert cg.bucket(3600) == "over_1h"


def test_a_conversation_is_sampled_once_per_turn_with_its_prompt_tokens():
    r, t0 = _R(), 1_800_000_000.0
    first = _turn("How much is the cope set?")
    _run(r, first, t0)                                            # new conversation
    # the tool loop, seconds later: refreshes the entry, is not a sample
    loop = first + [{"role": "assistant", "content": [{"type": "tool_use", "id": "1"}]},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1"}]}]
    _run(r, loop, t0 + 4)
    _run(r, _turn("How much is the cope set?", "KES 45,000.", "In rands?"), t0 + 4 + 600)   # 10 min
    _run(r, _turn("How much is the cope set?", "KES 45,000.", "In rands?", "R 6,300", "ok"),
         t0 + 604 + 120)                                          # 2 min
    g = asyncio.run(cg.read_gaps(r, now=t0))
    conv = g["conversation"]["whatsapp"]
    assert conv["new"]["calls"] == 1 and conv["5m_1h"]["calls"] == 1
    assert conv["under_5m"]["calls"] == 1 and conv["over_1h"]["calls"] == 0
    assert conv["5m_1h"]["tokens"] == 32010                       # what a 1h entry would have read


def test_the_rules_clock_is_shared_by_every_conversation_of_a_purpose():
    r, t0 = _R(), 1_800_000_000.0
    _run(r, _turn("Hi"), t0, purpose="comment")
    _run(r, _turn("Bei gani?"), t0 + 2 * 3600, purpose="comment")  # another person, 2 h later
    _run(r, _turn("Price?"), t0 + 2 * 3600 + 60, purpose="comment")
    rules = asyncio.run(cg.read_gaps(r, now=t0))["rules"]["comment"]
    assert (rules["new"]["calls"], rules["over_1h"]["calls"], rules["under_5m"]["calls"]) == (1, 1, 1)


def test_different_rules_or_tools_are_different_cache_entries():
    a = cg.keys_for(SYS, _turn("x"), TOOLS)
    assert cg.keys_for(["other rules", "this customer"], _turn("x"), TOOLS)[0] != a[0]
    assert cg.keys_for(SYS, _turn("x"), [{"name": "get_cart"}])[0] != a[0]
    assert cg.keys_for(SYS, _turn("y"), TOOLS)[1] != a[1]           # another conversation
    assert cg.keys_for(["shared rules", "someone else"], _turn("x"), TOOLS)[0] == a[0]


def test_it_never_costs_a_reply():
    class _Broken:
        async def get(self, k): raise RuntimeError("redis down")
    asyncio.run(cg.record("whatsapp", SYS, _turn("hi"), TOOLS, U, redis=_Broken()))
    assert asyncio.run(cg.read_gaps(_Broken())) == {}


def test_the_client_records_every_cached_call():
    import inspect
    from app.agent import llm
    src = inspect.getsource(llm.AnthropicLLM.complete)
    assert "cache_gaps.record" in src
    from app.routers import health
    assert "read_gaps" in inspect.getsource(health)
