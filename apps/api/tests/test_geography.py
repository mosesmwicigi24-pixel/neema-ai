"""GEOGRAPHY WITH PROVENANCE (owner's directive, 2026-11-09): a customer's
telephone country, probable country, confirmed residence, shipping destination
and city are separate attributes on the person, each with its source, its
confidence (the five-level scale, no invented numbers) and its time, with a
history on conflict — and ONE decision every reader shares. The Bahrain / Kenya
case runs end to end here on fakes; `test_geography_db.py` runs it on Postgres."""
import asyncio
import types
import uuid

import app.main  # noqa: F401 — registers models
from app.agent import tools
from app.agent.tools import ToolContext
from app.models.person import Person
from app.services import geography as geo
from app.services import market


# ── 1. the telephone country: shared codes read right ────────────────────────

def test_telephone_country_reads_shared_codes_with_the_phone_library():
    assert geo.telephone_country("97333123456")["iso"] == "BH"       # Bahrain
    assert geo.telephone_country("254712345678")["iso"] == "KE"
    assert geo.telephone_country("12125550123")["iso"] == "US"       # New York, not Canada
    assert geo.telephone_country("14165550123")["iso"] == "CA"       # Toronto
    assert geo.telephone_country("74951234567")["iso"] == "RU"       # Moscow, not Kazakhstan
    assert geo.telephone_country("442071234567")["iso"] == "GB"
    t = geo.telephone_country("+973 3312 3456")
    assert t["country"] == "Bahrain" and t["code"] == "973" and t["flag_url"].endswith("/bh.svg")


def test_telephone_country_is_none_for_a_non_number():
    assert geo.telephone_country("web_ab12cd") is None
    assert geo.telephone_country("26414904614761138") is None      # a Meta PSID
    assert geo.telephone_country(None) is None and geo.telephone_country("") is None


# ── 2. what they said ────────────────────────────────────────────────────────

def test_country_from_words_separates_the_country_from_the_city():
    assert geo.country_from_words("Kenya") == ("KE", None)
    assert geo.country_from_words("Nairobi") == ("KE", "Nairobi")
    assert geo.country_from_words("Kampala, Uganda") == ("UG", "Kampala, Uganda")
    assert geo.country_from_words("Pofadder") == (None, "Pofadder")  # a town we do not know
    assert geo.country_from_words("  ") == (None, None)


def test_a_short_country_name_or_a_well_known_city_places_the_customer():
    """The validation run of 2026-11-09 (cint-002): a Kenyan number saying
    "Dubai, UAE" was placed in Kenya and quoted in shillings, because the
    table knew only "United Arab Emirates". Aliases and well-known cities
    now name their country; Kenyan towns still win; plain words place no one."""
    assert geo.country_from_words("Dubai, UAE") == ("AE", "Dubai, UAE")
    assert geo.country_from_words("I'm in Dubai now") == ("AE", "I'm in Dubai now")
    assert geo.country_from_words("UAE") == ("AE", "UAE")
    assert geo.country_from_words("Kampala") == ("UG", "Kampala")
    assert geo.country_from_words("Dar es Salaam") == ("TZ", "Dar es Salaam")
    assert geo.country_from_words("London, UK") == ("GB", "London, UK")
    assert geo.country_from_words("Manama") == ("BH", "Manama")
    assert geo.country_from_words("Dubai or Nairobi") == ("KE", "Dubai or Nairobi")   # the home town wins
    assert geo.country_from_words("Tell us") == (None, "Tell us")                      # "us" is not the USA
    assert geo.country_from_words("Thank you") == (None, "Thank you")
    rs = geo.stated_readings("Dubai, UAE")
    assert [(a, v) for a, v, _ in rs] == [("probable_country", "AE"), ("city", "Dubai, UAE")]


def test_stated_readings_carry_the_words_as_detail():
    rs = geo.stated_readings("Nairobi")
    assert [(a, v) for a, v, _ in rs] == [("probable_country", "KE"), ("city", "Nairobi")]
    assert rs[0][2] == {"by": "stated", "confidence": "high", "detail": "Nairobi"}
    assert geo.stated_readings("Kenya") == [("probable_country", "KE",
                                             {"by": "stated", "confidence": "high", "detail": "Kenya"})]
    assert geo.stated_readings("somewhere nice") == [("city", "somewhere nice",
                                                      {"by": "stated", "confidence": "high"})]


