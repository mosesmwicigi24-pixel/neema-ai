"""Time maths (owner rule, 2026-08-13): a named day is anchored to the day the
customer said it — 'next Sunday' on a Sunday means next week's; on a Friday it
means in two days — and the check-in lands ON that day, matching what Neema
promises ('I'll check in with you on Sunday'), never the day after."""
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401
from app.services import deals as ds


def _utc(y, mo, d, h=9):
    # NBO = UTC+3, so 09:00 UTC = noon Nairobi.
    return datetime(y, mo, d, h, tzinfo=timezone.utc)


# 2026-08-12 is a WEDNESDAY (the day this rule was set).
WED = _utc(2026, 8, 12)


def _due_nbo(text, now):
    got = ds.detect_customer_promise(text, now=now)
    assert got is not None, text
    due_utc, hint = got
    return due_utc + timedelta(hours=3), hint


def test_sunday_named_on_wednesday_is_this_coming_sunday():
    due, _ = _due_nbo("I will check with my committee next Sunday", WED)
    assert due.strftime("%A") == "Sunday"
    assert due.date() == (WED + timedelta(hours=3)).date() + timedelta(days=4)
    assert due.hour == 18                     # evening — after the committee


def test_sunday_named_ON_a_sunday_means_next_weeks():
    sun = _utc(2026, 8, 16)
    assert sun.strftime("%A") == "Sunday"     # sanity-anchor the calendar
    due, _ = _due_nbo("We'll decide on Sunday", sun)
    assert due.strftime("%A") == "Sunday"
    assert (due.date() - (sun + timedelta(hours=3)).date()).days == 7


def test_friday_to_sunday_is_two_days():
    fri = _utc(2026, 8, 14)
    due, _ = _due_nbo("I'll reply you on Sunday", fri)
    assert (due.date() - (fri + timedelta(hours=3)).date()).days == 2


def test_weekday_beats_a_vaguer_hint_in_the_same_sentence():
    """'after church on Sunday' used to schedule for TOMORROW (the after-church
    branch matched first). The named day is the anchor."""
    due, hint = _due_nbo("I'll confirm after the church service on Sunday", WED)
    assert hint == "sunday"
    assert due.strftime("%A") == "Sunday" and due.hour == 18


def test_tomorrow_keeps_its_morning_shape():
    due, _ = _due_nbo("Nitaconfirm kesho", WED)
    assert due.date() == (WED + timedelta(hours=3)).date() + timedelta(days=1)
    assert due.hour == 10


def test_next_weekday_helper_never_returns_today_or_the_past():
    for offset in range(7):
        now = _utc(2026, 8, 10) + timedelta(days=offset)   # a full week of "todays"
        nbo = now + timedelta(hours=3)
        target = ds.next_weekday_nbo("sunday", nbo)
        assert target.strftime("%A") == "Sunday"
        assert 1 <= (target.date() - nbo.date()).days <= 7
