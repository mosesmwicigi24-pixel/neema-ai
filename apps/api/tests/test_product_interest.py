"""What "this product" means (owner, 2026-08-19, the +885 thread).

A customer returned: "Is this product now available? Last time we checked it
was yet to be re-stocked" — and Neema, who had handled the original ask,
replied "which item?". Structural cause: the first ask was a PHOTO, and photos
leave no product name in the text history (`_history` skips empty-text rows).
But every turn already collected the hub rows the agent surfaced
(`ctx.seen_products`) — the knowledge existed and evaporated.

These tests pin the durable memory: surfaced products are remembered per
contact with their stock-at-the-time, recalled into every future turn's
per-customer context, written only by REAL turns (never read-only drafts),
and framed so the availability doctrine ("confirmed, never denied") holds.
"""
import asyncio
import types

import app.main  # noqa: F401 — registers models before runtime import
import app.agent.runtime as runtime
from app.services import product_interest as pi


class _Redis:
    def __init__(self, store=None):
        self.kv = dict(store or {})

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    def __getattr__(self, name):
        async def _noop(*a, **kw):
            return None
        return _noop


class _Res:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._many)


class _FakeDB:
    def __init__(self, results):
        self._results, self._i = list(results), 0

    async def execute(self, *a, **k):
        r = self._results[min(self._i, len(self._results) - 1)]
        self._i += 1
        return r


def _turn_db():
    user = types.SimpleNamespace(name="Moses")
    # User, standing-orders, learned-rules, history — then a buffer result for
    # any best-effort tail queries (calls, cross-channel) that slip through.
    return _FakeDB([_Res(one=user), _Res(one=None), _Res(one=None), _Res(many=[])])


THURIBLE = {"name": "Brass Thurible", "slug": "brass-thurible", "in_stock": False,
            "price": 5200}
TRAY = {"name": "Silver Communion Tray", "slug": "silver-tray", "in_stock": True}


# ── the memory itself ────────────────────────────────────────────────────────

def test_remember_then_recall_keeps_stock_at_the_time():
    r = _Redis()
    asyncio.run(pi.remember(r, "whatsapp", "254700000001", [THURIBLE]))
    out = asyncio.run(pi.recall(r, "whatsapp", "254700000001"))
    assert out and out[0]["name"] == "Brass Thurible"
    assert out[0]["in_stock"] is False
    assert out[0]["at"]                       # dated, so the tail can say when


def test_newest_first_deduped_and_capped_at_five():
    r = _Redis()
    for i in range(7):
        asyncio.run(pi.remember(r, "whatsapp", "k", [
            {"name": f"P{i}", "slug": f"p{i}", "in_stock": True}]))
    asyncio.run(pi.remember(r, "whatsapp", "k", [THURIBLE]))
    asyncio.run(pi.remember(r, "whatsapp", "k", [THURIBLE]))     # dupe folds in
    out = asyncio.run(pi.recall(r, "whatsapp", "k"))
    assert len(out) == 5
    assert out[0]["slug"] == "brass-thurible"                     # newest first
    assert len({o["slug"] for o in out}) == 5


def test_rows_without_name_or_slug_never_pollute():
    r = _Redis()
    asyncio.run(pi.remember(r, "whatsapp", "k",
                            [{"name": "", "slug": "x"}, {"name": "Y", "slug": ""},
                             "junk", None]))
    assert asyncio.run(pi.recall(r, "whatsapp", "k")) == []
    assert not r.kv                            # nothing worth writing → no key


def test_memory_never_costs_a_reply():
    class _Broken:
        def __getattr__(self, name):
            async def _boom(*a, **kw):
                raise RuntimeError("redis down")
            return _boom
    asyncio.run(pi.remember(_Broken(), "whatsapp", "k", [THURIBLE]))   # no raise
    assert asyncio.run(pi.recall(_Broken(), "whatsapp", "k")) == []
    assert asyncio.run(pi.recall(None, "whatsapp", "k")) == []


