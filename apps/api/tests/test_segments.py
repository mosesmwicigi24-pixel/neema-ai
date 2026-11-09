"""CUSTOMERS IN AGGREGATE (owner's directive, 2026-11-09, Phase 4; audit §7):
by market with confirmed kept apart from inferred, by language, by channel —
counts only, from the geography decision and the scribe's language."""
import asyncio
import types
import uuid

import app.main  # noqa: F401
from app.services import geography as geo
from app.services import segments


def _u(wa_id, person_id=None, country_iso=None, uid=None):
    return types.SimpleNamespace(id=uid or uuid.uuid4(), wa_id=wa_id, phone=wa_id, person_id=person_id,
                                 country_iso=country_iso, state={})


def _state(**attrs):
    st = {}
    for attr, (val, by, conf) in attrs.items():
        st, _ = geo.observe(st, attr, val, by=by, confidence=conf)
    return st


def test_place_reads_the_decision_and_names_its_basis():
    pid = uuid.uuid4()
    said = _state(telephone_country=("BH", "phone", "confirmed"), probable_country=("KE", "stated", "high"))
    assert segments.place(_u("97333123456", pid), said) == {"iso": "KE", "name": "Kenya", "basis": "confirmed"}
    confirmed = _state(confirmed_residence=("AE", "operator", "confirmed"))
    assert segments.place(_u("97333123456", pid), confirmed)["basis"] == "confirmed"
    number_only = segments.place(_u("254712345678", pid), {})
    assert number_only == {"iso": "KE", "name": "Kenya", "basis": "inferred"}
    ip = _state(probable_country=("US", "ip", "probable"))
    assert segments.place(_u("web_abc", pid, country_iso="US"), ip)["basis"] == "inferred"
    assert segments.place(_u("web_abc", pid, country_iso="KE"), {}) == {"iso": "KE", "name": "Kenya", "basis": "inferred"}
    assert segments.place(_u("26414904614761138", pid), {}) == {"iso": None, "name": None, "basis": "unknown"}


def test_summarise_counts_markets_languages_and_channels():
    p1, p2, p3, p4 = (uuid.uuid4() for _ in range(4))
    persons = {
        p1: {**_state(telephone_country=("BH", "phone", "confirmed"), probable_country=("KE", "stated", "high")),
             "contact_preferences": {"language": "sw"}},
        p2: {"contact_preferences": {"language": "en"}},
        p3: {**_state(probable_country=("ZM", "stated", "high")), "contact_preferences": {"language": "en"}},
        p4: {},
    }
    users = [_u("97333123456", p1, uid="u1"), _u("254722000111", p2, uid="u2"),
             _u("27821234567", p3, uid="u3"), _u("26414904614761138", p4, uid="u4")]
    channels = {"u1": {"whatsapp"}, "u2": {"whatsapp", "messenger"}, "u3": {"whatsapp"}, "u4": {"messenger"}}
    out = segments.summarise(users, persons, channels)
    assert out["customers"] == 4 and out["unknown_market"] == 1
    by_iso = {r["iso"]: r for r in out["countries"]}
    assert by_iso["KE"] == {"iso": "KE", "customers": 2, "confirmed": 1, "inferred": 1, "name": "Kenya"}
    assert by_iso["ZM"] == {"iso": "ZM", "customers": 1, "confirmed": 1, "inferred": 0, "name": "Zambia"}
    assert "BH" not in by_iso and "ZA" not in by_iso            # the words outrank the numbers
    assert out["confirmed_market"] == 2 and out["inferred_market"] == 1
    assert [(r["code"], r["customers"]) for r in out["languages"]] == [("en", 2), ("sw", 1), ("unknown", 1)]
    assert out["languages"][1]["name"] == "Swahili" and out["languages"][2]["name"] == "Unknown"
    assert [(r["channel"], r["customers"]) for r in out["channels"]] == [("whatsapp", 3), ("messenger", 2)]
    assert out["as_of"].startswith("20") and "confirmed" in out["basis"]["market"]


def test_summarise_with_nothing():
    out = segments.summarise([], {}, {})
    assert out["customers"] == 0 and out["countries"] == [] and out["languages"] == [] and out["channels"] == []


def test_the_report_excludes_merged_rows_and_counts_one_customer_once_per_channel():
    """The three bulk reads on a scripted db: users, tombstoned persons,
    persons, conversations (wa_id, person_id, channel)."""
    p_live, p_dead = uuid.uuid4(), uuid.uuid4()
    live = _u("254722000111", p_live, uid="u-live")
    dead = _u("254722000222", p_dead, uid="u-dead")
    person = types.SimpleNamespace(id=p_live, state={"contact_preferences": {"language": "sw"}})
    rows = [("254722000111", p_live, "whatsapp"), ("254722000111", p_live, "whatsapp"),
            (None, p_live, "messenger")]

    class _DB:
        def __init__(self):
            self.calls = 0
        async def execute(self, stmt):
            self.calls += 1
            payload = {1: [live, dead], 2: [p_dead], 3: [person], 4: rows}[self.calls]
            return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: payload),
                                         all=lambda: payload)
    out = asyncio.run(segments.report(_DB()))
    assert out["customers"] == 1
    assert out["countries"] == [{"iso": "KE", "customers": 1, "confirmed": 0, "inferred": 1, "name": "Kenya"}]
    assert out["languages"] == [{"code": "sw", "name": "Swahili", "customers": 1}]
    assert out["channels"] == [{"channel": "messenger", "customers": 1}, {"channel": "whatsapp", "customers": 1}]


def test_the_endpoint_is_registered_and_delegates():
    import inspect
    from app.routers import admin
    assert "segments.report(db)" in inspect.getsource(admin.report_segments)
