"""The official voice (owner, 2026-09-15, from the green-cassock thread):

  "The chat is a bit off the official language. Let's not respond in Swahili
  unless someone speaks in Swahili. We should always confirm the name of the
  product and compare it to the hub products, and the price should be
  confirmed from the hub as well — the hub is the source of truth. The
  questions that follow should help to close the sale, not continue the
  conversation aimlessly: 'The Round Collar Shirt for Bishops is ZMW 900.
  Kindly make your order, let us know how many you need and the colour too.
  How soon do you want the shirt?' Also make your language human, not AI or
  bot or auto-generic."

What went out: "Tunakaa Nairobi…" under a thread, "Very well. The Round Collar
Shirt for bishops is ZMW 900. Which colour would you like?", "The Cope —
Complete Set in purple … is **$450 USD**" to "the dress you are wearing", and
"the colour of Pentecost fire, perfect for apostles".

Repo fake style (no DB fixture). Requires Python 3.11 (SQLAlchemy models).
"""
import asyncio
import inspect
import re

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime as rt
from app.agent import voice
from app.agent.prompt import build_system_prompt
from app.services import meta_send


def _prompt(**kw) -> str:
    return " ".join(build_system_prompt(**kw).split())


def _addendum(ccy="USD") -> str:
    return " ".join(rt._public_comment_addendum(ccy).split())


# ── 1. English is the selling language; Swahili only when THEY wrote it ──────

def test_the_prompt_makes_english_the_default_and_swahili_theirs_to_start():
    for p in (_prompt(country_iso="KE", currency="KES"), _prompt(currency="USD")):
        assert "THE LANGUAGE (owner rule, 2026-09-15)" in p
        assert "English is our official selling language and the default" in p
        assert "Reply in Swahili ONLY when the customer wrote their message in Swahili" in p
        assert "Never switch to Swahili on your own" in p
        assert '"Welcome" and "Thank you", not "Karibu" and "Asante"' in p
        assert "MIRROR THEM" not in p


def test_no_rule_text_sprinkles_swahili_into_its_own_examples():
    """The model imitates the prompt's examples more readily than its rules,
    so "Asante, Pastor — noted" as an example taught the very sprinkle the
    owner banned. The rule that names the two words is the one place they
    may still appear."""
    renderings = [_prompt(country_iso="KE", currency="KES"), _prompt(currency="USD"),
                  _addendum("USD"), " ".join(rt._meta_addendum("USD").split()),
                  " ".join(rt._tiktok_addendum("USD").split())]
    for text in renderings:
        low = (text.replace('"Welcome" and "Thank you", not "Karibu" and "Asante"', "")
                   .replace("'Welcome' and 'Thank you', not 'Karibu' and 'Asante'", "")
                   .lower())
        # the KISWAHILI SANIFU rule speaks Swahili on purpose — it governs a
        # reply that is ALREADY Swahili, never an English one
        low = re.sub(r"kiswahili sanifu \(owner rule.*?(?=- what a colleague said stands|$)", "", low)
        assert "karibu" not in low and "asante" not in low


def test_comment_rules_mirror_the_comment_itself_never_the_page():
    a = _addendum("KES")
    assert "THE LANGUAGE (owner rule, 2026-09-15)" in a
    assert "SAME language THIS comment is written in" in a
    assert "Never answer a French or Swahili comment in English" in a     # still mirrored
    assert "never answer an English comment in Swahili" in a
    assert "not for a Kenyan name" in a and "not for the post's language" in a
    assert "English, Sheng, a mix, or a language you cannot place → English" in a
    assert "No Swahili sprinkles in an English reply" in a


def test_no_canned_line_speaks_swahili():
    pools = (rt._LIVE_WHICH_POOL + rt._LIVE_WELCOME_POOL + rt._THANKS_POOL
             + rt._OVER_CAP_POOL + rt._OVER_CAP_SELL_POOL + rt._FIRST_SELL_POOL
             + rt._OVER_CAP_SELL_EACH_POOL + rt._NEUTRAL_ACK_POOL + rt._GOODWILL_POOL
             + [rt._PUBLIC_EMPATHY])
    for line in pools:
        low = line.lower()
        for sw in ("karibu", "asante", "sana", "habari", "pole"):
            assert not re.search(rf"\b{sw}\b", low), line


# ── 2. the hub names it, the hub prices it ───────────────────────────────────

def test_the_prompt_confirms_name_and_price_against_the_hub():
    p = _prompt(currency="USD")
    assert "THE HUB NAMES IT, THE HUB PRICES IT" in p
    assert "the hub is the source of truth" in p
    assert '"The Round Collar Shirt is ZMW 900"' in p
    assert 'never a name you composed ("the Round Collar Shirt for bishops")' in p
    assert "never a price from memory" in p
    assert "No hub row, no quote" in p


def test_comment_rules_confirm_the_row_and_read_the_one_youre_wearing():
    a = _addendum("USD")
    assert "THE HUB NAMES IT, THE HUB PRICES IT" in a
    assert "called by the hub's own name and priced by the hub's own figure" in a
    assert "SAY WHAT THEY SEE" in a                                        # kept, after the name
    assert "never the bare catalogue label ('Ornate Chasuble — Embroidered')" in a
    assert "never a description in place of the hub's name" in a
    assert "(4) CONFIRM against the hub before you quote" in a
    assert "means the garment on the PERSON in the frame, not the post's headline item" in a
    assert "do not guess a dearer or unrelated item" in a
    assert "Tell me which and I'll give you the price and take your order." in a


