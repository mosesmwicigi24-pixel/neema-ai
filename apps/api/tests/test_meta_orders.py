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


def test_meta_handoff_never_mints_a_phantom_conversation():
    """A Meta thread is keyed on (channel, external_id). Looking it up by wa_id
    misses and would CREATE Conversation(wa_id=PSID) — exactly how phantom
    contacts were born. Never invent one."""
    from app.agent.tools import _handoff_to_human

    class _NoConvDB(_DB):
        def __init__(self):
            super().__init__([None])
            self.added = []
        def add(self, obj):
            self.added.append(obj)

    db = _NoConvDB()
    ctx = ToolContext(db=db, redis=None, wa_id=PSID, currency="USD", channel="messenger")
    out = asyncio.run(_handoff_to_human({"reason": "wants a human"}, ctx))
    assert out["ok"] is False
    assert db.added == []                               # no phantom conversation


def test_meta_order_status_found_by_phone_not_psid(monkeypatch):
    """Orders are keyed on the PHONE; a Messenger buyer's handle is a PSID, so
    status lookup must go via their phone/person or their order is invisible."""
    from app.agent import tools
    captured = {}

    async def fake_identity(ctx):
        return "254712345678", "Meshack", "person-1"

    class _RowDB(_DB):
        async def execute(self, stmt):
            captured["stmt"] = str(stmt)
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    monkeypatch.setattr(tools, "_order_identity", fake_identity)
    ctx = ToolContext(db=_RowDB([]), redis=None, wa_id=PSID, currency="KES",
                      channel="messenger")
    out = asyncio.run(tools._check_order_status({}, ctx))
    assert out == {"found": False}
    # the query must filter on person_id / wa_id — never on the raw PSID handle
    assert "person_id" in captured["stmt"] and "wa_id" in captured["stmt"]


def test_merge_carries_an_in_progress_cart_to_the_phone_person():
    """A Messenger buyer moving to WhatsApp mid-order keeps the items they picked."""
    import types, uuid as _uuid
    from app.services.merge import merge_persons
    from app.models.person import Person as P

    primary, secondary = _uuid.uuid4(), _uuid.uuid4()
    sec = P(state={"agent_cart": {"items": [{"name": "Thurible", "qty": 1}]}})
    sec.id = secondary
    pri = P(state={})
    pri.id = primary

    class _MDB:
        def __init__(self): self.added = []
        async def execute(self, stmt):
            if type(stmt).__name__ == "Select":
                return types.SimpleNamespace(
                    scalars=lambda: types.SimpleNamespace(all=lambda: []))
            return None
        async def get(self, model, pk):
            return {primary: pri, secondary: sec}.get(pk)
        def add(self, obj): self.added.append(obj)
        async def flush(self): pass

    asyncio.run(merge_persons(_MDB(), primary, secondary))
    assert pri.state["agent_cart"]["items"][0]["name"] == "Thurible"   # cart survived

    # …but a cart the primary already started is never clobbered
    sec2 = P(state={"agent_cart": {"items": [{"name": "Thurible"}]}}); sec2.id = secondary
    pri2 = P(state={"agent_cart": {"items": [{"name": "Cassock"}]}}); pri2.id = primary

    class _MDB2(_MDB):
        async def get(self, model, pk):
            return {primary: pri2, secondary: sec2}.get(pk)

    asyncio.run(merge_persons(_MDB2(), primary, secondary))
    assert pri2.state["agent_cart"]["items"][0]["name"] == "Cassock"


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
