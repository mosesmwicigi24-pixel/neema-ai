"""Customer intelligence capture: ad-referral attribution (first-touch),
person-scoped role/organization, and the clergy-leader lead-score signal."""
import asyncio
import types

import pytest

from app.services import wa_native as wn


@pytest.fixture(autouse=True)
def _no_flag_modified(monkeypatch):
    """flag_modified needs real ORM instances; these tests use plain fakes."""
    monkeypatch.setattr("sqlalchemy.orm.attributes.flag_modified",
                        lambda *a, **k: None)


class _Res:
    def __init__(self, one=None):
        self._one = one
    def scalar_one_or_none(self):
        return self._one


class _FakeDB:
    def __init__(self, user=None, person=None):
        self.user, self.person = user, person
        self.commits = 0
    async def execute(self, *a, **k):
        return _Res(one=self.user)
    async def get(self, model, pk):
        return self.person
    async def commit(self):
        self.commits += 1


def _user(state=None, person_id="p1"):
    return types.SimpleNamespace(wa_id="254700000001", state=state or {},
                                 person_id=person_id)


def _person(state=None):
    return types.SimpleNamespace(state=state or {})


def test_parse_events_extracts_click_to_whatsapp_referral():
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "messages": [{"from": "254700000001", "id": "wamid.A", "type": "text",
                      "text": {"body": "How much is a cassock?"},
                      "referral": {"source_type": "ad", "source_id": "1203",
                                   "source_url": "https://fb.me/xyz",
                                   "headline": "Clergy wear sale"}}]}}]}]}
    events = wn.parse_events(payload)
    assert events[0]["referral"]["source_id"] == "1203"
    assert events[0]["referral"]["source_type"] == "ad"


def test_referral_sets_first_touch_on_user_and_person():
    user, person = _user(), _person()
    db = _FakeDB(user, person)
    ref = {"source_type": "ad", "source_id": "1203", "headline": "Clergy wear sale"}
    asyncio.run(wn._capture_referral(db, "254700000001", ref))
    assert user.state["lead_source"] == "facebook_ad"
    assert user.state["ad_ref"]["source_id"] == "1203"
    assert person.state["lead_source"] == "facebook_ad"
    assert person.state["ad_ref"]["headline"] == "Clergy wear sale"
    assert db.commits == 1


def test_referral_never_overwrites_established_origin():
    user = _user(state={"lead_source": "referral",
                        "ad_ref": {"source_id": "OLD"}})
    person = _person(state={"lead_source": "walk_in"})
    db = _FakeDB(user, person)
    asyncio.run(wn._capture_referral(
        db, "254700000001", {"source_type": "ad", "source_id": "NEW"}))
    assert user.state["lead_source"] == "referral"       # first touch wins
    assert user.state["ad_ref"]["source_id"] == "OLD"
    assert person.state["lead_source"] == "walk_in"
    # the person MIRRORS the user store's final values — never a new decision
    assert person.state["ad_ref"]["source_id"] == "OLD"


def test_ad_ref_is_coupled_to_an_ad_origin():
    # Established non-ad origin, no stored ad → a later ad click must NOT attach
    # ad details ("Came via ad" would be false attribution).
    user = _user(state={"lead_source": "referral"})
    db = _FakeDB(user, _person())
    asyncio.run(wn._capture_referral(
        db, "254700000001", {"source_type": "ad", "source_id": "NEW"}))
    assert "ad_ref" not in user.state


def test_post_referral_is_organic_not_an_ad():
    user, person = _user(), _person()
    db = _FakeDB(user, person)
    asyncio.run(wn._capture_referral(
        db, "254700000001", {"source_type": "post", "source_id": "p77"}))
    assert user.state["lead_source"] == "facebook"
    assert "ad_ref" not in user.state                    # organic: no ad badge


def test_meta_shortlink_referral_stores_no_ad_ref():
    from app.routers import meta_webhook as mw
    person = _person()
    db = _FakeDB(person=person)
    asyncio.run(mw._capture_ad_referral(
        db, "pid", "messenger", {"source": "SHORTLINK", "type": "OPEN_THREAD",
                                 "ref": "summer"}))
    assert person.state["lead_source"] == "facebook"
    assert "ad_ref" not in person.state


def test_set_lead_source_keeps_first_touch():
    from app.agent.tools import _set_lead_source
    user = _user(state={"lead_source": "facebook_ad"})
    ctx = types.SimpleNamespace(db=_FakeDB(user), wa_id="254700000001")
    out = asyncio.run(_set_lead_source({"source": "facebook"}, ctx))
    assert out["lead_source"] == "facebook_ad"           # ad attribution stands
    assert user.state["lead_source"] == "facebook_ad"


