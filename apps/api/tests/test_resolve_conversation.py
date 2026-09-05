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


def test_a_captured_phone_resolves_through_identifiers_with_no_order_ref():
    # capture_contact stores '+<digits>' as an Identifier; the link sends bare
    # digits and no order number. identifier -> person -> PSID -> thread.
    person_id = uuid.uuid4()
    conv = _conv("conv-psid", channel="messenger")
    db = _DB([
        [],                     # 1: no thread keyed by the digits
        [],                     # 2: no order carries them either
        None,                   # 3: no Identity is the phone
        person_id,              # 4: but an Identifier claims it
        ["27950420514615789"],  # 5: the person's channel identities
        [conv],                 # 6: the PSID-keyed thread
    ])

    out = asyncio.run(resolve_conversation(key="+23672582495", ref="", db=db, agent=None))

    assert out == {"conversation_id": "conv-psid"}


# ── resolving is only half the job: the inbox has to be able to RENDER it ────
# The link resolved correctly and still showed "Select a conversation". The
# thread pane reads conversations.find(c => c.id === activeConvId), and the
# client paints from a snapshot capped at 600 rows — so every link to a thread
# older than the 600 most recent selected an id the list did not contain. The
# full list is 13,000+ rows and 13 MB, so waiting for it is not an answer.
# GET /admin/conversations/{id} lets the client fetch just that one row.

def test_one_conversation_is_served_in_the_same_shape_as_the_list():
    import inspect
    from app.routers import admin

    # Both the list and the single fetch go through ONE serializer, so a row
    # fetched by id can never drift from the same row inside the list.
    assert hasattr(admin, "_conversation_rows")
    assert "_conversation_rows" in inspect.getsource(admin.list_conversations)
    assert "_conversation_rows" in inspect.getsource(admin.get_conversation)


def test_the_literal_resolve_path_is_registered_before_the_id_route():
    # /conversations/resolve must keep winning over /conversations/{conv_id};
    # FastAPI matches in registration order, so a wrongly-ordered pair would
    # send "resolve" into the id handler and 422 on the UUID parse.
    from app.routers import admin

    paths = [r.path for r in admin.router.routes]
    assert "/conversations/resolve" in paths
    assert "/conversations/{conv_id}" in paths
    assert paths.index("/conversations/resolve") < paths.index("/conversations/{conv_id}")


def test_an_unknown_conversation_is_a_404_not_an_empty_body():
    import pytest
    from fastapi import HTTPException
    from app.routers.admin import get_conversation

    db = _DB([[]])                            # no such conversation

    with pytest.raises(HTTPException) as e:
        asyncio.run(get_conversation(conv_id=uuid.uuid4(), db=db, agent=None))
    assert e.value.status_code == 404
