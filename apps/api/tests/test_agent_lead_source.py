"""Tests for the `set_lead_source` agent tool — normalizer + persistence wiring.

Covers the pure alias/normalizer directly and the handler against a lightweight
fake db+user (mirroring test_agent_memory.py). Requires Python 3.11 (models).
"""
import asyncio
import types

import app.main  # noqa: F401  — registers all SQLAlchemy models (User() needs the full mapper)
from app.agent.tools import run_tool, ToolContext, _norm_source
from app.models.user import User


# ── pure normalizer ──────────────────────────────────────────────────────────

def test_norm_source_maps_aliases():
    assert _norm_source("FB") == "facebook"
    assert _norm_source("ig") == "instagram"
    assert _norm_source("Tik Tok") == "tiktok"
    assert _norm_source("a friend") == "a_friend"      # unknown → spaced→underscore
    assert _norm_source("referred") == "referral"
    assert _norm_source("  Facebook ") == "facebook"
    assert _norm_source("") == "other"


# ── handler wiring against a fake db+user ─────────────────────────────────────

class _Res:
    def __init__(self, one=None):
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class _FakeDB:
    def __init__(self, results):
        self._results, self._i = list(results), 0
        self.commits = 0

    async def execute(self, *a, **k):
        r = self._results[self._i]
        self._i += 1
        return r

    async def commit(self):
        self.commits += 1


def test_set_lead_source_persists_normalized():
    user = User(state={})
    db = _FakeDB([_Res(one=user)])
    ctx = ToolContext(db=db, redis=None, wa_id="254700000001")

    out = asyncio.run(run_tool("set_lead_source", {"source": "Tik Tok"}, ctx))
    assert out == {"ok": True, "lead_source": "tiktok"}
    assert user.state["lead_source"] == "tiktok"
    assert db.commits == 1


def test_set_lead_source_no_user_is_noop():
    db = _FakeDB([_Res(one=None)])
    ctx = ToolContext(db=db, redis=None, wa_id="254700000001")
    out = asyncio.run(run_tool("set_lead_source", {"source": "facebook"}, ctx))
    assert out == {"ok": False}
    assert db.commits == 0
