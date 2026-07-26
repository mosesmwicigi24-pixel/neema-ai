"""The Church year — the one demand signal this business can know in advance.

Vestments are bought by season and made to order, so a wrong date or colour is a
wrong sale. Easter is a moveable feast and everything hangs off it, so the dates
are pinned against known-correct values.
"""
import asyncio
from datetime import date

import app.main  # noqa: F401 — registers models
import app.agent.tools as tools
from app.core import liturgical as lit


# ── Easter drives everything ─────────────────────────────────────────────────

def test_easter_matches_the_real_calendar():
    # Western (Gregorian) Easter Sundays — publicly known dates.
    assert lit.easter(2024) == date(2024, 3, 31)
    assert lit.easter(2025) == date(2025, 4, 20)
    assert lit.easter(2026) == date(2026, 4, 5)
    assert lit.easter(2027) == date(2027, 3, 28)
    assert lit.easter(2030) == date(2030, 4, 21)


def test_easter_is_always_a_sunday():
    for y in range(2024, 2041):
        assert lit.easter(y).weekday() == 6


def test_the_moveable_feasts_hang_off_easter_correctly():
    k = lit.key_dates(2026)
    e = date(2026, 4, 5)
    assert k["easter"] == e
    assert k["ash_wednesday"] == date(2026, 2, 18)      # 46 days before
    assert k["ash_wednesday"].weekday() == 2            # …and a Wednesday
    assert k["palm_sunday"] == date(2026, 3, 29)
    assert k["good_friday"] == date(2026, 4, 3)
    assert k["good_friday"].weekday() == 4              # a Friday
    assert k["pentecost"] == date(2026, 5, 24)          # 49 days after
    assert k["pentecost"].weekday() == 6


# ── Advent ───────────────────────────────────────────────────────────────────

def test_advent_is_the_fourth_sunday_before_christmas():
    for y in range(2024, 2041):
        a = lit.advent_start(y)
        assert a.weekday() == 6                              # a Sunday
        gap = (date(y, 12, 25) - a).days
        assert 22 <= gap <= 28                               # 4 Sundays out
        assert date(y, 11, 27) <= a <= date(y, 12, 3)        # the classic window


def test_advent_when_christmas_falls_on_a_sunday():
    """Christmas 2033 is a Sunday — that day is Christmas, not Advent 4, so
    Advent must start a full four Sundays earlier."""
    assert date(2033, 12, 25).weekday() == 6
    assert lit.advent_start(2033) == date(2033, 11, 27)


# ── seasons and their colours ────────────────────────────────────────────────

def test_each_season_reports_the_colour_a_parish_must_wear():
    assert lit.season_on(date(2026, 2, 25)) == "Lent"            # after Ash Wednesday
    assert "purple" in lit.colour_on(date(2026, 2, 25))
    assert lit.season_on(date(2026, 3, 30)) == "Holy Week"       # after Palm Sunday
    assert lit.season_on(date(2026, 4, 5)) == "Easter"
    assert "white" in lit.colour_on(date(2026, 4, 5))
    assert lit.season_on(date(2026, 5, 24)) == "Pentecost"
    assert lit.colour_on(date(2026, 5, 24)) == "red"
    assert lit.season_on(date(2026, 7, 27)) == "Ordinary Time"
    assert lit.colour_on(date(2026, 7, 27)) == "green"
    assert lit.season_on(date(2026, 12, 6)) == "Advent"
    assert "purple" in lit.colour_on(date(2026, 12, 6))
    assert lit.season_on(date(2026, 12, 27)) == "Christmas"      # after Christmas Day
    assert lit.season_on(date(2026, 1, 3)) == "Christmas"        # …and into January


def test_every_day_of_a_year_resolves_to_a_known_season():
    d = date(2026, 1, 1)
    while d.year == 2026:
        assert lit.season_on(d) in lit.COLOURS
        d = date.fromordinal(d.toordinal() + 1)


# ── the selling window ───────────────────────────────────────────────────────

def test_upcoming_is_sorted_nearest_first_and_carries_the_colour():
    up = lit.upcoming(date(2026, 1, 10), within_days=200)
    assert up, "should see Lent/Easter/Pentecost ahead"
    assert [e["days_away"] for e in up] == sorted(e["days_away"] for e in up)
    assert all(e["days_away"] >= 0 for e in up)
    names = [e["season"] for e in up]
    assert names[0] == "Lent"                    # Ash Wednesday is the next one
    assert all(e["colour"] for e in up)


def test_upcoming_crosses_the_year_boundary():
    """In December we must still see next year's Lent and Easter coming."""
    up = lit.upcoming(date(2026, 12, 20), within_days=200)
    assert any(e["season"] == "Lent" for e in up)
    assert any(e["season"] == "Easter" for e in up)


def test_order_now_flags_only_what_is_inside_the_lead_time():
    # Ash Wednesday 2026 is 18 Feb; six weeks before is early January.
    s = lit.summary(date(2026, 1, 20), lead_days=42)
    assert any(e["season"] == "Lent" for e in s["order_now"])
    # …but in July nothing is within six weeks
    quiet = lit.summary(date(2026, 7, 1), lead_days=42)
    assert quiet["order_now"] == []
    assert all(0 < e["days_away"] <= 42 for e in s["order_now"])


def test_brief_reads_like_something_neema_can_act_on():
    b = lit.brief(date(2026, 1, 20))
    assert "Church season today" in b
    assert "Lent" in b and "week(s)" in b
    assert "purple" in b


# ── the tool ─────────────────────────────────────────────────────────────────

def test_tool_returns_the_season_and_is_registered():
    ctx = tools.ToolContext(db=object(), redis=None, wa_id="254700000001")
    out = asyncio.run(tools._church_calendar({}, ctx))
    assert out["season"] in lit.COLOURS and out["colour"]
    assert "upcoming" in out and "order_now" in out
    assert "church_calendar" in tools._HANDLERS
    assert any(t["name"] == "church_calendar" for t in tools.TOOLS)
    from app.agent.runtime import MESSENGER_TOOLS
    assert "church_calendar" in {t["name"] for t in MESSENGER_TOOLS}


def test_the_season_reaches_the_system_prompt():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(customer_name="Rev Grace", country="Kenya",
                            country_iso="KE", currency="KES")
    assert "THE CHURCH YEAR" in p
    assert "vestment colour" in p
