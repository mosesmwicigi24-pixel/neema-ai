"""Owner, 2026-10-10: re-engage on, at most 15 check-ins a day to start. With
20 eligible threads one live run sends exactly 15; the other 5 are neither
composed nor marked, so they stay eligible for the next run."""
import asyncio
import types


def test_a_live_run_stops_at_the_daily_limit(monkeypatch):
    from app.core.config import settings
    from app.jobs import reengage as rg

    rows = [types.SimpleNamespace(i=i) for i in range(20)]
    handled = []

    async def fake_find(db):
        return rows

    async def fake_handle(redis, row, *, send, write):
        handled.append(row.i)
        return {"skipped": None, "refused": None, "error": None, "sent": True,
                "draft": "hi", "channel": "whatsapp", "to": f"2547000000{row.i:02d}",
                "last_in": "x"}

    class _Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(rg, "find_quiet", fake_find)
    monkeypatch.setattr(rg, "_handle", fake_handle)
    monkeypatch.setattr(rg, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(rg, "within_quiet_hours", lambda: True)
    monkeypatch.setattr(settings, "recovery_reengage_daily_limit", 15)

    res = asyncio.run(rg.run(send=True, redis=object()))

    assert res["sent"] == 15 and res["held_for_limit"] == 5
    assert handled == list(range(15))          # the last 5 never composed


def test_the_default_limit_is_fifteen():
    from app.core.config import Settings
    assert Settings.model_fields["recovery_reengage_daily_limit"].default == 15
