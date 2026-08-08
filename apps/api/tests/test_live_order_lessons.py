"""Lessons from the first real end-to-end order (WA-260808-M6NMK, 2026-08-08).

Moses ordered 200pcs of communion bread and paid KES 500 by M-Pesa. The order
worked — and surfaced four defects:
 1. Neema quoted a 250pcs pack that doesn't exist, corrected herself twice,
    and re-offered what was already accepted. The hub had three wafer packs
    (200/500/1000pcs) whose sizes are IN the product names all along.
 2. When he typed "Paid", she announced "payment received" while the hub still
    showed the proof UNDER REVIEW — a confirmation she had no right to give.
 3. The payment/receipt page showed no customer name or phone (hub-side fix).
 4. The real paid confirmation (the hub event) carried no receipt link.
"""
import asyncio
import json
import types

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.core.config import settings
from app.agent.prompt import build_system_prompt


def _flat() -> str:
    return " ".join(build_system_prompt(country_iso="KE", currency="KES").split())


# ── 1: pack sizes come from product names, options offered once ──────────────

def test_pack_sizes_are_read_from_names_not_guessed():
    flat = _flat()
    assert "THE NAME CARRIES THE PACK" in flat
    assert "never guessed, never averaged" in flat
    assert "present the fitting options TOGETHER" in flat
    assert "never drip corrections" in flat
    assert "never re-offer or re-confirm what the customer has already accepted" in flat


# ── 2: "paid" is a claim until the hub confirms ──────────────────────────────

def test_paid_is_verified_before_it_is_confirmed():
    flat = _flat()
    assert '"PAID" IS A CLAIM UNTIL THE HUB CONFIRMS IT' in flat
    assert "call `check_order_status` in that SAME turn" in flat
    assert 'NEVER announce "payment received/confirmed" on their word alone' in flat


# ── 4: the paid thank-you carries a short receipt link ───────────────────────

class _Redis:
    def __init__(self): self.kv = {}
    async def set(self, k, v, nx=None, ex=None):
        self.kv[k] = v
        return True


class _DB:
    def __init__(self, row): self._row = row
    async def execute(self, *a, **k):
        row = self._row
        return types.SimpleNamespace(scalar_one_or_none=lambda: row)


def test_receipt_link_is_shortened_through_our_redirect(monkeypatch):
    from app.services import hub_events as he
    monkeypatch.setattr(settings, "media_public_url", "https://neema.bethanyhouse.co.ke")
    row = types.SimpleNamespace(hub_payment_url="https://hub.bethanyhouse.co.ke/pay/longtoken123")
    r = _Redis()
    out = asyncio.run(he._receipt_link_for(_DB(row), r, {"order_number": "WA-260808-M6NMK"}))
    assert out.startswith("https://neema.bethanyhouse.co.ke/api/o/")
    ref = out.rsplit("/", 1)[1]
    stored = json.loads(r.kv[f"waref:{ref}"])
    assert stored["target"].endswith("/pay/longtoken123")


def test_receipt_link_degrades_gracefully(monkeypatch):
    from app.services import hub_events as he
    # No stored order → no link, never an error.
    assert asyncio.run(he._receipt_link_for(_DB(None), _Redis(),
                                            {"order_number": "WA-X"})) == ""
    # No public base → the raw target still goes out.
    monkeypatch.setattr(settings, "media_public_url", "")
    row = types.SimpleNamespace(hub_payment_url="https://hub.bethanyhouse.co.ke/pay/t")
    out = asyncio.run(he._receipt_link_for(_DB(row), None, {"order_number": "WA-X"}))
    assert out.endswith("/pay/t")


def test_celebration_and_template_paths_carry_the_receipt():
    import inspect
    from app.services import hub_events as he
    src = inspect.getsource(he._celebrate)
    assert "_receipt_link_for" in src
    assert "Include their receipt link" in src
    assert 'status_word += f". Receipt: {receipt}"' in src


# ── the General Nodier thread: chosen means chosen; trays stack ──────────────
# He said "silver tray"; asked for "the stackable tray … with a reserve of 200
# cups" — and was offered the GOLD tray as an alternative (he had to repeat
# "we want the silver one"), with 200 cups priced separately although every
# tray carries its 40 plastic cups free, and 200 cups of reserve means five
# trays stacked.

def test_chosen_means_chosen():
    flat = _flat()
    assert "CHOSEN MEANS CHOSEN" in flat
    assert "never re-offer its siblings" in flat
    assert ('A feature question ("does it stack?") is answered within their '
            "chosen line") in flat


def test_tray_trade_facts_cups_free_and_stacking():
    flat = _flat()
    assert "COMMUNION TRAYS" in flat
    assert "40 plastic cups included, FREE" in flat
    assert "each tray comes with its 40 cups free" in flat
    assert "Charge only for EXTRA cups" in flat
    assert "divide by 40" in flat
    assert "5 trays stacked together" in flat
    assert "never price the included cups separately" in flat


def test_price_flinch_offers_the_humbler_line_at_the_same_count():
    """Owner's note (2026-08-08): if the tray total feels like much, propose
    the aluminium at the SAME stacked count (cups still free) without dropping
    the silver — elegance, durability, easy maintenance stay on the table."""
    flat = _flat()
    assert "IF THE TRAY TOTAL MAKES THEM FLINCH" in flat
    assert "SAME count and configuration, cups still free" in flat
    assert "keeping the silver's crown" in flat
    assert "more elegant, more durable and easier to maintain" in flat
    assert "Reduce the LINE before the COUNT" in flat
    assert "never choose down for them" in flat
    # And CHOSEN MEANS CHOSEN sanctions exactly this one exception.
    assert "or the price makes them flinch" in flat
