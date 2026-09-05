"""Who is Kenyan — decided from evidence only, in ONE place (owner, 2026-09-05).

The owner's list: the website visitor's IP; a WhatsApp message from +254; a
Facebook / Messenger id that WhatsApp has associated with a +254 number. KES
for those, and only those (plus their own stated location); USD for anyone we
cannot place. The prices come from the hub's rows in that currency.

Found on the way and pinned here: after a Messenger contact is merged with a
+254 WhatsApp number the person owns TWO user rows, and every single-row read
(`scalar_one_or_none`) raised — the market lookup swallowed it and quoted USD
to exactly the customer who had proved they were Kenyan.
"""
import asyncio
import types
import uuid

import app.main  # noqa: F401 — registers models
import app.agent.runtime as rt
from app.agent import tools
from app.agent.tools import ToolContext
from app.core.phone import carries_country_code
from app.models.person import Person
from app.services import market


class _FakeDB:
    """Scripted: every execute() pops the next result. A list serves
    .scalars().all()/.first(); a single object serves the scalar reads."""
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

    async def get(self, model, pk):
        return self._person

    async def commit(self):
        self.commits += 1

    def add(self, obj):
        pass

    async def flush(self):
        pass


PSID = "26414904614761138"


def _person(name="Nicole Kioko", location=None, state=None):
    p = Person(display_name=name, state=dict(state or ({"location": location} if location else {})))
    p.id = uuid.uuid4()
    return p


def _ident(p, channel="messenger", external_id=PSID):
    return types.SimpleNamespace(person_id=p.id, channel=channel, external_id=external_id,
                                 display_name=None, raw_profile=None)


def _user(wa_id, **kw):
    base = dict(wa_id=wa_id, location=None, phone=None, country_iso=None, country=None,
                flag_url=None, name="")
    base.update(kw)
    return types.SimpleNamespace(**base)


def _market(results, p, channel="messenger", key=PSID):
    return asyncio.run(market.customer_market(_FakeDB(results, p), channel, key))


# ── 1. WhatsApp: the number is the evidence ──────────────────────────────────

def test_whatsapp_prefix_decides_without_a_lookup():
    assert _market([], None, "whatsapp", "254712345678") == ("KES", {"country_iso": "KE", "country": "Kenya"})
    cur, loc = _market([], None, "whatsapp", "256700111222")
    assert cur == "USD" and loc["country_iso"] == "UG"
    cur, loc = _market([], None, "whatsapp", "260977123456")
    assert cur == "ZMW" and loc["country_iso"] == "ZM"
    cur, loc = _market([], None, "whatsapp", "27821234567")
    assert cur == "USD" and loc["country_iso"] == "ZA"


# ── 2. the website: the IP the storefront forwarded, nothing else ────────────

def test_web_visitor_is_placed_by_the_geolocated_user_row():
    kenyan = _user("web_abc", country_iso="KE", country="Kenya")
    assert _market([kenyan], None, "whatsapp", "web_abc")[0] == "KES"
    assert _market([_user("web_abc", country_iso="US", country="United States")], None,
                   "whatsapp", "web_abc")[0] == "USD"
    assert _market([None], None, "whatsapp", "web_abc") == ("USD", {})     # no row, no IP → USD
    assert _market([_user("web_abc")], None, "whatsapp", "web_abc") == ("USD", {})


# ── 3. Messenger merged with a +254 WhatsApp number ──────────────────────────

def test_merged_whatsapp_user_row_places_them_and_two_rows_do_not_crash():
    p = _person()
    shim = _user(PSID)                                          # the Messenger shim
    wa = _user("254712345678", country_iso="KE", country="Kenya")  # the WhatsApp row
    cur, loc = _market([_ident(p), [shim, wa], [_ident(p), _ident(p, "whatsapp", "254712345678")], []], p)
    assert cur == "KES" and loc == {"country_iso": "KE", "country": "Kenya"}
    # the chat turn's own lookup agrees, and survives the two rows
    cur2, loc2, name, _ = asyncio.run(rt._meta_market(
        _FakeDB([_ident(p), [shim, wa], [_ident(p), _ident(p, "whatsapp", "254712345678")], []], p),
        "messenger", PSID))
    assert cur2 == "KES" and loc2["country_iso"] == "KE" and name == "Nicole Kioko"


