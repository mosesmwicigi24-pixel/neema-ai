"""The eval runner's throwaway-contact cleanup against a real Postgres
(verification pass 6: the recording-session test could not see a wrong
predicate — four mutants survived it). Skips cleanly without a database.

Seeds: contact A (person, WhatsApp identity, phone identifier, user,
messages, conversation); contact B whose person ALSO has a Messenger
identity; a Messenger identity whose external id equals A's number but
belongs to another person; an unrelated contact E. Cleaning A and B must
remove every row of A's, B's WhatsApp identity only (B's person stays), and
touch nothing of the Messenger person's or E's."""
import asyncio
import uuid

import pytest
import sqlalchemy as sa

from tests.test_security_db import _reachable, _sync_url, fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = pytest.mark.skipif(
    not (_sync_url() and _reachable(_sync_url())),
    reason="needs a reachable Postgres (CI migrations job / Docker harness)",
)

A, B, E, PSID = "254700000901", "254700000902", "254700000905", "1234567890123456"


def _seed(sync_url: str) -> dict:
    from app.models.conversation import Conversation
    from app.models.message import Message, MsgDirection, MsgSender
    from app.models.person import Identifier, Identity, Person
    from app.models.user import User
    from sqlalchemy.orm import Session
    eng = sa.create_engine(sync_url)
    ids = {}
    with Session(eng) as s:
        pa, pb, pm, pe = Person(), Person(), Person(), Person()
        s.add_all([pa, pb, pm, pe])
        s.flush()
        ids.update(pa=pa.id, pb=pb.id, pm=pm.id, pe=pe.id)
        s.add_all([
            Identity(person_id=pa.id, channel="whatsapp", external_id=A),
            Identifier(person_id=pa.id, type="phone", value="+" + A),
            Identity(person_id=pb.id, channel="whatsapp", external_id=B),
            Identity(person_id=pb.id, channel="messenger", external_id=PSID),
            Identifier(person_id=pb.id, type="phone", value="+" + B),
            Identity(person_id=pm.id, channel="messenger", external_id=A),       # same digits, another channel
            Identity(person_id=pe.id, channel="whatsapp", external_id=E),
            Identifier(person_id=pe.id, type="phone", value="+" + E),
            User(wa_id=A, person_id=pa.id), User(wa_id=B, person_id=pb.id), User(wa_id=E, person_id=pe.id),
            Conversation(wa_id=A), Conversation(wa_id=E),
            Message(wa_id=A, channel="whatsapp", direction=MsgDirection.inbound, sender=MsgSender.user, text="hi"),
            Message(wa_id=A, channel="whatsapp", direction=MsgDirection.outbound, sender=MsgSender.ai, text="hello"),
            Message(wa_id=E, channel="whatsapp", direction=MsgDirection.inbound, sender=MsgSender.user, text="hi"),
        ])
        s.commit()
    eng.dispose()
    return ids


def _count(sync_url: str, table: str, where: str, **params) -> int:
    eng = sa.create_engine(sync_url)
    with eng.connect() as c:
        n = c.execute(sa.text(f"select count(*) from {table} where {where}"), params).scalar_one()
    eng.dispose()
    return n


def test_cleanup_removes_every_row_of_the_contact_and_nothing_of_anyone_else(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.jobs import agent_eval

    ids = _seed(fresh_db)
    async_url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(agent_eval, "AsyncSessionLocal", maker)

    asyncio.run(agent_eval._cleanup_contacts(None, [A, B]))
    asyncio.run(engine.dispose())

    # A: every row gone — person, identity, identifier, user, messages, conversation
    assert _count(fresh_db, "persons", "id = :id", id=ids["pa"]) == 0
    assert _count(fresh_db, "identities", "channel = 'whatsapp' and external_id = :x", x=A) == 0
    assert _count(fresh_db, "identifiers", "person_id = :id", id=ids["pa"]) == 0
    assert _count(fresh_db, "users", "wa_id = :x", x=A) == 0
    assert _count(fresh_db, "messages", "wa_id = :x", x=A) == 0
    assert _count(fresh_db, "conversations", "wa_id = :x", x=A) == 0
    # B: the WhatsApp identity and user go; the person stays because Messenger still points at it
    assert _count(fresh_db, "identities", "channel = 'whatsapp' and external_id = :x", x=B) == 0
    assert _count(fresh_db, "persons", "id = :id", id=ids["pb"]) == 1
    assert _count(fresh_db, "identities", "person_id = :id", id=ids["pb"]) == 1
    assert _count(fresh_db, "identifiers", "person_id = :id", id=ids["pb"]) == 1
    # the Messenger person who happens to share A's digits is untouched (the channel matters)
    assert _count(fresh_db, "identities", "channel = 'messenger' and external_id = :x", x=A) == 1
    assert _count(fresh_db, "persons", "id = :id", id=ids["pm"]) == 1
    # E: untouched
    assert _count(fresh_db, "persons", "id = :id", id=ids["pe"]) == 1
    assert _count(fresh_db, "messages", "wa_id = :x", x=E) == 1
    assert _count(fresh_db, "conversations", "wa_id = :x", x=E) == 1
    assert _count(fresh_db, "users", "wa_id = :x", x=E) == 1
    assert isinstance(uuid.UUID(str(ids["pe"])), uuid.UUID)
