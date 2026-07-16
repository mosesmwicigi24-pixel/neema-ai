"""Messenger/Instagram run the SAME order flow as WhatsApp — cart → confirm →
hub order (WhatsApp Orders) → payment details, in-thread.

The one thing a Meta contact lacks is a phone, and that's the hub customer's
key: create_order must ASK for it rather than bill an order to a page-scoped
PSID (the phantom-contact bug). The cart must also live on the PERSON for Meta —
they have no User row, so a User-keyed cart would silently lose every item.
"""
import asyncio
import uuid
from types import SimpleNamespace

from app.agent import cart as cartmod
from app.agent.tools import _order_identity, _create_order, ToolContext
from app.models.person import Person

PSID = "26414904614761138"


class _DB:
    """Serves a scripted sequence of scalar lookups; `get` returns the person."""
    def __init__(self, results, person=None):
        self._r = list(results)
        self._person = person

    async def execute(self, stmt):
        nxt = self._r.pop(0) if self._r else None
        items = nxt if isinstance(nxt, list) else ([nxt] if nxt is not None else [])
        return SimpleNamespace(
            scalar_one_or_none=lambda: items[0] if items else None,
            scalars=lambda: SimpleNamespace(first=lambda: items[0] if items else None,
                                            all=lambda: items))

    async def get(self, model, pk):
        return self._person

    async def commit(self):
        pass


def _person(name="Meshack Munyao"):
    p = Person(display_name=name, state={})
    p.id = uuid.uuid4()
    return p


def test_meta_order_uses_the_captured_phone_not_the_psid():
    person = _person()
    ident = SimpleNamespace(person_id=person.id, channel="messenger", external_id=PSID)
    phone_id = SimpleNamespace(value="+254712345678", type="phone")
    db = _DB([ident, phone_id], person=person)          # identity, then phone identifier
    ctx = ToolContext(db=db, redis=None, wa_id=PSID, currency="KES", channel="messenger")

    phone, name, pid = asyncio.run(_order_identity(ctx))
    assert phone == "254712345678"                      # the real number, '+' stripped
    assert phone != PSID                                # never the PSID
    assert name == "Meshack" and pid == person.id


def test_meta_order_without_a_phone_asks_instead_of_inventing_one(monkeypatch):
    """No phone → NO order. A PSID must never become a hub customer's phone."""
    person = _person()
    ident = SimpleNamespace(person_id=person.id, channel="messenger", external_id=PSID)
    db = _DB([ident, None, None], person=person)        # identity, no identifier, no user
    ctx = ToolContext(db=db, redis=None, wa_id=PSID, currency="KES", channel="messenger")

    async def fake_cart(db_, wa_id, channel="whatsapp"):
        return {"items": [{"name": "Thurible", "qty": 1, "unit_price": 12000,
                           "hub_product_id": 85}]}

    async def boom(*a, **k):
        raise AssertionError("must not push an order without a real phone")

    monkeypatch.setattr(cartmod, "get_cart", fake_cart)
    monkeypatch.setattr("app.core.hub_client.push_pending_order", boom)

    out = asyncio.run(_create_order({}, ctx))
    assert "no phone number" in out["error"]
    assert "capture_contact" in out["next_step"]        # tells Neema to ask, warmly


def test_whatsapp_order_identity_is_the_wa_id():
    user = SimpleNamespace(name="Moses Mwicigi", person_id="p-1", wa_id="254700111222")
    db = _DB([user])
    ctx = ToolContext(db=db, redis=None, wa_id="254700111222", currency="KES",
                      channel="whatsapp")
    phone, name, pid = asyncio.run(_order_identity(ctx))
    assert phone == "254700111222" and name == "Moses" and pid == "p-1"


def test_meta_cart_lives_on_the_person_not_a_missing_user_row():
    """A Meta contact has no User row — the cart must persist on their Person or
    every item silently vanishes between turns."""
    person = _person()
    ident = SimpleNamespace(person_id=person.id, channel="messenger", external_id=PSID)
    db = _DB([ident], person=person)
    cart = {"items": [{"name": "Thurible", "qty": 1, "unit_price": 12000}]}
    asyncio.run(cartmod.save_cart(db, PSID, cart, "messenger"))
    assert person.state["agent_cart"] == cart           # stored on the PERSON

    db2 = _DB([ident], person=person)
    got = asyncio.run(cartmod.get_cart(db2, PSID, "messenger"))
    assert got["items"][0]["name"] == "Thurible"        # and survives the next turn
