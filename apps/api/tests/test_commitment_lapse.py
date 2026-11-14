"""CLOSING A CHECK WHOSE REPLY DAY HAS PASSED, and the way to the customer on
the platform itself (owner, 2026-11-14): "close those that the respond day
have passed and what we can open directly on Messenger or Facebook comment,
have a provision to go directly to that comment or message"."""
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401
from app.services import commitments as cm

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)


def _r(age_min):
    return {"item": "the cope", "age_min": age_min}


def test_lapsed_needs_both_a_quiet_customer_and_an_old_check(monkeypatch):
    monkeypatch.setattr(cm.settings, "commitment_lapse_hours", 24, raising=False)
    day = timedelta(hours=24)
    assert cm.lapsed(_r(2000), NOW - day - timedelta(minutes=1), now=NOW)
    assert not cm.lapsed(_r(2000), NOW - timedelta(hours=23), now=NOW)      # they wrote today
    assert not cm.lapsed(_r(60), NOW - timedelta(days=5), now=NOW)          # a new check on an old thread
    assert not cm.lapsed(_r(2000), None, now=NOW)                           # unreadable: never closed
    assert not cm.lapsed(None, NOW - timedelta(days=5), now=NOW)
    monkeypatch.setattr(cm.settings, "commitment_lapse_hours", 0, raising=False)
    assert not cm.lapsed(_r(9000), NOW - timedelta(days=5), now=NOW)        # switched off


def test_the_direct_link_points_at_the_comment_the_post_or_the_page_inbox(monkeypatch):
    monkeypatch.setattr(cm.settings, "meta_page_id", "1234", raising=False)
    post = "https://www.facebook.com/1234/posts/5678"
    assert cm.direct_link("facebook", "u1", permalink=post, comment_id="5678_91011") == post + "?comment_id=91011"
    assert cm.direct_link("facebook", "u1", permalink=post + "?x=1", comment_id="91011") == post + "?x=1&comment_id=91011"
    assert cm.direct_link("facebook", "u1", permalink=post) == post
    assert cm.direct_link("facebook", "u1") == ""
    ig = "https://www.instagram.com/p/abc/"
    assert cm.direct_link("instagram", "u2", permalink=ig, comment_id="1") == ig
    m = cm.direct_link("messenger", "PSID9")
    assert m.startswith("https://business.facebook.com/latest/inbox/all?asset_id=1234")
    assert "selected_item_id=PSID9" in m and "thread_type=FB_MESSAGE" in m
    assert cm.direct_link("instagram", "u2") == "https://business.facebook.com/latest/inbox/all?asset_id=1234"
    # WhatsApp has no such place, and nothing is invented without a Page id
    assert cm.direct_link("whatsapp", "254700000001") == ""
    monkeypatch.setattr(cm.settings, "meta_page_id", "", raising=False)
    assert cm.direct_link("messenger", "PSID9") == ""


def test_the_inbox_offers_the_way_there():
    import pathlib
    web = pathlib.Path(__file__).resolve().parents[2] / "web" / "src"
    view = (web / "components" / "views" / "ConversationsView.tsx").read_text()
    assert "conversationsApi.directLink(activeConv.id)" in view
    assert "Open the comment on Facebook" in view and "Open in the Page inbox" in view
    assert "/direct-link" in (web / "lib" / "api.ts").read_text()