# ── 3. every question takes the order ────────────────────────────────────────

def test_the_prompt_closes_instead_of_chatting():
    p = _prompt(currency="USD")
    assert "CLOSE, DON'T CHAT (owner rule, 2026-09-15)" in p
    assert "Every question you ask must move the order" in p
    assert '"which colour would you prefer?" on its own' in p
    assert "Kindly place your order — let us know the colour and how many you need. How soon do you want the shirt?" in p
    # one piece stays the default, and "how many" is part of the order, not a gate
    assert "ONE PIECE IS THE DEFAULT" in p
    assert 'Never make "how many?" the gate before a price' in p
    assert 'One is a fine answer to "how many"' in p
    assert '"Shall I reserve it for you?" is a sale' not in p


def test_comment_rules_end_with_the_order():
    a = _addendum("KES")
    assert "END WITH THE PULL — and the pull is the ORDER" in a
    assert "Kindly place your order — let us know the colour and how many you need. How soon do you want the shirt?" in a
    assert "Every question must move the order" in a
    assert "a comment that answers AND asks is what starts the sale" in a
    assert "No benefit blurb, no boilerplate" in a


def test_the_messenger_walk_takes_how_many_and_how_soon_after_the_size():
    for a in (rt._meta_addendum("USD"), rt._tiktok_addendum("KES")):
        flat = " ".join(a.split())
        assert "size → how many they need (ONE PIECE IS THE DEFAULT; one is a fine answer) → how soon they want it → their city" in flat


def test_the_which_item_pool_offers_to_take_the_order():
    assert any("take your order" in line for line in rt._LIVE_WHICH_POOL)


# ── 4. human, not bot: the rule, and the seam that enforces it ───────────────

def test_the_prompt_bans_the_butler_and_the_boilerplate():
    p = _prompt(currency="USD")
    assert "SOUND LIKE A PERSON, NOT A BOT (owner rule, 2026-09-15)" in p
    assert 'never with a butler\'s "Very well", "Certainly" or "Absolutely"' in p
    assert '"the colour of Pentecost fire, perfect for apostles and church leaders"' in p
    assert '"made to fit you perfectly, lasts for years"' in p
    assert 'Say "$170", never "$170 USD"' in p
    assert "If a sentence could have been written for anyone, it is not yours" in p
    # the old acknowledgement list recommended the very word the owner flagged
    assert '("Very well", "A fine choice"' not in p


@pytest.mark.parametrize("raw, clean", [
    ("The Cope — Complete Set in purple is **$450 USD**. Which colour?",
     "The Cope — Complete Set in purple is $450. Which colour?"),
    ("Very well. The Round Collar Shirt is ZMW 900. Which colour would you like?",
     "The Round Collar Shirt is ZMW 900. Which colour would you like?"),
    ("Certainly! The Cassock is KES 12,000 Kenyan Shillings.", "The Cassock is KES 12,000."),
    ("Thank you Gregory 🙏 The Red Apostolic Cassock is USD $170.",
     "Thank you Gregory 🙏 The Red Apostolic Cassock is $170."),
    ("*The Cassock* is `KES 12,000` — __made to order__", "The Cassock is KES 12,000 — made to order"),
    ("Sure thing — it's $40 each.", "It's $40 each."),
    ("Of course, Mary 🙏 Which piece do you mean?", "Of course, Mary 🙏 Which piece do you mean?"),
    ("", ""),
])
def test_plain_public_voice_strips_markdown_money_words_and_butler_openers(raw, clean):
    assert voice.plain_public_voice(raw) == clean
    assert voice.plain_public_voice(clean) == clean          # idempotent


def test_a_bare_butler_word_is_left_alone_rather_than_emptied():
    assert voice.plain_public_voice("Very well.") == "Very well."


def test_the_public_seams_go_through_the_plain_voice():
    src = inspect.getsource(rt._run_comment_engage)
    assert "await reply_to_comment(cid, plain_public_voice(text)," in src   # every public reply
    assert "public_text = plain_public_voice(public_text)" in src           # the saved copy too
    assert "_dm_text(plain_public_voice(answer), product_link, ext, swahili=swahili)" in src  # and the DM


def test_messenger_and_instagram_sends_lose_their_asterisks(monkeypatch):
    sent = []

    async def fake_send(recipient, text, page_id=None, human_agent=False, tag=None):
        sent.append(text)
    monkeypatch.setattr(meta_send, "send_meta_message", fake_send)
    asyncio.run(meta_send.send_to_channel("messenger", "psid1", "It is **$450**, __made to order__.",
                                          page_id="pg"))
    assert sent == ["It is $450, made to order."]


def test_whatsapp_keeps_its_single_bold(monkeypatch):
    sent = []
    from app.services import n8n_bridge

    async def fake_waba(to, text, context_wamid=None):
        sent.append(text)
        return "wamid.1"
    monkeypatch.setattr(n8n_bridge, "_send_waba", fake_waba)
    asyncio.run(meta_send.send_to_channel("whatsapp", "+254700", "*Cassock* — KES 12,000"))
    assert sent == ["*Cassock* — KES 12,000"]
