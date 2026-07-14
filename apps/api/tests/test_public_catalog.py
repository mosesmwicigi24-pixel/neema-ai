"""The shared customer catalog card: a real USD price (never $0 for an
international viewer), and — for varied products — the size/colour options with
their own prices plus a price range."""
from app.routers.public import _card, _usd_price


def test_usd_price_prefers_hub_else_approximates_never_zero(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "usd_kes_rate", 100, raising=False)
    assert _usd_price(13000, 130) == 130       # hub USD wins
    assert _usd_price(13000, 0) == 130         # $0 in hub → approx from KES, not 0
    assert _usd_price(13000, None) == 130      # missing → approx
    assert _usd_price(30, 0) == 0.3            # small item keeps cents, never $0
    assert _usd_price(None, None) is None      # genuinely unknown
    assert _usd_price(0, 0) is None


def test_card_has_nonzero_usd_and_no_variants_for_simple():
    p = {"slug": "bell", "name": "BELL", "category": "Accessories",
         "description": "An altar bell", "price_kes": 2500, "price_usd": 0.0,
         "image_url": "http://x/bell.webp", "is_producible": False, "in_stock": True}
    card = _card(p)
    assert card["price_usd"] == 25 and "variants" not in card   # 2500/100, not $0


def test_card_surfaces_variants_and_range_for_varied_product():
    p = {"slug": "thurible", "name": "Thurible", "category": "Communion",
         "description": "Incense burner", "price_kes": 12000, "price_usd": 120,
         "image_url": "http://x/t.webp", "is_producible": False, "in_stock": True,
         "price_min_kes": 9000, "price_max_kes": 15000,
         "variants": [
             {"name": "S / GOLD", "attributes": {"Size": "S", "Colour": "GOLD"},
              "price_kes": 9000, "price_usd": 90},
             {"name": "L / GOLD", "attributes": {"Size": "L", "Colour": "GOLD"},
              "price_kes": 15000, "price_usd": 150},
         ]}
    card = _card(p)
    assert card["price_from_kes"] == 9000 and card["price_to_kes"] == 15000
    assert card["price_from_usd"] == 90 and card["price_to_usd"] == 150
    labels = {v["label"]: v for v in card["variants"]}
    assert set(labels) == {"S / GOLD", "L / GOLD"}
    assert labels["S / GOLD"]["price_kes"] == 9000 and labels["S / GOLD"]["price_usd"] == 90
    assert labels["L / GOLD"]["price_usd"] == 150
