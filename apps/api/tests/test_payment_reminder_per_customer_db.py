"""Payment reminders: ONE message per customer per run, real Postgres.

The live preview (2026-10-10) would have sent one buyer two reminders back to
back — one per unpaid order (WA-261010-MDKMA USD 45, WA-261010-LKEPE USD 485).
Now all of a customer's unpaid orders go in ONE short message, each order on
its own line with its number, amount and its own link; the once-per-order
guard is still claimed per order, so neither is re-chased early.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests.test_security_db import fresh_db, pytestmark  # noqa: F401
from tests.test_recovery_jobs_db import FakeRedis

ONE_WA, TWO_WA = "254755000011", "254766000022"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def pay(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.jobs import payment_followup
    from app.core import hub_client
    from app.services import n8n_bridge, meta_send

    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE agent_actions, deals, messages, order_events, users, "
                          "intercepts, conversations, persons CASCADE"))
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    maker = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                               class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(payment_followup, "AsyncSessionLocal", maker)
    monkeypatch.setattr(payment_followup, "within_quiet_hours", lambda *a, **k: True)

    hub_states: dict = {}

    async def status(order_id, redis=None):
        return {"payment_status": hub_states.get(order_id, "unpaid")}
    monkeypatch.setattr(hub_client, "fetch_order_status", status)

    sent = []

    async def waba(to, text, *a, **k):
        sent.append((to, text))
        return "wamid.x"

    async def meta(channel, to, text, *a, **k):
        sent.append((to, text))
    monkeypatch.setattr(n8n_bridge, "_send_waba", waba)
    monkeypatch.setattr(meta_send, "send_to_channel", meta)
    return {"maker": maker, "sent": sent, "hub": hub_states}


def _seed(maker, convs: dict, orders: list[tuple]):
    """convs: {wa: name}; orders: (wa, hub_id, number, total, currency, hours_ago)."""
    from app.models.conversation import Conversation
    from app.models.order_event import OrderEvent
    from app.models.user import User
    now = datetime.now(timezone.utc)

    async def go():
        async with maker() as db:
            for wa, name in convs.items():
                db.add(User(wa_id=wa, name=name))
                db.add(Conversation(id=uuid.uuid4(), wa_id=wa, channel="whatsapp",
                                    external_id=wa, last_message_at=now - timedelta(hours=3)))
            for wa, hid, num, total, ccy, ago in orders:
                db.add(OrderEvent(id=f"{wa}_{hid}", wa_id=wa, event_type="confirmed",
                                  hub_order_id=hid, hub_order_number=num, hub_total=total,
                                  hub_currency=ccy, hub_payment_url=f"https://pay.example/{hid}",
                                  payment_status="unpaid",
                                  created_at=now - timedelta(hours=ago)))
            await db.commit()
    run(go())


def test_two_unpaid_orders_for_one_customer_are_one_message(pay):
    from app.jobs import payment_followup as pf
    _seed(pay["maker"], {ONE_WA: "Hepsivardhan Rao"},
          [(ONE_WA, 901, "WA-261010-MDKMA", 45, "USD", 3),
           (ONE_WA, 902, "WA-261010-LKEPE", 485, "USD", 4)])
    r = FakeRedis()
    out = run(pf.run(send=True, redis=r))
    assert len(pay["sent"]) == 1, pay["sent"]                 # ONE message, not two
    to, text = pay["sent"][0]
    assert to == ONE_WA
    for bit in ("Hepsivardhan", "WA-261010-MDKMA", "USD 45", "https://pay.example/901",
                "WA-261010-LKEPE", "USD 485", "https://pay.example/902"):
        assert bit in text, (bit, text)
    assert "Rao" not in text                                   # first name only
    assert (out["candidates"], out["orders"], out["sent"]) == (1, 2, 1)
    # the guard is PER ORDER: both are claimed, so neither is re-reminded early
    assert r.kv.get("payfollow:901") == "1" and r.kv.get("payfollow:902") == "1"
    pay["sent"].clear()
    again = run(pf.run(send=True, redis=r))
    assert pay["sent"] == [] and again["skipped"] == 1


def test_two_customers_get_one_message_each(pay):
    from app.jobs import payment_followup as pf
    _seed(pay["maker"], {ONE_WA: "Grace", TWO_WA: "Peter"},
          [(ONE_WA, 911, "BH-911", 4500, "KES", 3),
           (TWO_WA, 912, "BH-912", 7000, "KES", 3),
           (TWO_WA, 913, "BH-913", 1200, "KES", 5)])
    run(pf.run(send=True, redis=FakeRedis()))
    assert sorted(to for to, _ in pay["sent"]) == [ONE_WA, TWO_WA]
    peter = next(t for to, t in pay["sent"] if to == TWO_WA)
    assert "BH-912" in peter and "BH-913" in peter and "BH-911" not in peter
    grace = next(t for to, t in pay["sent"] if to == ONE_WA)
    assert "BH-911" in grace and "KES 4,500" in grace and "BH-912" not in grace


def test_a_paid_order_is_left_out_of_the_reminder(pay):
    from app.jobs import payment_followup as pf
    _seed(pay["maker"], {ONE_WA: "Grace"},
          [(ONE_WA, 921, "BH-921", 4500, "KES", 3),
           (ONE_WA, 922, "BH-922", 9000, "KES", 3)])
    pay["hub"][922] = "paid"                                   # landed silently
    r = FakeRedis()
    run(pf.run(send=True, redis=r))
    assert len(pay["sent"]) == 1
    text = pay["sent"][0][1]
    assert "BH-921" in text and "BH-922" not in text
    assert "payfollow:922" not in r.kv                         # nothing claimed for it


def test_an_order_already_reminded_drops_out_and_a_new_one_still_goes(pay):
    from app.jobs import payment_followup as pf
    _seed(pay["maker"], {ONE_WA: "Grace"},
          [(ONE_WA, 931, "BH-931", 4500, "KES", 3),
           (ONE_WA, 932, "BH-932", 9000, "KES", 3)])
    r = FakeRedis()
    r.kv["payfollow:931"] = "1"                                # reminded yesterday
    run(pf.run(send=True, redis=r))
    assert len(pay["sent"]) == 1
    text = pay["sent"][0][1]
    assert "BH-932" in text and "BH-931" not in text
    assert "orders" not in text.split("\n")[0]                 # a single order reads singular


def test_a_dry_run_composes_one_message_and_claims_nothing(pay):
    from app.jobs import payment_followup as pf
    _seed(pay["maker"], {ONE_WA: "Grace"},
          [(ONE_WA, 941, "BH-941", 4500, "KES", 3),
           (ONE_WA, 942, "BH-942", 9000, "KES", 3)])
    r = FakeRedis()
    out = run(pf.run(send=False, redis=r, max_drafts=3))
    assert pay["sent"] == [] and not r.kv
    assert out["would_send"] == 1 and len(out["samples"]) == 1
    assert "BH-941" in out["samples"][0]["text"] and "BH-942" in out["samples"][0]["text"]