# ── 3. observe: confidence decides what replaces what ────────────────────────

def test_a_reading_is_recorded_with_its_provenance():
    st, changed = geo.observe({}, "telephone_country", "BH", by="phone", confidence="confirmed",
                              detail="+973")
    assert changed
    r = st["geo"]["telephone_country"]
    assert r["value"] == "BH" and r["by"] == "phone" and r["confidence"] == "confirmed"
    assert r["detail"] == "+973" and r["at"].startswith("20")
    assert "history" not in st["geo"]


def test_a_stronger_reading_replaces_a_weaker_one_and_keeps_it_in_the_history():
    st, _ = geo.observe({}, "probable_country", "US", by="ip", confidence="probable")
    st, changed = geo.observe(st, "probable_country", "KE", by="stated", confidence="high",
                              detail="Nairobi")
    assert changed and st["geo"]["probable_country"]["value"] == "KE"
    h = st["geo"]["history"]
    assert len(h) == 1 and h[0]["previous"]["value"] == "US" and h[0]["value"] == "KE"
    assert "kept" not in h[0]


def test_a_weaker_conflicting_reading_never_moves_the_record_but_is_visible():
    st, _ = geo.observe({}, "probable_country", "KE", by="stated", confidence="high")
    st, changed = geo.observe(st, "probable_country", "US", by="ip", confidence="probable")
    assert changed                                          # the conflict is recorded…
    assert st["geo"]["probable_country"]["value"] == "KE"   # …the decision is not moved
    assert st["geo"]["history"][0]["kept"] == "previous"
    assert st["geo"]["history"][0]["value"] == "US"


def test_the_same_value_again_is_not_a_change_unless_it_is_better_sourced():
    st, _ = geo.observe({}, "probable_country", "KE", by="stated", confidence="high")
    at = st["geo"]["probable_country"]["at"]
    st2, changed = geo.observe(st, "probable_country", "KE", by="ip", confidence="probable")
    assert not changed and st2["geo"]["probable_country"]["at"] == at
    st3, changed = geo.observe(st, "probable_country", "KE", by="operator", confidence="confirmed")
    assert changed and st3["geo"]["probable_country"]["by"] == "operator"
    assert "history" not in st3["geo"]                      # same value: nothing to keep


def test_history_is_capped_and_unknown_attributes_or_empty_values_are_ignored():
    st = {}
    for i in range(20):
        st, _ = geo.observe(st, "city", f"Town {i}", by="stated", confidence="high")
    assert len(st["geo"]["history"]) == geo.HISTORY_CAP
    assert st["geo"]["city"]["value"] == "Town 19"
    assert geo.observe(st, "favourite_colour", "blue", by="stated", confidence="high")[1] is False
    assert geo.observe(st, "city", "", by="stated", confidence="high")[1] is False
    assert geo.observe(st, "city", None, by="stated", confidence="high")[1] is False


def test_other_state_keys_survive_a_geography_write():
    st = {"agent_memory": ["likes blue"], "contact_preferences": {"language": "sw"}}
    st2, _ = geo.observe(st, "telephone_country", "KE", by="phone", confidence="confirmed")
    assert st2["agent_memory"] == ["likes blue"] and st2["contact_preferences"] == {"language": "sw"}
    assert st == {"agent_memory": ["likes blue"], "contact_preferences": {"language": "sw"}}  # pure


# ── 4. the one decision ──────────────────────────────────────────────────────

def _state(**attrs):
    st = {}
    for attr, (val, by, conf) in attrs.items():
        st, _ = geo.observe(st, attr, val, by=by, confidence=conf)
    return st


def test_decision_order_is_confirmed_then_probable_then_telephone():
    tel_only = _state(telephone_country=("BH", "phone", "confirmed"))
    assert geo.decide(tel_only)["country_iso"] == "BH"
    assert geo.decide(tel_only)["attribute"] == "telephone_country"
    said = _state(telephone_country=("BH", "phone", "confirmed"),
                  probable_country=("KE", "stated", "high"))
    d = geo.decide(said)
    assert d["country_iso"] == "KE" and d["country"] == "Kenya" and d["by"] == "stated"
    assert d["attribute"] == "probable_country" and d["flag_url"].endswith("/ke.svg")
    confirmed = _state(telephone_country=("BH", "phone", "confirmed"),
                       probable_country=("KE", "stated", "high"),
                       confirmed_residence=("AE", "operator", "confirmed"))
    assert geo.decide(confirmed)["country_iso"] == "AE"
    assert geo.decide(confirmed)["attribute"] == "confirmed_residence"