def test_meta_ad_referral_is_channel_aware_and_first_touch():
    from app.routers import meta_webhook as mw
    person = _person()
    db = _FakeDB(person=person)
    ref = {"source": "ADS", "type": "OPEN_THREAD", "ad_id": "9981",
           "ads_context_data": {"ad_title": "Communion sets"}}
    asyncio.run(mw._capture_ad_referral(db, "pid", "instagram", ref))
    assert person.state["lead_source"] == "instagram_ad"
    assert person.state["ad_ref"]["ad_id"] == "9981"
    assert person.state["ad_ref"]["headline"] == "Communion sets"
    # second referral does not overwrite
    asyncio.run(mw._capture_ad_referral(db, "pid", "instagram",
                                        {"source": "ADS", "ad_id": "OTHER"}))
    assert person.state["ad_ref"]["ad_id"] == "9981"


def test_save_profile_fields_person_scoped():
    from app.agent.tools import _save_profile_fields
    person = _person()
    db = _FakeDB(person=person)
    out = asyncio.run(_save_profile_fields(
        db, "pid", role="  Bishop ", organization="Peniel Christ Embassy"))
    assert out == {"role": "Bishop", "organization": "Peniel Christ Embassy"}
    assert person.state["profile"]["role"] == "Bishop"
    # partial update keeps the other field
    asyncio.run(_save_profile_fields(db, "pid", role="Archbishop"))
    assert person.state["profile"] == {"role": "Archbishop",
                                       "organization": "Peniel Christ Embassy"}
    # an empty string CLEARS the field (mis-captured roles must be removable)
    asyncio.run(_save_profile_fields(db, "pid", role=""))
    assert person.state["profile"] == {"organization": "Peniel Christ Embassy"}
    # no person available → None (caller falls back), never a silent {"ok"}
    assert asyncio.run(_save_profile_fields(_FakeDB(), "pid", role="Bishop")) is None


def test_clergy_leader_role_scores_ten():
    from app.routers.crm import _lead_score_parts, _compute_lead_score
    u = types.SimpleNamespace(name="John", location="Kajiado", email=None)
    def pts(role):
        parts = _lead_score_parts(u, 0, 0.0, 1, role=role)
        return next(p["pts"] for p in parts if p["label"] == "Clergy leader")
    assert pts("Founder & C.E.O Peniel Christ embassy ministries") == 10
    assert pts("Bishop") == 10
    assert pts("Rev Dr") == 10
    assert pts("Student") == 0
    assert pts(None) == 0
    # word-bounded: substrings of ordinary words must not score
    assert pts("Welder") == 0
    assert pts("Grandfather of three") == 0
    assert pts("Deanna") == 0
    # the cap still holds
    assert _compute_lead_score(u, 9, 99999, 3, True, 5, 1.0, "Bishop") == 100


def test_merge_suggestions_route_is_registered_before_the_dynamic_merge_route():
    """/customers/{wa_id}/merge_suggestions must be its own GET route and the
    POST merge route must still exist — the suggestion endpoint was inserted
    next to it."""
    from app.routers.crm import router
    paths = {(r.path, tuple(sorted(r.methods or []))) for r in router.routes}
    assert ("/customers/{wa_id}/merge_suggestions", ("GET",)) in paths
    assert ("/customers/{wa_id}/merge", ("POST",)) in paths


def test_dedupe_plan_merges_only_on_overwhelming_evidence():
    from app.jobs.dedupe_merge import build_plan
    wa = {"id": "u1", "wa_id": "254700000001", "phone": None, "person_id": "pA",
          "name": "Bishop Elias", "merged": False, "is_wa": True}
    social_same = {"id": "u2", "wa_id": "2647945332506541", "phone": "+254700000001",
                   "person_id": "pB", "name": "Elias FB", "merged": False, "is_wa": False}
    social_linked = {"id": "u3", "wa_id": "8888888877776666", "phone": "+254700000001",
                     "person_id": "pA", "name": "Already linked", "merged": False, "is_wa": False}
    tombstone = {"id": "u4", "wa_id": "9999999988887777", "phone": "+254700000001",
                 "person_id": "pC", "name": "Old dup", "merged": True, "is_wa": False}
    merges, review = build_plan([wa, social_same, social_linked, tombstone])
    assert len(merges) == 1
    assert merges[0]["primary"]["id"] == "u1"            # WhatsApp anchor survives
    assert merges[0]["secondary"]["id"] == "u2"          # linked + tombstoned skipped
    assert review == []


def test_dedupe_plan_sends_anchorless_groups_to_review():
    from app.jobs.dedupe_merge import build_plan
    a = {"id": "s1", "wa_id": "111122223333444", "phone": "+256700111222",
         "person_id": "p1", "name": "FB One", "merged": False, "is_wa": False}
    b = {"id": "s2", "wa_id": "555566667777888", "phone": "+256 700 111 222",
         "person_id": "p2", "name": "IG One", "merged": False, "is_wa": False}
    merges, review = build_plan([a, b])
    assert merges == []
    assert len(review) == 1 and review[0]["phone"].endswith("256700111222")
