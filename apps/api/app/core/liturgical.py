"""The Church year — what season it is, what colour that means, and what's next.

Bethany House sells vestments, and vestments are bought by SEASON: purple for
Advent and Lent, white or gold for Christmas and Easter, red for Pentecost and
Palm Sunday, green for Ordinary Time. A parish that needs purple for Advent must
order weeks ahead, because made-to-order takes time to sew.

That makes the Church calendar the single best demand signal this business has —
and it is completely knowable in advance. This module computes it so Neema can
advise ("Advent starts in five weeks — is your purple set ready?") instead of
waiting to be asked.

Everything hangs off Easter, a moveable feast, computed with the Anonymous
Gregorian algorithm (Meeus/Jones/Butcher). Western (Gregorian) calendar, which is
what Catholic, Anglican and Methodist clergy here follow.
"""
from __future__ import annotations

from datetime import date, timedelta

# Season → the liturgical colour a parish needs to be wearing.
COLOURS = {
    "Advent": "violet (purple)",
    "Christmas": "white or gold",
    "Lent": "violet (purple)",
    "Holy Week": "red for Palm Sunday and Good Friday, violet otherwise",
    "Easter": "white or gold",
    "Pentecost": "red",
    "Ordinary Time": "green",
}


def easter(year: int) -> date:
    """Easter Sunday (Western/Gregorian) — Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lu = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lu) // 451
    month, day = divmod(h + lu - 7 * m + 114, 31)
    return date(year, month, day + 1)


def advent_start(year: int) -> date:
    """First Sunday of Advent — the 4th Sunday before Christmas Day, and the start
    of the Church year. When Christmas itself falls on a Sunday it is Christmas,
    not Advent 4, so we always step back to the Sunday strictly before it."""
    christmas = date(year, 12, 25)
    # weekday(): Mon=0 … Sun=6. Step back to the Sunday BEFORE Christmas…
    back = ((christmas.weekday() - 6) % 7) or 7
    advent_four = christmas - timedelta(days=back)
    return advent_four - timedelta(days=21)          # …then three more Sundays


def key_dates(year: int) -> dict[str, date]:
    """The dates that drive vestment demand in a given calendar year."""
    e = easter(year)
    return {
        "ash_wednesday": e - timedelta(days=46),
        "palm_sunday":   e - timedelta(days=7),
        "good_friday":   e - timedelta(days=2),
        "easter":        e,
        "ascension":     e + timedelta(days=39),
        "pentecost":     e + timedelta(days=49),
        "advent_start":  advent_start(year),
        "christmas":     date(year, 12, 25),
    }


def season_on(day: date) -> str:
    """The liturgical season for a date."""
    k = key_dates(day.year)
    # Christmas season runs across the year boundary: 25 Dec → Epiphany (6 Jan).
    if day >= k["advent_start"] and day < k["christmas"]:
        return "Advent"
    if day >= k["christmas"] or day <= date(day.year, 1, 6):
        return "Christmas"
    if k["ash_wednesday"] <= day < k["palm_sunday"]:
        return "Lent"
    if k["palm_sunday"] <= day < k["easter"]:
        return "Holy Week"
    if k["easter"] <= day < k["pentecost"]:
        return "Easter"
    if day == k["pentecost"]:
        return "Pentecost"
    return "Ordinary Time"


def colour_on(day: date) -> str:
    return COLOURS[season_on(day)]


def upcoming(day: date, within_days: int = 120) -> list[dict]:
    """The seasons/feasts starting soon, nearest first — each with how far away it
    is and the colour it calls for. This is the selling window: a parish ordering
    made-to-order vestments needs to decide WEEKS before the season begins."""
    events: list[tuple[date, str]] = []
    for y in (day.year, day.year + 1):
        k = key_dates(y)
        events += [
            (k["ash_wednesday"], "Lent"),
            (k["palm_sunday"], "Holy Week"),
            (k["easter"], "Easter"),
            (k["pentecost"], "Pentecost"),
            (k["advent_start"], "Advent"),
            (k["christmas"], "Christmas"),
        ]
    out = []
    for when, name in sorted(events):
        days = (when - day).days
        if 0 <= days <= within_days:
            out.append({"season": name, "date": when.isoformat(), "days_away": days,
                        "colour": COLOURS[name]})
    return out


def summary(day: date | None = None, lead_days: int = 42) -> dict:
    """What Neema should know about the Church year right now.

    `lead_days` is the made-to-order lead time worth flagging (six weeks by
    default): a season inside that window is one a parish should be ordering for
    NOW, not when it arrives."""
    day = day or date.today()
    season = season_on(day)
    nxt = upcoming(day, within_days=180)
    order_now = [e for e in nxt if 0 < e["days_away"] <= lead_days]
    return {
        "today": day.isoformat(),
        "season": season,
        "colour": COLOURS[season],
        "upcoming": nxt[:4],
        "order_now": order_now,
    }


def brief(day: date | None = None, lead_days: int = 42) -> str:
    """One short block for the agent's context — season, colour, and what a parish
    should already be ordering for."""
    s = summary(day, lead_days)
    lines = [f"Church season today: {s['season']} — vestment colour: {s['colour']}."]
    for e in s["order_now"]:
        weeks = max(round(e["days_away"] / 7), 1)
        lines.append(
            f"{e['season']} begins in about {weeks} week(s) ({e['date']}) and needs "
            f"{e['colour']} — made-to-order takes time, so this is the moment to ask "
            f"whether they're ready.")
    return "\n".join(lines)
