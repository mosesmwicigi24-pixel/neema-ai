"""THE LANGUAGE GUARD IS HARD (owner's decision, 2026-11-07): a plainly
English draft to a customer the floor placed in Hindi, Swahili, French or
Portuguese is corrected by the rewrite; still wrong, the hold line goes out
in THEIR language and a colleague is flagged. Bilingual replies, the hub's
product names and English customers are never flagged."""
from __future__ import annotations

import pytest

import app.main  # noqa: F401


def _findings(comment, answer):
    from app.agent import review as rv
    return [f for f in rv.rule_findings(comment, answer, [], tool_results=[], mode="dm") if f["kind"] == "language"]


@pytest.mark.parametrize("comment,answer,lang", [
    ("Habari, kasoki ni bei gani? Nataka nyeusi.", "Hello! The Cassock is KES 4,500 and it is made to order. Which colour would you like?", "Swahili"),
    ("Bonjour, combien coûte la chasuble ?", "Hello, the Chasuble is USD 120 and we ship it to you by DHL.", "French"),
    ("Olá, quanto custa a estola?", "Hello, the Stole is USD 35 and we ship worldwide by DHL.", "Portuguese"),
    ("नमस्ते, कसॉक की कीमत क्या है?", "Hello, the Cassock is USD 45 and we ship it to India by DHL.", "Hindi"),
])
def test_a_plainly_english_draft_to_a_placed_customer_is_a_hard_finding(comment, answer, lang):
    f = _findings(comment, answer)
    assert len(f) == 1 and f[0]["hard"] is True and lang in f[0]["text"]
    assert "product names may stay" in f[0]["text"]


@pytest.mark.parametrize("comment,answer", [
    # bilingual: the customer's language with the hub's English product names
    ("Habari, kasoki ni bei gani?", "Habari! Cassock ni KES 4,500, inashonwa kwa kipimo chako. Ungependa rangi gani?"),
    ("Bonjour, combien coûte la chasuble ?", "Bonjour ! La Chasuble est à USD 120, livrée chez vous par DHL."),
    # an English customer is never flagged, whatever the reply
    ("How much is a cassock?", "The Cassock is KES 4,500. Which colour would you like?"),
    # a short Swahili price line with no listed Swahili word is not English
    ("Trei ni bei gani?", "Trei tatu za aluminium ni KES 66,000."),
])
def test_bilingual_replies_product_names_and_english_customers_are_not_flagged(comment, answer):
    assert _findings(comment, answer) == []


def test_the_hold_line_is_in_the_customers_language():
    from app.agent import runtime as rt
    assert rt._hold_dm_for("Habari, kasoki ni bei gani?", swahili=True, money=False) == rt._SW_REVIEW_HOLD_DM
    assert rt._hold_dm_for("Bonjour, combien coûte la chasuble ?", swahili=False, money=True).startswith("Laissez-moi vérifier l'article")
    assert rt._hold_dm_for("Olá, quanto custa a estola?", swahili=False, money=False).startswith("Deixe-me confirmar")
    assert "टीम" in rt._hold_dm_for("नमस्ते, कसॉक की कीमत क्या है?", swahili=False, money=False)
    assert rt._hold_dm_for("How much is a cassock?", swahili=False, money=True) == rt._REVIEW_HOLD_DM_PRICE
    assert rt._hold_dm_for("你好，多少钱？", swahili=False, money=False) == rt._REVIEW_HOLD_DM


def test_the_gate_uses_the_language_aware_hold_line():
    import inspect
    from app.agent import runtime as rt
    src = inspect.getsource(rt._gate_turn_reply)
    assert "_hold_dm_for(user_text, swahili=swahili, money=money)" in src
    assert "_SW_REVIEW_HOLD_DM if swahili else _REVIEW_HOLD_DM" not in src


def test_chinese_and_arabic_are_answered_in_their_language_not_handed_over():
    from app.jobs import eval_cases
    cases = {c["id"]: c for c in eval_cases.load("independent_safety.jsonl", include_blind=True)}
    for cid in ("safe-094", "safe-095"):
        e = cases[cid]["turns"][0]["expect"]
        assert e["next"] == "answer" and e["tool"] == "!handoff_to_human" and e["figures"] == "hub-only"
        assert "human-takeover" not in cases[cid]["categories"]
