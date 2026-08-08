"""Humane-intelligence lift: presence indicators, grounded product details,
mood/slot-check prompt contracts, deeper history."""
import asyncio
import types

from app.core.config import settings
from app.services import wa_native as wn


def test_whatsapp_presence_call_shape(monkeypatch):
    """Read receipt + typing indicator ride ONE Cloud API call with the wamid."""
    monkeypatch.setattr(settings, "waba_token", "T", raising=False)
    monkeypatch.setattr(settings, "waba_phone_number_id", "PNID", raising=False)
    sent = {}

    class _Resp:
        is_success = True

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            sent.update(url=url, json=json)
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    asyncio.run(wn._mark_read_and_typing("wamid.XYZ"))
    assert sent["json"]["status"] == "read"
    assert sent["json"]["message_id"] == "wamid.XYZ"
    assert sent["json"]["typing_indicator"] == {"type": "text"}
    # no wamid / no creds → silently does nothing
    sent.clear()
    asyncio.run(wn._mark_read_and_typing(None))
    assert sent == {}


def test_meta_typing_on_shape(monkeypatch):
    from app.services import meta_send as ms
    monkeypatch.setattr(ms, "token_for_page", lambda pid: "PAGETOK")
    sent = {}

    class _Resp:
        is_success = True

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, params=None, json=None):
            sent.update(url=url, params=params, json=json)
            return _Resp()

    monkeypatch.setattr(ms.httpx, "AsyncClient", _Client)
    asyncio.run(ms.send_typing_on("PSID9", page_id="PG"))
    assert sent["json"] == {"recipient": {"id": "PSID9"}, "sender_action": "typing_on"}
    assert sent["params"] == {"access_token": "PAGETOK"}


def test_search_results_carry_hub_details(monkeypatch):
    """The enriched hub description reaches the model (capped), so product talk
    is specific — and absent descriptions add no empty field."""
    from app.agent import tools as t

    async def fake_catalog(db, redis):
        return [
            {"name": "Cassock", "sku": "V1", "category": "Vestments",
             "price": 12000, "description": "Mint poly-cotton, custom embroidery."},
            {"name": "Stole", "sku": "V2", "category": "Vestments",
             "price": 2200, "description": ""},
        ]
    monkeypatch.setattr(t.svc, "catalog_items", fake_catalog)
    ctx = t.ToolContext(db=None, redis=None, wa_id="254700000001", read_only=True)
    out = asyncio.run(t._search_catalog({"query": ""}, ctx))
    by_name = {r["name"]: r for r in out["results"]}
    assert by_name["Cassock"]["details"].startswith("Mint poly-cotton")
    assert "details" not in by_name["Stole"]


def test_prompt_carries_mood_slots_and_grounding():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(currency="KES")
    assert "READ THE ROOM" in p
    assert "SLOT CHECK" in p
    assert "GROUNDED DETAILS ONLY" in p
    assert "UPSET" in p and "no emoji, no selling" in p


def test_history_window_is_forty():
    import inspect
    from app.agent import runtime
    src = inspect.getsource(runtime.run_turn)
    assert "limit=40" in src


def test_prompt_prices_the_photo_instead_of_asking_which_item():
    """A photo + 'how much?' is a complete question — Pastor Pius sent a tray of
    cups and was asked which item he meant. The persona must forbid that."""
    from app.agent.prompt import build_system_prompt
    # Normalised so the assertions survive re-wrapping of the prompt text.
    p = " ".join(build_system_prompt(currency="KES").split())
    assert "PRICE WHAT IS IN THE PHOTO" in p
    # Lead with the primary object's price, never a clarifying question.
    assert "which item are you asking about" in p
    assert "ONE primary object" in p
    # The second item in the same photo is quoted and offered in one breath.
    assert "Aluminium Tray is KES 7,000" in p
    assert "50-cup pack of plastic cups is KES 500" in p
    # Cups are catalogued per piece — never quote the unit price beside a tray.
    assert "Cups are catalogued PER PIECE" in p
