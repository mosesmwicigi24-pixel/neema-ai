"""Kiswahili sanifu (owner, 2026-09-15): "In Swahili, use the above rules — no
non-official language, no comments that are not official. Ensure the language
is good."

What had gone out: "tunaship duniani kote", "Unaweza order moja kwa moja",
"tunakuhitaji vipimo vyako", "kwa kiwango chako", "cup 40", "Kwa divai (mkate
wa Bwana)", "Devai (divai ya kienyeji)", "KES 1,000 au 1,500", "Upo wapi?".

Swahili is spoken only when THEY wrote Swahili (THE LANGUAGE rule); when it is,
it is standard, official, and under every rule of the official voice.

Repo fake style (no DB fixture). Requires Python 3.11 (SQLAlchemy models).
"""
import inspect
import re

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime as rt
from app.agent import voice
from app.agent.prompt import build_system_prompt
from app.services import meta_send


# ── 1. Swahili is recognised from THEIR words alone ──────────────────────────

@pytest.mark.parametrize("text", [
    "Bei gani?", "Bei?", "Ni ngapi?", "Pesa ngapi hii?", "Nataka hii", "Divai na mkate",
    "Vifaa vya meza ya Bwana", "Habari, mnauza stole?", "Asante sana", "Nahitaji kasoki nyeusi",
    "Tafadhali nitumie bei", "Je, mnayo msalaba wa kifuani?",
])
def test_their_swahili_is_recognised(text):
    assert voice.looks_swahili(text)


@pytest.mark.parametrize("text", [
    "How much?", "I need one", "Karibu Zambia", "Amen", "Nice", "Bonjour", "",
    "Where should I place the order?", "The dress you are wearing is how much",
    "I want this one please", "AMAZING!",
])
def test_english_and_a_lone_swahili_word_are_not_swahili(text):
    assert not voice.looks_swahili(text)


# ── 2. the Swahili canned lines: official, hub-named, closing on the order ───

_SW_SELL = rt._SW_OVER_CAP_SELL_POOL + rt._SW_FIRST_SELL_POOL + rt._SW_OVER_CAP_SELL_EACH_POOL
_SW_ALL = (_SW_SELL + rt._SW_LIVE_WHICH_POOL + rt._SW_LIVE_WELCOME_POOL + rt._SW_THANKS_POOL
           + rt._SW_OVER_CAP_POOL + rt._SW_NEUTRAL_ACK_POOL + rt._SW_GOODWILL_POOL
           + rt._SW_DM_CONTINUE_POOL + [rt._SW_PUBLIC_EMPATHY])


def test_swahili_sell_lines_take_the_order_after_the_price_with_one_question():
    for line in _SW_SELL:
        low = line.lower()
        assert "{product}" in line and "{price}" in line, line
        assert low.index("{price}") < low.index("weka oda yako"), line      # price first, then the order
        assert line.count("?") == 1, line
        assert "dhl" in low or "tayari" in low, line


def test_swahili_lines_are_official_swahili_not_swanglish_or_sheng():
    swanglish = re.compile(r"\b(?:order|ship|shipping|deliver|delivery|confirm|book|cup|cups|pcs|"
                           r"kindly|please|thank|welcome|poa|niaje|msee|fiti|sawa sawa)\b", re.I)
    for line in _SW_ALL:
        assert not swanglish.search(line.replace("DHL", "").replace("Bethany House", "")), line
        assert "**" not in line and "http" not in line and "au " not in line.lower(), line


def test_swahili_lines_keep_the_hubs_name_bare():
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Daniel", seed="d",
                                   product_known=True, product_name="Round Collar Shirt",
                                   price_text="KES 4,500", swahili=True)
    assert "Round Collar Shirt ni KES 4,500" in out            # the hub's name, exactly, then its price
    assert "the Round Collar Shirt" not in out
    assert "weka oda yako" in out and out.count("?") == 1


def test_a_first_swahili_comment_gets_the_swahili_welcome():
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Samuel", seed="s",
                                   product_known=True, product_name="Cassock",
                                   price_text="KES 12,000", first_contact=True, swahili=True)
    assert out.startswith("Karibu Bethany House Samuel")
    assert "Cassock ni KES 12,000" in out and "Unaihitaji lini?" in out or "kuipata lini?" in out


def test_per_piece_goods_are_sold_by_the_count_in_swahili():
    out = rt._comment_public_reply("", dm_sent=False, name_tag="", seed="p",
                                   product_known=True, product_name="Plastic Communion Cups",
                                   price_text="KES 10", per_piece=True, swahili=True)
    assert "KES 10 kila kimoja" in out and "ngapi" in out


def test_goodwill_neutral_and_empathy_have_swahili_forms():
    assert rt._comment_public_reply("", dm_sent=False, name_tag=" Sydney", seed="g",
                                    goodwill=True, swahili=True) in [
        p.replace("{name}", " Sydney") for p in rt._SW_GOODWILL_POOL]
    assert rt._comment_public_reply("", dm_sent=False, name_tag="", seed="n", swahili=True) in [
        p.replace("{name}", "") for p in rt._SW_NEUTRAL_ACK_POOL]
    assert "kwa uzito" in rt._SW_PUBLIC_EMPATHY