# ── the context block ────────────────────────────────────────────────────────

def test_context_block_marks_out_of_stock_and_teaches_the_resolve():
    txt = pi.context_block([
        {"name": "Brass Thurible", "slug": "brass-thurible", "in_stock": False,
         "at": "2026-08-02"},
        {"name": "Silver Communion Tray", "slug": "silver-tray", "in_stock": True,
         "at": "2026-07-30"},
    ])
    assert "PRODUCTS RECENTLY DISCUSSED WITH THIS CUSTOMER" in txt
    assert "Brass Thurible — was OUT OF STOCK when last discussed (2026-08-02)" in txt
    assert "Silver Communion Tray (2026-07-30)" in txt
    assert "Do NOT ask them to re-explain from nothing" in txt
    # the availability doctrine survives — never "tell them it's out of stock"
    assert "confirmed, never denied" in txt
    assert pi.context_block([]) == ""


def test_the_shared_rules_carry_the_unnamed_referent_rule():
    from app.agent.prompt import build_system_prompt
    flat = " ".join(build_system_prompt(country_iso="KE", currency="KES").split())
    assert '"THIS PRODUCT", UNNAMED' in flat
    assert "The newest matching entry IS what they mean" in flat
    assert "never make them re-explain what we once discussed" in flat


# ── the runtime loop: remember on real turns, recall into the tail ───────────

def test_a_real_turn_remembers_what_search_catalog_surfaced(monkeypatch):
    async def fake_run_tool(name, args, ctx):
        ctx.seen_products.append(THURIBLE)     # what _search_catalog does on match
        return {"count": 1, "results": [{"name": "Brass Thurible", "price": 5200}]}
    monkeypatch.setattr(runtime, "run_tool", fake_run_tool)

    from app.agent.llm import FakeLLM
    llm = FakeLLM([
        {"tools": [{"name": "search_catalog", "input": {"query": "thurible"}}]},
        {"text": "Let me confirm that with our team and come right back to you."},
    ])
    r = _Redis()
    asyncio.run(runtime.run_turn(_turn_db(), r, "254700000001",
                                 "do you have this?", llm))
    out = asyncio.run(pi.recall(r, "whatsapp", "254700000001"))
    assert out and out[0]["slug"] == "brass-thurible"


def test_a_read_only_draft_never_writes_the_record(monkeypatch):
    async def fake_run_tool(name, args, ctx):
        ctx.seen_products.append(THURIBLE)
        return {"count": 1, "results": []}
    monkeypatch.setattr(runtime, "run_tool", fake_run_tool)
    from app.agent.llm import FakeLLM
    llm = FakeLLM([
        {"tools": [{"name": "search_catalog", "input": {"query": "thurible"}}]},
        {"text": "draft"},
    ])
    r = _Redis()
    asyncio.run(runtime.run_turn(_turn_db(), r, "254700000001", "hi", llm,
                                 read_only=True))
    assert asyncio.run(pi.recall(r, "whatsapp", "254700000001")) == []


def test_the_next_turn_reads_the_memory_in_its_tail(monkeypatch):
    seen = {}

    class _RecLLM:
        async def complete(self, *, system, messages, tools):
            seen["system"] = system
            return types.SimpleNamespace(text="You asked about the Brass Thurible —",
                                         tool_calls=[], assistant_content=[], usage={})

    r = _Redis()
    asyncio.run(pi.remember(r, "whatsapp", "254700000001", [THURIBLE]))
    asyncio.run(runtime.run_turn(_turn_db(), r, "254700000001",
                                 "is this product now available?", _RecLLM()))
    sys_blocks = seen["system"]
    tail = sys_blocks[1] if isinstance(sys_blocks, list) and len(sys_blocks) > 1 else ""
    assert "Brass Thurible — was OUT OF STOCK when last discussed" in tail
    assert "PRODUCTS RECENTLY DISCUSSED" in tail