def test_a_possible_reading_never_decides_and_the_fallback_is_the_number():
    locale = _state(probable_country=("ZA", "locale", "possible"))
    assert geo.decide(locale)["country_iso"] is None
    assert geo.decide(locale)["confidence"] == "unknown"
    d = geo.decide(locale, fallback_iso="ke")
    assert d["country_iso"] == "KE" and d["attribute"] == "telephone_country"
    assert geo.decide(None) == {"country_iso": None, "country": None, "flag_url": None,
                                "by": None, "confidence": "unknown", "attribute": None}


def test_shipping_and_city_never_decide_the_market():
    st = _state(shipping_country=("KE", "order", "probable"), city=("Nairobi", "stated", "high"))
    assert geo.decide(st)["country_iso"] is None


# ── 5. the view the profile shows ────────────────────────────────────────────

def test_view_shows_every_attribute_with_source_and_confidence_and_flags_the_discrepancy():
    st = _state(telephone_country=("BH", "phone", "confirmed"),
                probable_country=("KE", "stated", "high"), city=("Nairobi", "stated", "high"))
    v = geo.view(st, language="sw")
    assert v["telephone_country"]["label"] == "Bahrain"
    assert v["telephone_country"]["source"] == "the telephone number"
    assert v["telephone_country"]["confidence_label"] == "Confirmed"
    assert v["probable_country"]["label"] == "Kenya" and v["probable_country"]["source"] == "what the customer said"
    assert v["probable_country"]["confidence_label"] == "High confidence"
    assert v["city"]["label"] == "Nairobi"
    assert v["confirmed_residence"] is None and v["shipping_country"] is None
    assert v["decision"]["country_iso"] == "KE" and v["decision"]["source"] == "what the customer said"
    assert v["discrepancy"] is True
    assert v["preferred_language"]["value"] == "sw"
    assert v["history"] == []


def test_view_derives_the_telephone_country_from_the_handle_for_an_old_profile():
    v = geo.view({}, handle="254712345678")
    assert v["telephone_country"]["value"] == "KE" and v["telephone_country"]["at"] is None
    assert v["decision"]["country_iso"] == "KE" and v["discrepancy"] is False
    assert v["preferred_language"] is None
    assert geo.view(None)["decision"]["country_iso"] is None


# ── 6. operator readings and merge carry ─────────────────────────────────────

def test_operator_readings_confirm_the_residence_from_iso_name_or_location():
    assert geo.operator_readings(country_iso="ke") == [
        ("confirmed_residence", "KE", {"by": "operator", "confidence": "confirmed", "detail": None})]
    assert geo.operator_readings(country="Uganda")[0][1] == "UG"
    rs = geo.operator_readings(location="Mombasa")
    assert [(a, v) for a, v, _ in rs] == [("confirmed_residence", "KE"), ("city", "Mombasa")]
    assert geo.operator_readings(country_iso="XX") == []            # not a country
    assert geo.operator_readings(location="nowhere in particular") == [
        ("city", "nowhere in particular", {"by": "operator", "confidence": "confirmed"})]


def test_merge_carries_the_secondary_geography_without_weakening_the_primary():
    primary = _state(telephone_country=("KE", "phone", "confirmed"),
                     probable_country=("KE", "stated", "high"))
    secondary = _state(probable_country=("US", "ip", "probable"),
                       city=("Nairobi", "stated", "high"),
                       shipping_country=("KE", "order", "probable"))
    st, changed = geo.carry_on_merge(primary, secondary)
    assert changed
    g = st["geo"]
    assert g["probable_country"]["value"] == "KE"                 # the weaker US did not win
    assert g["city"]["value"] == "Nairobi" and g["shipping_country"]["value"] == "KE"
    assert any(h["value"] == "US" and h.get("kept") == "previous" for h in g["history"])
    st2, changed2 = geo.carry_on_merge(st, {})
    assert not changed2 and st2 == st


