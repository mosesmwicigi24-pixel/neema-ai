"""Seasonal outreach — and above all, the 24-hour rule.

Most of this audience has not written to us recently, so free-form WhatsApp is not
allowed. The test that matters most: someone outside the window is NEVER messaged
free-form, and is not messaged at all unless an approved template is configured.
"""
import asyncio
import types
from datetime import date, datetime, timedelta, timezone

import app.main  # noqa: F401 — registers models
import app.jobs.seasonal_outreach as so
from app.core.config import settings


def _season(name="Advent", days=35, colour="violet (purple)", when="2026-11-29"):
    return {"season": name, "days_away": days, "colour": colour, "date": when}


def _row(open_window=False, name="Rev Grace", items=("Purple Chasuble",)):
    conv = types.SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700000001")
    return {"wa_id": "254700000001", "conv": conv, "name": name,
            "items": list(items), "last_bought": "2025-12-01",
            "open_window": open_window}


# ── the 24-hour rule ─────────────────────────────────────────────────────────

def test_outside_the_window_with_no_template_is_listed_never_sent(monkeypatch):
    monkeypatch.setattr(settings, "wa_seasonal_template", "", raising=False)
    sent = {"n": 0}

    async def boom(*a, **k):
        sent["n"] += 1

    monkeypatch.setattr("app.services.n8n_bridge._send_waba", boom)
    monkeypatch.setattr("app.services.n8n_bridge.send_wa_template", boom)

    r = asyncio.run(so._handle(None, _row(open_window=False), _season(), send=True))
    assert r["sent"] is False
    assert r["route"] == "needs template"
    assert "no WA_SEASONAL_TEMPLATE" in r["skipped"]
    assert sent["n"] == 0                    # nothing left the building


def test_outside_the_window_uses_the_approved_template(monkeypatch):
    monkeypatch.setattr(settings, "wa_seasonal_template", "seasonal_advent", raising=False)
    monkeypatch.setattr(settings, "wa_seasonal_lang", "en", raising=False)
    calls = {}

    async def fake_template(to, template, lang, params):
        calls.update(to=to, template=template, lang=lang, params=params)

    async def free_form_boom(*a, **k):
        raise AssertionError("free-form is illegal outside the 24h window")

    monkeypatch.setattr("app.services.n8n_bridge.send_wa_template", fake_template)
    monkeypatch.setattr("app.services.n8n_bridge._send_waba", free_form_boom)

    r = asyncio.run(so._handle(None, _row(open_window=False), _season(), send=True))
    assert r["sent"] is True and r["route"] == "template"
    assert calls["template"] == "seasonal_advent"
    assert calls["params"] == ["Rev Grace", "Advent", "violet (purple)", "5"]


def test_inside_the_window_sends_a_warm_free_form_message(monkeypatch):
    monkeypatch.setattr(settings, "wa_seasonal_template", "seasonal_advent", raising=False)
    sent = {}

    async def fake_wa(to, text):
        sent.update(to=to, text=text)

    async def fake_save(*a, **k):
        pass

    async def template_boom(*a, **k):
        raise AssertionError("no template needed inside the window")

    monkeypatch.setattr("app.services.n8n_bridge._send_waba", fake_wa)
    monkeypatch.setattr("app.services.n8n_bridge.save_outbound_message", fake_save)
    monkeypatch.setattr("app.services.n8n_bridge.send_wa_template", template_boom)

    r = asyncio.run(so._handle(None, _row(open_window=True), _season(), send=True))
    assert r["sent"] is True and r["route"] == "free-form"
    assert "Advent" in sent["text"] and "violet" in sent["text"]


# ── the message ──────────────────────────────────────────────────────────────

def test_clergy_titles_are_kept_with_the_name():
    """'Rev Grace' — never the bare title 'Rev', never a stranger's 'Grace'."""
    assert so.greeting_name("Rev Grace Wanjiru") == "Rev Grace"
    assert so.greeting_name("Bishop Moses Mwicigi") == "Bishop Moses"
    assert so.greeting_name("Pst. Daniel Kinyua") == "Pst. Daniel"
    assert so.greeting_name("Moses Mwicigi") == "Moses"      # no title → first name
    assert so.greeting_name("Rev") == "Rev"                  # title alone is all we have
    assert so.greeting_name("") == "" and so.greeting_name(None) == ""


def test_message_is_specific_timely_and_not_pushy():
    text = so.compose(_row(), _season(days=35))
    assert "Rev Grace" in text                              # title + first name
    assert "Advent" in text and "violet (purple)" in text
    assert "5 week(s)" in text
    assert "Purple Chasuble" in text                        # what they bought before
    assert "make to order" in text
    for pushy in ("buy now", "hurry", "limited", "discount", "offer expires"):
        assert pushy not in text.lower()


def test_template_params_are_positional_and_complete():
    p = so.template_params(_row(name=None), _season(days=14))
    assert p == ["there", "Advent", "violet (purple)", "2"]   # graceful without a name
    assert so.template_params(_row(), _season(days=14))[0] == "Rev Grace"


# ── when to run at all ───────────────────────────────────────────────────────

def test_next_season_only_fires_inside_the_lead_window():
    # Ash Wednesday 2026 is 18 Feb — six weeks earlier is early January.
    s = so.next_season(date(2026, 1, 20), lead_days=42)
    assert s and s["season"] == "Lent"
    # …and in a quiet stretch there is simply nothing to offer
    assert so.next_season(date(2026, 7, 1), lead_days=42) is None


def test_quiet_hours():
    at = lambda h: datetime(2026, 7, 27, h, 0, tzinfo=timezone.utc)
    assert so.within_quiet_hours(at(6)) is True     # 09:00 Nairobi
    assert so.within_quiet_hours(at(20)) is False   # 23:00


def test_once_per_customer_per_season_per_year(monkeypatch):
    monkeypatch.setattr(settings, "wa_seasonal_template", "t", raising=False)

    class _R:
        def __init__(self): self.keys = set()
        async def set(self, k, v, nx=False, ex=None):
            if nx and k in self.keys:
                return False
            self.keys.add(k)
            return True

    async def noop(*a, **k):
        pass

    monkeypatch.setattr("app.services.n8n_bridge.send_wa_template", noop)
    r = _R()
    first = asyncio.run(so._handle(r, _row(), _season(), send=True))
    second = asyncio.run(so._handle(r, _row(), _season(), send=True))
    assert first["sent"] is True
    assert second["sent"] is False and "already offered" in second["skipped"]
    # a DIFFERENT season is still allowed
    third = asyncio.run(so._handle(r, _row(), _season(name="Lent", when="2027-02-10"),
                                   send=True))
    assert third["sent"] is True


def test_audience_is_last_years_buyers_of_that_season():
    """The selection must be a PREVIOUS year's same-season buyer — not someone who
    already bought during this year's run of the season."""
    import inspect
    src = inspect.getsource(so.find_audience)
    assert "season_on" in src
    assert "d.year >= today.year" in src        # this year's buyers excluded
    assert "InterceptMode.ai" in src and "ConvStatus.open" in src
