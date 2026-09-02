"""The customer's order link must reach their order — and never a blank chat.

A real buyer was told "Here's your order link: …/api/o/E161A5" and tapped into
an empty WhatsApp thread: /api/o/ is a redis-backed TAP-TO-ORDER shortener
whose targets are storefront product pages, and whose miss-path 302s to a bare
wa.me chat. Her ref had expired, so that is exactly what she got — and she had
no order in the database at all.

These tests pin the replacement (/api/r/, Postgres-backed) and, above all, the
one assertion that would have caught the original defect: a dead order link
must NOT resolve to a WhatsApp chat.
"""
import pytest

from app.routers.order_link import _ALPHABET, new_short_ref


def test_short_ref_is_readable_over_the_phone():
    """A customer reads this aloud to an agent — no characters that collide."""
    for _ in range(200):
        ref = new_short_ref()
        assert len(ref) == 6
        # Every character comes from the readable alphabet. NOT `ref.isupper()`:
        # an all-digit ref like "428729" reads aloud perfectly but has no cased
        # character, so isupper() is False. With 8 digits in a 32-character
        # alphabet that is (8/32)**6 per ref — ~4.8% across 200 draws, so this
        # test failed roughly one CI run in twenty for no real reason.
        assert set(ref) <= set(_ALPHABET)
        assert not any(c.islower() for c in ref)
        # I/O/0/1 are the pairs people mishear and mistype.
        assert not (set(ref) & set("IO01"))


@pytest.mark.asyncio
async def test_a_dead_ref_never_lands_in_a_whatsapp_chat(monkeypatch):
    """THE regression. The old shortener answered a miss with wa.me/<number>
    (or facebook.com), which is how a customer ended up in a blank thread
    holding what she had been told was her order link."""
    from app.routers import order_link

    class _NoRows:
        async def execute(self, *_a, **_k):
            class R:
                def scalar_one_or_none(self_inner):
                    return None
            return R()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(order_link, "AsyncSessionLocal", lambda: _NoRows())

    resp = await order_link.order_redirect("ZZZZZZ", request=None)

    target = resp.headers["location"]
    assert "wa.me" not in target, "a dead order link must not dump the customer into a chat"
    assert "facebook.com" not in target
    assert target.startswith("https://")


@pytest.mark.asyncio
async def test_a_live_ref_reaches_the_durable_order_page(monkeypatch):
    from app.routers import order_link

    class _Row:
        hub_public_url = "https://hub.bethanyhouse.co.ke/order/" + "a" * 48
        hub_payment_url = "https://hub.bethanyhouse.co.ke/pay/expired"

    class _OneRow:
        async def execute(self, *_a, **_k):
            class R:
                def scalar_one_or_none(self_inner):
                    return _Row()
            return R()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(order_link, "AsyncSessionLocal", lambda: _OneRow())

    resp = await order_link.order_redirect("ABC234", request=None)

    # The DURABLE page, not the 72-hour pay session that killed all 88 links.
    assert resp.headers["location"] == _Row.hub_public_url
    assert "/pay/" not in resp.headers["location"]


@pytest.mark.asyncio
async def test_a_lookup_failure_still_redirects_somewhere_useful(monkeypatch):
    """Postgres down must not 500 in a customer's face."""
    from app.routers import order_link

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("db down")
        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(order_link, "AsyncSessionLocal", lambda: _Boom())

    resp = await order_link.order_redirect("ABC234", request=None)

    assert resp.status_code == 302
    assert "wa.me" not in resp.headers["location"]
