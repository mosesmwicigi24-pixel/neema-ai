"""The hub→Neema chat deep link, resolved server-side.

The hub links by the customer's phone — the only key it has. A WhatsApp
thread matches directly, but Stella's case is the one this exists for: a
Facebook customer whose thread is keyed by PSID, whose phone lives only on
the order record, and whose profile has no phone identity at all. The
resolver walks order → person → identities → thread.
"""
import asyncio
import uuid
from types import SimpleNamespace

from app.routers.admin import resolve_conversation


class _DB:
    """Serves a scripted sequence of results; mirrors the house _DB style but
    also answers .all() for row-tuple selects (the order_events lookup)."""

    def __init__(self, results):
        self._r = list(results)

    async def execute(self, stmt):
        nxt = self._r.pop(0) if self._r else None
        items = nxt if isinstance(nxt, list) else ([nxt] if nxt is not None else [])
        return SimpleNamespace(
            all=lambda: items,
            scalar_one_or_none=lambda: items[0] if items else None,
            scalars=lambda: SimpleNamespace(
                first=lambda: items[0] if items else None,
                all=lambda: items,
            ),
        )


def _conv(cid, channel="whatsapp"):
    return SimpleNamespace(id=cid, channel=channel, last_message_at=None)


def test_a_whatsapp_thread_resolves_by_phone():
    conv = _conv("conv-wa")
    db = _DB([[conv]])                       # 1: direct thread-key hit

    out = asyncio.run(resolve_conversation(key="+254722000111", ref="", db=db, agent=None))

    assert out == {"conversation_id": "conv-wa"}


def test_a_meta_thread_resolves_through_the_order():
    # Stella's shape: PSID-keyed messenger thread, phone known only to the
    # order, no phone identity anywhere.
    person_id = uuid.uuid4()
    conv = _conv("conv-psid", channel="messenger")
    db = _DB([
        [],                                   # 1: no thread keyed by the phone
        [(person_id, "23672582495")],         # 2: the order knows the person
        ["27950420514615789"],                # 3: the person's identity PSIDs
        [conv],                               # 4: the PSID-keyed thread
    ])

    out = asyncio.run(resolve_conversation(
        key="23672582495", ref="WA-260819-ALRXF", db=db, agent=None))

    assert out == {"conversation_id": "conv-psid"}


def test_an_unknown_key_says_so_instead_of_guessing():
    db = _DB([
        [],     # no thread by digits
        [],     # no order knows this number
        None,   # no identity carries it
    ])

    out = asyncio.run(resolve_conversation(key="999999999999", ref="", db=db, agent=None))

    assert out == {"conversation_id": None}


def test_a_person_with_threads_on_two_channels_prefers_whatsapp():
    person_id = uuid.uuid4()
    wa = _conv("conv-wa", channel="whatsapp")
    fb = _conv("conv-fb", channel="messenger")
    db = _DB([
        [],                                   # no direct hit
        [(person_id, "254700000001")],        # order -> person
        ["psid-1", "254700000001"],           # identities on both channels
        [fb, wa],                             # both threads come back
    ])

    out = asyncio.run(resolve_conversation(
        key="254700000001", ref="POS-1", db=db, agent=None))

    assert out == {"conversation_id": "conv-wa"}, "WhatsApp thread wins the tie"