def test_a_merged_whatsapp_identity_alone_is_enough():
    p = _person()
    ev = asyncio.run(market.evidence_for_person(
        _FakeDB([[], [_ident(p), _ident(p, "whatsapp", "254712345678")], []], p), _ident(p), p))
    assert ev["country_iso"] == "KE" and ev["evidence"] == "merged WhatsApp number"
    # a Ugandan number merged the same way is evidence the other way
    q = _person()
    cur, loc = _market([_ident(q), [], [_ident(q, "whatsapp", "256700111222")], []], q)
    assert cur == "USD" and loc["country_iso"] == "UG"


def test_users_for_person_puts_the_phone_row_first():
    p = _person()
    shim, wa = _user(PSID, name="shim"), _user("254712345678", name="wa")
    rows = asyncio.run(market.users_for_person(_FakeDB([[shim, wa]], p), p.id))
    assert [u.name for u in rows] == ["wa", "shim"]
    rows = asyncio.run(market.users_for_person(_FakeDB([[wa, shim]], p), p.id))
    assert [u.name for u in rows] == ["wa", "shim"]


# ── 4. their own words, and a phone they gave us ─────────────────────────────

def test_stated_location_is_evidence():
    k = _person(location="Nairobi")
    cur, loc = _market([_ident(k), [], [], []], k)
    assert cur == "KES" and loc["country_iso"] == "KE"
    u = _person(location="Kampala, Uganda")
    assert _market([_ident(u), [], [], []], u)[0] == "USD"


def test_a_phone_with_its_country_code_is_evidence_but_an_assumed_one_is_not():
    p = _person()
    given = types.SimpleNamespace(type="phone", value="+254733000111", raw=None)
    assert _market([_ident(p), [], [], [given]], p)[0] == "KES"
    assumed = types.SimpleNamespace(type="phone", value="+254733000111",
                                    raw={"as_given": "0733000111", "region_assumed": True})
    assert _market([_ident(p), [], [], [assumed]], p) == ("USD", {})
    ugandan = types.SimpleNamespace(type="phone", value="+256700111222", raw=None)
    assert _market([_ident(p), [], [], [ugandan]], p)[0] == "USD"


def test_a_profile_phone_is_evidence():
    p = _person()
    assert _market([_ident(p), [_user(PSID, phone="+254722000111")], [], []], p)[0] == "KES"


# ── 5. what is NOT evidence ──────────────────────────────────────────────────

def test_a_facebook_locale_hint_never_decides_the_currency():
    # meta_webhook stamps person.state.country_iso from a profile locale
    # ("sw_KE") — a CRM flag hint, never a market decision.
    p = _person(state={"country_iso": "KE", "country": "Kenya", "flag_url": "x"})
    assert _market([_ident(p), [], [], []], p) == ("USD", {})


def test_a_name_and_the_page_are_not_evidence():
    p = _person(name="Nicole Kioko")
    assert _market([_ident(p), [], [], []], p) == ("USD", {})
    assert _market([None], None, "facebook", "someone") == ("USD", {})   # unknown identity


def test_carries_country_code():
    assert carries_country_code("+254712345678", "+254712345678")
    assert carries_country_code("254712345678", "+254712345678")
    assert carries_country_code("00254712345678", "+254712345678")
    assert carries_country_code("+254 712 345 678", "+254712345678")
    assert not carries_country_code("0712345678", "+254712345678")
    assert not carries_country_code("712345678", "+254712345678")
    assert not carries_country_code("", "+254712345678")
    assert not carries_country_code("0712345678", None)


