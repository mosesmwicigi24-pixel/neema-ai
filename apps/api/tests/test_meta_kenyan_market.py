"""Meta channels default to USD, but a customer whose captured location resolves
to Kenya IS the Kenyan market (the Meshack 'Kenya money' case): real KES
catalogue prices — never a USD conversion — flipped in the SAME turn the
location is captured. Also: fuller name wins so a self-stated 'Meshack' never
shadows the profile's 'Meshack Munyao'."""
import asyncio
import uuid
from types import SimpleNamespace

from app.agent.runtime import _meta_market, _meta_addendum
from app.agent.tools import _capture_contact, ToolContext
from app.models.person import Person

PSID = "26414904614761138"


class _FakeDB:
    """Scripted: every execute() pops the next result; get() returns the person."""
    def __init__(self, results, person=None):
        self._results = list(results)
        self._person = person
        self.commits = 0

    async def execute(self, stmt):
        nxt = self._results.pop(0) if self._results else None
        return SimpleNamespace(scalar_one_or_none=lambda: nxt,
                               scalars=lambda: SimpleNamespace(first=lambda: nxt))

    async def get(self, model, pk):
        return self._person

    async def commit(self):
        self.commits += 1


def _person(name=None, location=None):
    p = Person(display_name=name, state={"location": location} if location else {})
    p.id = uuid.uuid4()
    return p


def _ident(person, display_name=None):
    return SimpleNamespace(person_id=person.id, channel="messenger",
                           external_id=PSID, display_name=display_name)


def test_meta_market_flips_to_kes_for_captured_kenyan_location():
    person = _person(name="Meshack Munyao", location="Machakos . kenya")
    db = _FakeDB([_ident(person), None], person=person)   # identity, then no User row
    currency, loc, name = asyncio.run(_meta_market(db, "messenger", PSID))
    assert currency == "KES"
    assert loc["country_iso"] == "KE"
    assert name == "Meshack Munyao"                        # greeted by name from turn one


def test_meta_market_defaults_usd_without_location():
    person = _person(name="Jane")
    db = _FakeDB([_ident(person), None], person=person)
    currency, loc, _ = asyncio.run(_meta_market(db, "messenger", PSID))
    assert currency == "USD" and loc == {}
    # South Africa stays USD too — only Kenya is the KES market
    person2 = _person(location="Somerset East, South Africa")
    db2 = _FakeDB([_ident(person2), None], person=person2)
    currency2, loc2, _ = asyncio.run(_meta_market(db2, "messenger", PSID))
    assert currency2 == "USD" and loc2["country_iso"] == "ZA"


def test_capture_contact_flips_currency_same_turn():
    person = _person()
    db = _FakeDB([_ident(person)], person=person)          # _select_identity hit
    ctx = ToolContext(db=db, redis=None, wa_id=PSID, currency="USD", channel="messenger")
    out = asyncio.run(_capture_contact({"location": "Machakos, Kenya"}, ctx))
    assert ctx.currency == "KES"                           # same-turn market switch
    assert out["currency_now"] == "KES" and "KES" in out["note"]
    assert person.state["location"] == "Machakos, Kenya"
    assert db.commits == 1


def test_capture_contact_keeps_usd_for_non_kenyan_location():
    person = _person()
    db = _FakeDB([_ident(person)], person=person)
    ctx = ToolContext(db=db, redis=None, wa_id=PSID, currency="USD", channel="messenger")
    out = asyncio.run(_capture_contact({"location": "Kampala, Uganda"}, ctx))
    assert ctx.currency == "USD" and "currency_now" not in out


def test_capture_name_fuller_wins_both_directions():
    # Profile already knows "Meshack Munyao"; customer types "Meshack" → keep the fuller.
    person = _person(name="Meshack Munyao")
    user = SimpleNamespace(name="", person_id=person.id)
    db = _FakeDB([_ident(person), user], person=person)    # identity, then User select
    ctx = ToolContext(db=db, redis=None, wa_id=PSID, currency="USD", channel="messenger")
    out = asyncio.run(_capture_contact({"name": "Meshack"}, ctx))
    assert out["name"] == "Meshack Munyao"
    assert person.display_name == "Meshack Munyao" and user.name == "Meshack Munyao"

    # Stores only know "Meshack"; customer gives the full name → upgrade everywhere.
    person2 = _person(name="Meshack")
    user2 = SimpleNamespace(name="Meshack", person_id=person2.id)
    db2 = _FakeDB([_ident(person2, display_name="Meshack"), user2], person=person2)
    ctx2 = ToolContext(db=db2, redis=None, wa_id=PSID, currency="USD", channel="messenger")
    out2 = asyncio.run(_capture_contact({"name": "Meshack Munyao"}, ctx2))
    assert out2["name"] == "Meshack Munyao"
    assert person2.display_name == "Meshack Munyao" and user2.name == "Meshack Munyao"


def test_meta_addendum_kenya_rule_only_while_usd():
    usd = _meta_addendum("USD")
    assert "do NOT convert" in usd and "capture_contact" in usd
    assert "IN THAT SAME TURN" in usd                      # hard capture rule
    assert "ease of communication" in usd                  # ask the number to close
    kes = _meta_addendum("KES")
    assert "do NOT convert" not in kes                     # already the Kenyan market