def test_english_stays_english_when_the_flag_is_off():
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Daniel", seed="d",
                                   product_known=True, product_name="Round Collar Shirt",
                                   price_text="ZMW 900")
    assert "the Round Collar Shirt is ZMW 900" in out and "oda" not in out.lower()


def test_the_swahili_dm_orders_in_swahili():
    dm = rt._dm_text("Round Collar Shirt ni KES 4,500.", "https://bethanyhouse.co.ke/product/x", "s",
                     swahili=True)
    assert "Agiza hapa 👉 https://bethanyhouse.co.ke/product/x" in dm
    assert any(dm.endswith(line) for line in rt._SW_DM_CONTINUE_POOL)
    en = rt._dm_text("It is $45.", "https://bethanyhouse.co.ke/product/x", "s")
    assert "Order here 👉" in en and any(en.endswith(line) for line in rt._DM_CONTINUE_POOL)


def test_the_engine_detects_once_and_uses_it_everywhere():
    src = inspect.getsource(rt._run_comment_engage)
    assert "swahili = looks_swahili(comment_text)" in src
    assert "_SW_LIVE_WELCOME_POOL if swahili else _LIVE_WELCOME_POOL" in src
    assert "_SW_LIVE_WHICH_POOL if swahili else _LIVE_WHICH_POOL" in src
    assert "_SW_THANKS_POOL if swahili else _THANKS_POOL" in src
    assert "_SW_PUBLIC_EMPATHY if swahili else _PUBLIC_EMPATHY" in src
    assert "swahili=swahili)" in src                                 # the public composer
    assert "_dm_text(plain_public_voice(answer), product_link, ext, swahili=swahili)" in src


# ── 3. the rules, in the prompt and under a comment ──────────────────────────

def test_the_prompt_teaches_official_swahili():
    p = " ".join(build_system_prompt(country_iso="KE", currency="KES").split())
    assert "KISWAHILI SANIFU (owner rule, 2026-09-15)" in p
    for phrase in ('never "tunaship"', '"unaweza order"', '"tunasafirisha"', '"unaweza kuagiza"',
                   '"vikombe 40", never "cup 40"', 'never "KES 1,000 au 1,500"',
                   '"Silver Communion Tray ni KES 18,000"', '"Devai (divai ya kienyeji)" was invented',
                   '"tunahitaji vipimo vyako"', '"Nikusaidie vipi leo?"',
                   'No butler openers ("Vema", "Hakika", "Bila shaka")',
                   '"Tunasafirisha kote duniani kwa DHL."',
                   '"Tafadhali weka oda yako — tuambie rangi na idadi unayohitaji. Unaihitaji lini?"',
                   'Never "Upo wapi?"', "msalaba wa kifuani (pectoral cross)"):
        assert phrase in p, phrase
    # Swahili is still theirs to start — the language rule stands above it
    assert "Reply in Swahili ONLY when the customer wrote their message in Swahili" in p


def test_comment_rules_carry_the_same_swahili_standard():
    a = " ".join(rt._public_comment_addendum("KES").split())
    assert "KISWAHILI SANIFU (owner rule, 2026-09-15)" in a
    assert "ONE price per item (never 'KES 1,000 au 1,500')" in a
    assert "'tunaship', 'unaweza order' → 'tunasafirisha', 'unaweza kuagiza'" in a
    assert "'vikombe 40' never 'cup 40'" in a
    assert "Tafadhali weka oda yako — tuambie rangi na idadi unayohitaji. Unaihitaji lini?" in a
    assert "Never 'Upo wapi?' to place them" in a


# ── 4. the seams: Swahili butler words and the Swahili country hedge ─────────

@pytest.mark.parametrize("raw, clean", [
    ("Vema. Round Collar Shirt ni KES 4,500.", "Round Collar Shirt ni KES 4,500."),
    ("Hakika, Cassock ni KES 12,000 shilingi.", "Cassock ni KES 12,000."),
    ("Bila shaka! Tunasafirisha kote duniani kwa DHL.", "Tunasafirisha kote duniani kwa DHL."),
    ("Karibu Bethany House, Samuel 🙏 Cassock ni KES 12,000.", "Karibu Bethany House, Samuel 🙏 Cassock ni KES 12,000."),
])
def test_the_plain_voice_drops_the_swahili_butler_too(raw, clean):
    assert voice.plain_public_voice(raw) == clean


def test_the_swahili_country_hedge_is_stripped_at_the_send_boundary():
    safe, removed = meta_send.sanitize_public_comment(
        "Tuko Nairobi, Kenya. Tunasafirisha kote duniani kwa DHL. Upo wapi?")
    assert "Upo wapi" not in safe and removed
    assert safe.startswith("Tuko Nairobi, Kenya.") and "DHL" in safe
    safe2, removed2 = meta_send.sanitize_public_comment("Cassock ni KES 12,000. Uko nchi gani?")
    assert "nchi gani" not in safe2 and removed2