def test_describe_change_names_the_move_and_its_source():
    change = {"moved": True, "before": {"country_iso": "BH", "country": "Bahrain"},
              "after": {"country_iso": "KE", "country": "Kenya", "by": "stated"}}
    assert geo.describe_change(change) == "Placed in Kenya (what the customer said); was Bahrain"
    assert geo.describe_change({"moved": False}) is None and geo.describe_change(None) is None
    first = {"moved": True, "before": {"country_iso": None}, "after": {"country_iso": "KE", "country": "Kenya", "by": "phone"}}
    assert geo.describe_change(first) == "Placed in Kenya (the telephone number)"


# ── 7. the market reads the decision (fakes) ─────────────────────────────────

class _FakeDB:
    """Scripted execute() results; get() returns the person."""
    def __init__(self, results, person=None):
        self._results, self._person, self.commits = list(results), person, 0
    async def execute(self, stmt):
        nxt = self._results.pop(0) if self._results else None
        items = nxt if isinstance(nxt, list) else ([nxt] if nxt is not None else [])
        return types.SimpleNamespace(
            scalar_one_or_none=lambda: items[0] if items else None,
            first=lambda: items[0] if items else None,
            scalars=lambda: types.SimpleNamespace(all=lambda: items,
                                                  first=lambda: items[0] if items else None))
    async def get(self, model, pk, **kw):
        return self._person
    async def commit(self):
        self.commits += 1
    async def flush(self):
        pass
    def add(self, obj):
        pass


def _person(state=None):
    p = Person(display_name="Amina", state=dict(state or {}))
    p.id = uuid.uuid4()
    return p