# ── 6. capture_contact records what it assumed, and never stamps it ─────────

def _capture(results, person, phone, monkeypatch):
    recorded = {}

    async def fake_attach(db, person_id, type_, value, *, source=None, confidence=None, raw=None):
        recorded.update({"type": type_, "value": value, "raw": raw})
        return types.SimpleNamespace(type=type_, value=value, raw=raw)
    monkeypatch.setattr("app.services.reconcile.attach_identifier", fake_attach)
    db = _FakeDB(results, person)
    ctx = ToolContext(db=db, redis=None, wa_id=PSID, currency="USD", channel="messenger")
    out = asyncio.run(tools._capture_contact({"phone": phone}, ctx))
    return out, recorded, ctx


def test_bare_local_number_is_stored_as_assumed_and_stamps_no_country(monkeypatch):
    p = _person()
    shim = _user(PSID)
    # queries: select_identity → users → whatsapp identity for the number → users
    out, rec, ctx = _capture([_ident(p), [shim], None, [shim]], p, "0712345678", monkeypatch)
    assert rec["value"] == "+254712345678"
    assert rec["raw"]["region_assumed"] is True and rec["raw"]["as_given"] == "0712345678"
    assert out.get("country_assumed") is True and "country" not in out
    assert shim.country_iso is None and shim.phone == "+254712345678"
    assert ctx.currency == "USD"                                   # no evidence, no KES


def test_number_given_with_its_code_is_evidence(monkeypatch):
    p = _person()
    shim = _user(PSID)
    out, rec, _ = _capture([_ident(p), [shim], None, [shim]], p, "+254712345678", monkeypatch)
    assert rec["raw"]["region_assumed"] is False
    assert out["country"] == "Kenya" and shim.country_iso == "KE"
    assert p.state["country_iso"] == "KE"


def test_a_real_whatsapp_contact_on_the_same_number_corroborates_a_bare_number(monkeypatch):
    p = _person()
    shim = _user(PSID)
    wa_ident = _ident(p, "whatsapp", "254712345678")          # same person already
    out, rec, _ = _capture([_ident(p), [shim], wa_ident, [shim]], p, "0712345678", monkeypatch)
    assert rec["raw"]["region_assumed"] is False
    assert out["country"] == "Kenya" and shim.country_iso == "KE"


# ── 7. the shared catalogue link uses the same evidence ──────────────────────

def test_customer_currency_agrees_with_the_market():
    p = _person()
    shim, wa = _user(PSID), _user("254712345678", country_iso="KE", country="Kenya")
    db = _FakeDB([_ident(p), [shim, wa], [_ident(p), _ident(p, "whatsapp", "254712345678")], []], p)
    ctx = ToolContext(db=db, redis=None, wa_id=PSID, currency="USD", channel="messenger")
    assert asyncio.run(tools._customer_currency(ctx)) == "KES"
    ctx2 = ToolContext(db=_FakeDB([_ident(p), [], [], []], p), redis=None, wa_id=PSID,
                       currency="USD", channel="messenger")
    assert asyncio.run(tools._customer_currency(ctx2)) == "USD"
    ctx3 = ToolContext(db=_FakeDB([], None), redis=None, wa_id="254712345678",
                       currency="KES", channel="whatsapp")
    assert asyncio.run(tools._customer_currency(ctx3)) == "KES"


def test_the_public_comment_engine_and_the_panel_use_the_same_chain():
    import inspect
    src = inspect.getsource(rt._run_comment_engage)
    assert "_ccy = (await _meta_market(_db3, channel, ext))[0]" in src
    assert "evidence_for_person" in inspect.getsource(rt._meta_market)
    from app.routers import crm
    assert "users_for_person" in inspect.getsource(crm)
    assert "scalar_one_or_none" not in inspect.getsource(tools._capture_contact).split("if phone:")[1]
