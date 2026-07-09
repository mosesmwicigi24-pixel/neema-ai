"""Attribution rollup: leads + orders + revenue grouped by (source, post), with
orders of unknown origin reported honestly as unattributed.
"""
import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.routers.crm import attribution


class _Res:
    def __init__(self, items): self._items = items
    def scalars(self): return SimpleNamespace(all=lambda: self._items)


class _FakeDB:
    """Serves the four selects in order: users, persons, identities, orders."""
    def __init__(self, users, persons, idents, orders):
        self._seq = [users, persons, idents, orders]
    async def execute(self, stmt):
        return _Res(self._seq.pop(0))


def test_attribution_groups_by_source_and_reports_unattributed():
    p_fb = uuid.uuid4()      # came via a facebook comment on POST9 (waref bridge)
    p_tk = uuid.uuid4()      # told us on WhatsApp they found us on TikTok
    p_un = uuid.uuid4()      # ordered but origin unknown

    persons = [
        SimpleNamespace(id=p_fb, state={"lead_source": "facebook", "source_post": "POST9"}),
        SimpleNamespace(id=p_tk, state={}),
        SimpleNamespace(id=p_un, state={}),
    ]
    users = [
        SimpleNamespace(wa_id="254701", person_id=p_tk, state={"lead_source": "tiktok"}),
        SimpleNamespace(wa_id="254702", person_id=p_un, state={}),
    ]
    idents = []              # no extra comment identities in this scenario
    orders = [
        SimpleNamespace(person_id=p_fb, wa_id="x", hub_total=Decimal("13000"),
                        subtotal=None, payment_status="paid"),
        SimpleNamespace(person_id=None, wa_id="254701", hub_total=None,
                        subtotal=Decimal("5000"), payment_status="unpaid"),
        SimpleNamespace(person_id=p_un, wa_id="254702", hub_total=Decimal("700"),
                        subtotal=None, payment_status="paid"),
    ]

    out = asyncio.run(attribution(db=_FakeDB(users, persons, idents, orders), agent=None))

    by_src = {(r["source"], r["post"]): r for r in out["sources"]}
    fb = by_src[("facebook", "POST9")]
    assert fb["leads"] == 1 and fb["orders"] == 1
    assert fb["revenue"] == 13000.0 and fb["paid_revenue"] == 13000.0
    tk = by_src[("tiktok", None)]
    assert tk["leads"] == 1 and tk["orders"] == 1 and tk["revenue"] == 5000.0
    assert out["unattributed"]["orders"] == 1 and out["unattributed"]["revenue"] == 700.0
    assert out["sources"][0] == fb                      # sorted by revenue desc
    assert out["totals"]["orders"] == 3 and out["totals"]["revenue"] == 18700.0
