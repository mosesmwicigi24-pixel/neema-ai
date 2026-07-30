"""Phase E — standing orders: the owner's live steering wheel."""
import asyncio
import types

from app.agent.prompt import build_system_prompt
from app.services.app_settings import (get_directives, set_directives,
                                       DIRECTIVES_MAX_CHARS)


class _Res:
    def __init__(self, one=None): self._one = one
    def scalar_one_or_none(self): return self._one


class _DB:
    def __init__(self, row=None):
        self.row, self.added, self.commits = row, [], 0
    async def execute(self, *a, **k): return _Res(one=self.row)
    def add(self, o): self.added.append(o)
    async def commit(self): self.commits += 1


class _Redis:
    def __init__(self): self.store = {}
    async def get(self, k): return self.store.get(k)
    async def set(self, k, v, ex=None): self.store[k] = v


def test_prompt_injects_standing_orders_with_precedence_guard():
    p = build_system_prompt(currency="KES", directives="Push copes this week")
    assert "STANDING ORDERS FROM THE TEAM" in p
    assert "Push copes this week" in p
    assert "NEVER overrides the pricing, payment, stock or safety rules" in p
    # empty directives → no block at all
    assert "STANDING ORDERS" not in build_system_prompt(currency="KES")


def test_directives_are_hard_capped():
    long = "x" * 2000
    p = build_system_prompt(currency="USD", directives=long)
    assert "x" * 600 in p and "x" * 601 not in p


def test_get_directives_cache_first_then_db_then_fills_cache():
    r = _Redis()
    row = types.SimpleNamespace(value="Quote 3-week lead times")
    db = _DB(row=row)
    out = asyncio.run(get_directives(db, r))
    assert out == "Quote 3-week lead times"
    assert r.store["app:directives"] == out          # cache filled
    # cache now wins even if DB changes
    row.value = "changed"
    assert asyncio.run(get_directives(db, r)) == "Quote 3-week lead times"


def test_get_directives_never_breaks_a_reply():
    class _BadDB:
        async def execute(self, *a, **k): raise RuntimeError("db down")
    assert asyncio.run(get_directives(_BadDB(), None)) == ""


def test_set_directives_trims_caps_and_updates_cache():
    r = _Redis()
    db = _DB(row=None)
    out = asyncio.run(set_directives(db, r, "  hello  " + "y" * 2000))
    assert out.startswith("hello")
    assert len(out) <= DIRECTIVES_MAX_CHARS
    assert db.added and db.commits == 1
    assert r.store["app:directives"] == out


def test_directives_routes_registered():
    from app.routers.crm import router
    paths = {(rt.path, tuple(sorted(rt.methods or []))) for rt in router.routes}
    assert ("/settings/directives", ("GET",)) in paths
    assert ("/settings/directives", ("PUT",)) in paths
