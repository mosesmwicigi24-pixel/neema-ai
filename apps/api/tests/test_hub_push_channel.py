"""Neema must tell the hub WHICH APP the customer used.

The hub has always accepted source_channel (whatsapp|messenger|instagram);
Neema hardcoded "channel": "whatsapp" and never sent it. So a real Messenger
buyer's order arrived labelled WhatsApp, and the hub offered a WhatsApp button
that could not reach her — her thread is keyed by a 17-digit page-scoped id,
while the phone on the order (a Central African Republic number) keys nothing.
"""
import pytest

from app.core import hub_client


def _payload_for(monkeypatch, channel):
    """Run push_pending_order far enough to capture the payload it POSTs."""
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"order_id": 1, "order_number": "WA-1", "total_amount": 100,
                    "currency_code": "KES", "public_url": "https://hub/order/x",
                    "public_token": "x"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(hub_client.httpx, "AsyncClient", lambda **kw: _Client())

    async def _no_customer(_wa):
        return None

    monkeypatch.setattr(hub_client, "_find_customer_id", _no_customer)
    return captured


@pytest.mark.asyncio
@pytest.mark.parametrize("channel,expected", [
    ("messenger", "messenger"),
    ("instagram", "instagram"),
    ("whatsapp",  "whatsapp"),
    # Facebook and Messenger are one inbox to the customer; the hub's word is
    # 'messenger'.
    ("facebook",  "messenger"),
    # Anything the hub cannot name falls back rather than failing the order.
    ("tiktok",    "whatsapp"),
    (None,        "whatsapp"),
])
async def test_the_real_channel_reaches_the_hub(monkeypatch, channel, expected):
    captured = _payload_for(monkeypatch, channel)
    catalog = [{"id": 1, "hub_product_id": 1, "name": "Aluminium Tray", "sku": "COM-AT-001",
                "price": 7000.0, "prices": {"KES": 7000.0}}]

    await hub_client.push_pending_order(
        catalog, wa_id="23672582495", first_name="Stella", country_iso="CF",
        items=[{"name": "Aluminium Tray", "qty": 1, "unit_price": 7000.0}],
        source_channel=channel,
    )

    body = captured["json"]
    assert body["source_channel"] == expected
    # The sales BUCKET is unchanged — a chat sale is a chat sale whichever app
    # carried it; only the app label is new.
    assert body["channel"] == "whatsapp"


@pytest.mark.asyncio
async def test_the_note_names_the_app_the_customer_used(monkeypatch):
    captured = _payload_for(monkeypatch, "messenger")
    catalog = [{"id": 1, "hub_product_id": 1, "name": "Aluminium Tray", "sku": "COM-AT-001",
                "price": 7000.0, "prices": {"KES": 7000.0}}]

    await hub_client.push_pending_order(
        catalog, wa_id="23672582495", first_name="Stella", country_iso="CF",
        items=[{"name": "Aluminium Tray", "qty": 1, "unit_price": 7000.0}],
        source_channel="messenger",
    )

    assert "Messenger order via Neema" in captured["json"]["notes"]
