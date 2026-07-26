"""One customer across every platform, with their real purchase history.

Three things pinned here:
 1. A conversation with no messages yet reports when it STARTED, not null — the
    panel was rendering null as a 1970 date ("20660d ago").
 2. Hub purchase history is looked up across EVERY phone we know for the person,
    not only the handle that was asked for — someone who bought at the shop under
    another number still shows their orders.
 3. A visitor who clicks a Neema link (…/product/<slug>?ref=X) is joined to the
    person behind that ref, so the website is the same customer, not a stranger.
"""
import asyncio
import json
import types

import app.main  # noqa: F401 — registers models
import app.routers.web_chat as wc
from app.models.user import User


# ── 1. no-messages conversation reports its start, not null ──────────────────

def test_channel_last_seen_falls_back_to_created_at():
    from datetime import datetime, timezone
    from app.routers.crm import _build_profile

    started = datetime(2026, 7, 25, 9, 0, tzinfo=timezone.utc)
    conv = types.SimpleNamespace(channel="whatsapp", wa_id="254727808176",
                                 created_at=started, last_message_at=None)
    user = User(wa_id="254727808176", phone="254727808176", name="Cynthia Kaffi")
    prof = _build_profile(user, [], [conv], None)

    ch = prof["channels"][0]
    assert ch["last_seen"] == started.isoformat()   # never None → never 1970
    assert ch["first_seen"] == started.isoformat()


def test_channel_last_seen_prefers_a_real_message_time():
    from datetime import datetime, timezone
    from app.routers.crm import _build_profile

    started = datetime(2026, 7, 25, 9, 0, tzinfo=timezone.utc)
    spoke = datetime(2026, 7, 26, 18, 30, tzinfo=timezone.utc)
    conv = types.SimpleNamespace(channel="whatsapp", wa_id="254727808176",
                                 created_at=started, last_message_at=spoke)
    prof = _build_profile(User(wa_id="254727808176"), [], [conv], None)
    assert prof["channels"][0]["last_seen"] == spoke.isoformat()


# ── 3. a ref click joins the website visitor to the same person ──────────────

class _Redis:
    def __init__(self, store=None):
        self.store = store or {}
    async def get(self, k):
        return self.store.get(k)


class _DB:
    def __init__(self, ident=None):
        self.ident = ident
    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalar_one_or_none=lambda: self.ident)


def test_web_visitor_adopts_the_person_behind_the_ref():
    ident = types.SimpleNamespace(person_id="PERSON-1", channel="facebook",
                                  external_id="FBID")
    redis = _Redis({"waref:AB12CD": json.dumps(
        {"channel": "facebook", "external_id": "FBID",
         "items": [{"hub_product_id": 7, "name": "Red Chasuble", "qty": 1}]})})
    user = User(wa_id="web_abc", phone=None)
    user.person_id = None

    linked = asyncio.run(wc._adopt_person_from_ref(_DB(ident), redis, user, "ab12cd"))
    assert linked is True
    assert user.person_id == "PERSON-1"       # same human as the Facebook commenter


def test_unknown_or_expired_ref_leaves_them_anonymous():
    user = User(wa_id="web_abc")
    user.person_id = None
    assert asyncio.run(wc._adopt_person_from_ref(_DB(None), _Redis(), user, "NOPE")) is False
    assert user.person_id is None
    # no ref / no redis → no-op, never an error
    assert asyncio.run(wc._adopt_person_from_ref(_DB(None), None, user, "X")) is False
    assert asyncio.run(wc._adopt_person_from_ref(_DB(None), _Redis(), user, "")) is False


def test_already_linked_visitor_is_not_reassigned():
    ident = types.SimpleNamespace(person_id="OTHER", channel="facebook", external_id="F")
    redis = _Redis({"waref:AB12CD": json.dumps({"channel": "facebook", "external_id": "F"})})
    user = User(wa_id="web_abc")
    user.person_id = "ALREADY"
    assert asyncio.run(wc._adopt_person_from_ref(_DB(ident), redis, user, "AB12CD")) is False
    assert user.person_id == "ALREADY"        # never steals an established identity


def test_web_chat_accepts_a_ref_field():
    body = wc.WebChatIn(session_id="s1", message="hi", ref="AB12CD")
    assert body.ref == "AB12CD"
    assert wc.WebChatIn(session_id="s1", message="hi").ref is None
