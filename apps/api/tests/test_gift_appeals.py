"""Gift requests and hardship appeals: one warm no, one blessing, then peace.

The Bangladesh thread (2026-08-08): a customer priced the $180 tray, then
began an appeal chain — "I am a poor person, please give me a gift", photos
of gatherings to persuade, blessings traded message for message. Neema kept
replying, and even promised the team would "consider" the gift, which only
extended false hope and the chain.

The owner's protocol, codified: decline once with dignity and open the
budget door; if they insist (or send photos to persuade), ONE closing
scripture blessing and pause_conversation — silence after a blessing is
kindness, not rudeness. The shop door stays open if they return to buy.
"""
import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent.prompt import build_system_prompt


def _flat() -> str:
    return " ".join(build_system_prompt(country_iso="KE", currency="KES").split())


def test_decline_once_and_open_the_budget_door():
    flat = _flat()
    assert "GIFT REQUESTS AND HARDSHIP APPEALS" in flat
    assert "DECLINE once, gently" in flat
    assert "a smaller size, fewer pieces, an item within their budget" in flat


def test_no_false_hope_of_team_consideration():
    flat = _flat()
    assert 'do NOT promise that the team will "consider" a gift request' in flat
    assert "extends false hope" in flat


def test_insistence_gets_one_blessing_then_the_chain_ends():
    flat = _flat()
    assert "sending photos of their situation to persuade" in flat
    assert "never reciprocate message-for-message" in flat
    assert "ONE closing word of blessing" in flat
    assert "Philippians 4:19" in flat
    assert "call `pause_conversation`" in flat
    assert "silence after a blessing is kindness" in flat


def test_the_shop_door_stays_open():
    flat = _flat()
    assert "if they later return able to buy within their means" in flat
    assert "with no reference to the appeal" in flat


def test_pause_tool_knows_the_appeal_case():
    from app.agent.tools import TOOLS
    desc = next(t["description"] for t in TOOLS if t["name"] == "pause_conversation")
    assert "gift/hardship appeal" in desc
    assert "AFTER your one scripture blessing" in desc
    assert "Never use it on a buying customer" in desc
