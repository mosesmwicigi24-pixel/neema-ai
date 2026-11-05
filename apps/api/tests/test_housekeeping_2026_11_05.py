"""Housekeeping from the audit of 2026-11-05: the learned-rules cap keeps the
newest rules, and the `remember` tool never files a price."""
import asyncio

import app.main  # noqa: F401 — registers models
from app.services.learned_rules import keep_newest


def test_the_learned_rules_cap_keeps_the_newest_whole_lines():
    rules = "\n".join(f"- rule number {i} " + "x" * 40 for i in range(40))
    out = keep_newest(rules, 1200)
    assert len(out) <= 1200
    assert out.endswith("- rule number 39 " + "x" * 40)
    assert "- rule number 0 " not in out
    assert all(ln.startswith("- rule number") for ln in out.splitlines())
    assert keep_newest("- short", 1200) == "- short"
    assert keep_newest("- " + "y" * 2000, 100) == ("- " + "y" * 2000)[:100]


def test_remember_refuses_a_price(monkeypatch):
    from app.agent import tools
    saved = []

    async def _add(db, wa_id, fact, channel="whatsapp"):
        saved.append(fact)
        return [fact]
    monkeypatch.setattr(tools.memorymod, "add_fact", _add)
    ctx = tools.ToolContext(db=None, redis=None, wa_id="254700000001")
    out = asyncio.run(tools._remember({"fact": "Quoted KES 60,500 for the Bishop's set"}, ctx))
    assert out.get("ok") is False and "hub" in out["not_saved"] and saved == []
    out = asyncio.run(tools._remember({"fact": "Prefers the grey shirt with green and white"}, ctx))
    assert out["ok"] is True and saved == ["Prefers the grey shirt with green and white"]