def _user(wa_id, person_id=None, **kw):
    base = dict(wa_id=wa_id, location=None, phone=wa_id, country_iso=None, country=None,
                flag_url=None, name="", person_id=person_id, name_confirmed=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


BH = "97333123456"


def test_the_bahrain_number_in_kenya_is_quoted_kes_by_the_shared_decision():
    p = _person(_state(telephone_country=("BH", "phone", "confirmed"),
                       probable_country=("KE", "stated", "high")))
    u = _user(BH, p.id)
    cur, loc = asyncio.run(market.customer_market(_FakeDB([u], p), "whatsapp", BH))
    assert cur == "KES" and loc == {"country_iso": "KE", "country": "Kenya"}
    # without the stated location the number decides, as before
    p2 = _person(_state(telephone_country=("BH", "phone", "confirmed")))
    cur, loc = asyncio.run(market.customer_market(_FakeDB([_user(BH, p2.id)], p2), "whatsapp", BH))
    assert cur == "USD" and loc["country_iso"] == "BH"
    # no user row, no person: the number alone
    assert asyncio.run(market.customer_market(_FakeDB([]), "whatsapp", "254712345678"))[0] == "KES"


def test_a_geography_read_that_fails_falls_back_to_the_number():
    class _Broken(_FakeDB):
        async def execute(self, stmt):
            raise RuntimeError("db away")
    cur, loc = asyncio.run(market.customer_market(_Broken([]), "whatsapp", "254712345678"))
    assert cur == "KES" and loc["country_iso"] == "KE"


def test_the_meta_chain_reads_the_record_first_then_the_old_stores():
    p = _person(_state(probable_country=("KE", "stated", "high")))
    ident = types.SimpleNamespace(person_id=p.id, channel="messenger", external_id="psid1")
    ev = asyncio.run(market.evidence_for_person(_FakeDB([[], []], p), ident, p))
    assert ev["country_iso"] == "KE" and ev["evidence"] == "their words"
    # a locale-only record decides nothing; the legacy location text still does
    p2 = _person({**_state(probable_country=("ZA", "locale", "possible")), "location": "Lusaka, Zambia"})
    ev2 = asyncio.run(market.evidence_for_person(_FakeDB([[], []], p2), ident, p2))
    assert ev2["country_iso"] == "ZM" and ev2["evidence"] == "their words"


def test_the_profile_country_fields_read_the_decision_first():
    from app.routers.crm import _country_fields
    u = _user(BH, country_iso="BH", country="Bahrain")
    st = _state(telephone_country=("BH", "phone", "confirmed"), probable_country=("KE", "stated", "high"))
    assert _country_fields(u, st, BH) == {"country_iso": "KE", "country": "Kenya",
                                          "flag_url": "https://flagcdn.com/ke.svg"}
    # no record: the stores as before
    assert _country_fields(u, {}, BH)["country_iso"] == "BH"


# ── 8. capture_customer places them, switches the turn, mirrors the row ──────

def test_capture_customer_places_the_customer_and_switches_this_turn(monkeypatch):
    p = _person(_state(telephone_country=("BH", "phone", "confirmed")))
    u = _user(BH, p.id, country_iso="BH", country="Bahrain")
    noted = []

    async def fake_note(db, *, channel, contact, change):
        noted.append((channel, contact, geo.describe_change(change)))
    monkeypatch.setattr(geo, "note", fake_note)
    db = _FakeDB([u], p)
    ctx = ToolContext(db=db, redis=None, wa_id=BH, currency="USD", channel="whatsapp",
                      market_locked=True)
    out = asyncio.run(tools._capture_customer({"location": "Nairobi"}, ctx))
    assert out["ok"] and out["location"] == "Nairobi" and out["placed"] == "Kenya"
    assert out["currency_now"] == "KES" and ctx.currency == "KES"
    assert "KES" in out["note"] and "do NOT convert" in out["note"]
    g = p.state["geo"]
    assert g["telephone_country"]["value"] == "BH"                   # the number is kept
    assert g["probable_country"] == {**g["probable_country"], "value": "KE", "by": "stated",
                                     "confidence": "high", "detail": "Nairobi"}
    assert g["city"]["value"] == "Nairobi"
    assert (u.country_iso, u.country) == ("KE", "Kenya")             # the compatibility store follows
    assert u.location == "Nairobi"
    assert noted == [("whatsapp", BH, "Placed in Kenya (what the customer said); was Bahrain")]
    assert db.commits == 1


def test_capture_customer_with_a_kenyan_number_and_a_kenyan_town_changes_no_market(monkeypatch):
    p = _person(_state(telephone_country=("KE", "phone", "confirmed")))
    u = _user("254712345678", p.id, country_iso="KE", country="Kenya")
    noted = []

    async def fake_note(db, **kw):
        noted.append(geo.describe_change(kw["change"]))             # what note() would write
    monkeypatch.setattr(geo, "note", fake_note)
    ctx = ToolContext(db=_FakeDB([u], p), redis=None, wa_id=u.wa_id, currency="KES", channel="whatsapp")
    out = asyncio.run(tools._capture_customer({"location": "Nakuru", "name": "Amina"}, ctx))
    assert out["placed"] == "Kenya" and "currency_now" not in out and ctx.currency == "KES"
    assert p.state["geo"]["city"]["value"] == "Nakuru"
    assert noted == [None]                                           # the decision did not move: no event
    assert u.name == "Amina" and u.name_confirmed is True


def test_capture_customer_without_a_person_still_saves_the_location():
    u = _user("254712345678", None)
    ctx = ToolContext(db=_FakeDB([u], None), redis=None, wa_id=u.wa_id, currency="KES", channel="whatsapp")
    out = asyncio.run(tools._capture_customer({"location": "Kisumu"}, ctx))
    assert out == {"ok": True, "name": "", "location": "Kisumu"}


def test_the_activity_trail_labels_a_placement():
    from app.services.activity_trail import describe
    label, detail = describe("geography", {"placed": "KE"}, {"summary": "Placed in Kenya (what the customer said); was Bahrain"})
    assert label == "Placed the customer" and detail.startswith("Placed in Kenya")


# ── 9. the runtime's WhatsApp turn uses the same decision ────────────────────

def test_the_whatsapp_turn_and_the_catalogue_link_read_the_shared_decision():
    import inspect
    import app.agent.runtime as rt
    src = inspect.getsource(rt.run_turn)
    assert "placement_for_handle" in src
    assert "customer_market(ctx.db, ctx.channel, ctx.wa_id)" in inspect.getsource(tools._customer_currency)
    p = _person(_state(telephone_country=("BH", "phone", "confirmed"), probable_country=("KE", "stated", "high")))
    ctx = ToolContext(db=_FakeDB([_user(BH, p.id)], p), redis=None, wa_id=BH, currency="USD", channel="whatsapp")
    assert asyncio.run(tools._customer_currency(ctx)) == "KES"
