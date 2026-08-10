"""The WhatsApp invitation is an offer, not a redirect.

Neema was pushing "let's continue on WhatsApp" at customers who were already
buying — on Messenger, in public comments, and even on our own storefront. The
cause was a contradiction: the Messenger addendum said "close the sale right
here", but the `whatsapp_checkout_link` TOOL DESCRIPTION (which the model reads
every single turn) said "use this the moment they show buying intent". The tool
description won.

These tests pin the corrected behaviour: sell where the customer already is,
invite to WhatsApp at most once and in passing, and never hand a ready buyer a
wa.me link instead of closing.
"""
import app.agent.runtime as rt
from app.agent.prompt import build_system_prompt
from app.agent.tools import TOOLS
from app.routers.web_chat import _web_wa_id


def _tool(name: str) -> dict:
    return next(t for t in TOOLS if t["name"] == name)


# ── the tool description: buying intent must NOT trigger the link ────────────

def test_checkout_link_is_a_last_resort_not_a_buying_intent_trigger():
    desc = _tool("whatsapp_checkout_link")["description"]
    assert "LAST RESORT" in desc
    # The exact instruction that caused the bug must be gone.
    assert "the moment they show buying intent" not in desc
    # …and buying intent must now route to closing the sale instead.
    assert "CLOSE THE SALE HERE" in desc
    assert "decline" in desc.lower()          # the real trigger: they won't share a number


# ── the governing rule lives in the base prompt (every channel) ──────────────

def test_prompt_carries_the_invitation_rule():
    p = build_system_prompt(currency="KES")
    assert "THE WHATSAPP INVITATION" in p
    assert "SELL WHERE THEY ALREADY ARE" in p
    assert "AT MOST ONCE" in p
    # The invitation must never replace the selling.
    assert "never a redirect" in p
    assert "addition" in p.lower()


# ── the website: a visitor in the shop is never sent to another app ──────────

def test_web_session_is_detected():
    key = _web_wa_id("sess-abc")
    assert key.startswith(rt.WEB_KEY_PREFIX)
    # a real phone must never be mistaken for a web session
    assert not "254712345678".startswith(rt.WEB_KEY_PREFIX)


def test_web_addendum_sells_on_site():
    a = rt._web_addendum()
    assert "WEBSITE" in a
    assert "Do NOT send them to WhatsApp to buy" in a
    # asking for the number is still allowed — that IS the natural invitation
    assert "capture_contact" in a
    # and if the customer asks for WhatsApp, serving them is fine
    assert "If they ASK for WhatsApp" in a


def test_web_tool_set_drops_the_wa_link():
    """The tool-set filter run_turn applies for a storefront visitor."""
    web_tools = [t["name"] for t in TOOLS if t["name"] != "whatsapp_checkout_link"]
    assert "whatsapp_checkout_link" not in web_tools
    # but she can still sell: catalogue, cart and order all remain
    for still_there in ("search_catalog", "update_cart", "create_order", "capture_contact"):
        assert still_there in web_tools


# ── public comments: one CTA, not a WhatsApp push on every reply ─────────────

def test_public_comment_gives_one_cta():
    # DM landed → the ONE public CTA is the inbox. Links are DM-only on Meta
    # (the algorithm suppresses link-carrying comments), so the storefront
    # link rides the DM and the public square stays link-free.
    out = rt._comment_public_reply(
        "That red chasuble is $150.", dm_sent=True, name_tag=" Charity", seed="X",
        product_known=True, product_name="Red Chasuble")
    assert "WhatsApp" not in out                     # no push — the DM has everything
    assert "http" not in out                         # link-free public reply
    # DM did not open → an invitation to the inbox, NOT the product page
    out2 = rt._comment_public_reply(
        "That red chasuble is $150.", dm_sent=False, name_tag=" Charity", seed="X",
        product_known=True, product_name="Red Chasuble")
    assert "red-chasuble" not in out2 and "http" not in out2
    # a buyer we could NOT identify a product for is still never stranded
    fallback = rt._comment_public_reply("It is $150.", dm_sent=False,
                                        name_tag="", seed="X")
    assert "http" not in fallback
    assert any(fallback.endswith(line) for line in rt._COMMENT_INVITE_POOL)


# ── Messenger/Instagram: close here, invite once ─────────────────────────────

def test_meta_addendum_closes_here_and_invites_once():
    a = rt._meta_addendum("KES")
    assert "CLOSE THE SALE RIGHT HERE" in a
    assert "Do NOT push them to WhatsApp" in a
    # the number request is explicitly framed as the ONE natural invitation
    assert "one natural WhatsApp invitation" in a
    assert "Never repeat the invitation" in a
