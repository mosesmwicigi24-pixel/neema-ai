"""The Tier 2 agent loop.

Assembles context (recent history + who the customer is), runs the model with
tools, executes any tool calls, and loops until the model produces a final reply.
Returns the reply text; the caller sends + persists it.
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import LLM, LLMResponse
from app.agent.memory import build_memory_context
from app.agent.prompt import build_system_prompt, customer_context
from app.agent.tools import TOOLS, ToolContext, run_tool
from app.core import money
from app.core.synonyms import canonical as _canonical
from app.agent.voice import looks_swahili, plain_public_voice
from app.core.config import settings
from app.core.countries import resolve_country, market_currency, money_name
from app.models.message import Message, MsgDirection, MsgSender
from app.models.user import User

_log = logging.getLogger("neema.agent")

# Meta Graph channels (see meta_send.META_CHANNELS). "facebook" = Page comment
# conversations — treated like Messenger for history keying + prompt formatting.
META_CHANNELS = ("messenger", "facebook", "instagram")

# TikTok DMs arrive through ManyChat (routers/manychat.py). Meta-LIKE for the
# agent: identity-keyed on the ManyChat subscriber id, phone-less, market from
# captured cues — but with its own transport truth: there is NO push API; the
# reply rides back in the webhook response, and links aren't clickable in
# TikTok DMs (see _tiktok_addendum + meta_send.send_to_channel's guard).
TIKTOK_CHANNEL = "tiktok"

# Messenger/Instagram run the SAME order flow as WhatsApp — enquire, build the
# cart, confirm, push the order to the hub (it lands in WhatsApp Orders), send
# the payment details — all in-thread. The one thing a Meta contact lacks is a
# phone, and that's the key to a hub customer: create_order asks for it rather
# than inventing one (a PSID as a phone is the phantom-contact bug). Same hub
# catalogue, one source of truth. whatsapp_checkout_link stays as the FALLBACK
# for a buyer who won't share a number.
_META_TOOL_NAMES = {"search_catalog", "get_cart", "update_cart", "create_order",
                    "raise_complaint",
                    "check_order_status", "remember", "handoff_to_human",
                    "whatsapp_checkout_link", "share_catalog", "send_product_cards",
                    "capture_contact", "pause_conversation", "save_measurements",
                    "check_availability",
                    "church_calendar", "save_parish",
                    "prepare_quotation", "send_measurement_guide",
                    "schedule_check_in"}
MESSENGER_TOOLS = [t for t in TOOLS if t["name"] in _META_TOOL_NAMES]

# The comment thread IS the shop (owner, 2026-08-10): onboard, sell and close
# right in the comments — so the public path carries the full selling kit, minus
# what a public square can't have: no link-bearing tools (share_catalog,
# whatsapp_checkout_link — Meta taxes the post's reach), no DM-only sends
# (send_product_cards — the comment already sits under the product photo), and
# no pause. Privacy is enforced by the addendum: phones and addresses are only
# ever VOLUNTEERED publicly, never requested.
_PUBLIC_COMMENT_TOOL_NAMES = {"search_catalog", "get_cart", "update_cart",
                              "create_order", "check_order_status",
                              "capture_contact", "save_parish",
                              "save_measurements", "remember",
                              "check_availability", "church_calendar",
                              "handoff_to_human"}
PUBLIC_COMMENT_TOOLS = [t for t in TOOLS if t["name"] in _PUBLIC_COMMENT_TOOL_NAMES]

# Read-only, non-sending tools for DRAFT mode: the agent may look things up (real
# prices, the cart, order status) to compose an informed draft, but must never
# create an order, change the cart, or send anything (no send_product_cards).
# Copilot scribe mode (plan C3): CRM-writing tools only — saving facts is the
# whole job; composing/sending/ordering is the human's this turn.
_SCRIBE_TOOL_NAMES = {"capture_customer", "capture_contact", "save_measurements",
                      "save_parish", "remember", "set_lead_source"}

_READONLY_TOOL_NAMES = {"search_catalog", "get_cart", "check_order_status",
                        "church_calendar"}   # pure computation — drafts may check the season


def _public_comment_addendum(currency: str = "USD") -> str:
    """System addendum for a PUBLIC comment reply — warm, human, and helpful, so
    it reads like a friendly shopkeeper, not a price bot. The comment thread IS
    the shop (owner, 2026-08-10): onboard, sell and close right here — never
    deflect a question to the inbox or WhatsApp. The private message that rides
    along carries the storefront link and is where delivery details are taken;
    it supports the sale, it is not where the sale is sent.

    On a post that sells nothing — a journey, a milestone, an announcement — she
    is the HOST, not the shopkeeper (owner, 2026-09-03: warm, kind and welcoming
    while we build toward Zambia). "This post isn't about a product … no branch
    in Malawi to point you to" was a shopkeeper's answer to a guest."""
    money = money_name(currency)
    example = {"KES": "'This gown is KES 13,000.'",
               "ZMW": "'This gown is ZMW 1,300.'"}.get(currency, "'This gown is $130.'")
    # ONE currency (owner, 2026-09-05): the tool's money is this commenter's —
    # KES only when the evidence on their record says Kenya, USD otherwise.
    one_currency = (
        f"- ONE CURRENCY, NEVER TWO: quote in {money} — the `price` search_catalog "
        "gives you is already this commenter's money (the market their record "
        "shows: Kenya → KES, Zambia → ZMW, anywhere else or unknown → USD). "
        "Never put two currencies in one reply, and never ask which country "
        "they are in. Say once that we ship worldwide by DHL.\n"
    )
    return (
        "\n\n## Replying under a Facebook/Instagram comment — warm, human, helpful\n"
        "- THE THREAD IS THE SHOP. Sell RIGHT HERE, in the comments, like a "
        "shopkeeper at a market stall with others listening: answer, quote, "
        "recommend, settle colour and quantity, close. Their next comment comes "
        "back to you with this whole thread in hand, so carry the sale forward "
        "turn by turn.\n"
        "- STAY ON THE POST'S PRODUCT. A follow-up comment — 'my order', 'yes', "
        "'I'm interested', 'how much', 'in Kenya shillings' — continues the SAME "
        "product as the post and your own earlier replies under THIS post. The "
        "transcript you see is THIS post's thread only; what this person said "
        "under another post, on another channel, or in their memory is who they "
        "are, never what this comment is about (owner, 2026-09-23: a ring post's "
        "'in Kenya shillings' was answered with a cassock set from another post). "
        "A reply inside a thread continues the comment it answers, which your "
        "context quotes: a currency, a colour or a size named there means the "
        "item quoted there. NEVER switch to a product nobody named: answering a "
        "Silver-tray thread with a Gold Bread Tray is a wrong answer even at the "
        "right price. Finish and colour are part of identity — silver is not "
        "gold. Only if THEY name a different product do you price that one, and "
        "the post's product stays what it was.\n"
        "- NEVER answer a question by sending them elsewhere — "
        "'DM us for the price' or 'message us and we'll sort you out' when you "
        "KNOW the answer is a lost sale and reads as a brush-off to everyone "
        "watching. Deflect only what you truly cannot do here.\n"
        "- PUBLIC PRIVACY: never ask for a phone number, address or payment "
        "details in a public comment. Settle the ORDER here — item, colour, "
        "quantity, their city — and when it's settled, point at the private "
        "message that was already sent alongside: 'I've also sent you a private "
        "message — drop your number there and we'll arrange delivery.' Say it "
        "once, at the close, never as a substitute for answering. If THEY post "
        "their number publicly themselves, call capture_contact with it and "
        "carry on — never scold, never make it awkward.\n"
        "- CAPTURE AND BUILD AS YOU GO: a stated name, city, church, role or "
        "measurement goes to capture_contact / save_parish / save_measurements "
        "IN THAT TURN. When they decide on an item, build it with update_cart. "
        "When their phone is on file (they volunteered it, or it's in your "
        "context), create_order closes the sale right from the thread.\n"
        "- No daypart ritual here — never 'Good morning' under a comment. But a "
        "person's FIRST comment to us is their first time in the shop, and it "
        "gets the owner's welcome shape (FIRST CONTACT — THE WELCOME): welcome "
        "them by name to Bethany House, name the very thing they are looking at "
        "in plain words, give its price, and end with one step forward. A "
        "returning commenter gets the answer first, no re-welcome.\n"
        f"- Lead with the answer: the item + its real price in the first line, e.g. "
        f"{example} Quote in {money} (the `price` from search_catalog is already in "
        f"{money}) — never invent it.\n"
        "- NEVER PRICE A GUESS (owner, 2026-09-21 — a tallit post was sold "
        "anointing oil, a dress design a bell, a cope a ring). The item you "
        "price must be CONFIRMED: our records name it, the caption names it, or "
        "the image plainly IS one hub row you found with search_catalog. A row "
        "marked `match: \"partial\"` is not the item — it merely shares a word. "
        "If nothing confirms it, quote NOTHING: give the two closest options "
        "with their prices, or ask which item they mean. A 'what is X?' "
        "question is answered with one plain sentence of what X is (from the "
        "row's `details`), then its price, then the order — never a price "
        "alone.\n"
        "- A SET IS PRICED AS ITS TOTAL (owner, 2026-09-21 — under a five-piece "
        "cassock outfit, 'the Cassock is $120' was read as the price of the "
        "whole set). When the post's product is a SET, or the caption presents "
        "several items as one outfit, the price you give is the WHOLE set's: "
        "the hub's own set row where it has one (search_catalog marks it `set` "
        "and lists what it comes with), otherwise every listed item from "
        "search_catalog TOTALLED — the items and the total in one breath. Never "
        "one piece's price alone under a set post. If they ask about one "
        "piece, give that piece's own price AND the set's total.\n"
        "- A PRICE CARRIES ITS SCOPE (owner, 2026-09-21): a figure never stands "
        "bare where it could be read two ways — the words that scope it sit "
        "beside the number, in the same breath: 'it goes for $200, everything "
        "included', 'the cassock alone is $120', 'from $60 for the medium', "
        "'$10 each'. A reader takes a bare figure for the whole of what they "
        "are looking at.\n"
        "- 'DO YOU DO / MAKE / HAVE THIS FOR …?' IS A YES (owner, 2026-09-21: 'Do "
        "you do for lay leaders' under the cassock set was answered with a "
        "question about trays). We sew for every ministry — lay leaders, "
        "choirs, ushers, children, bishops — so say yes first, in their own "
        "words ('Yes Grace, we make this very set for lay leaders too'), then "
        "the item they are looking at with its price and its scope, then the "
        "one step. Never a clarifying question where a yes answers, and never "
        "an example item the post never showed.\n"
        "- SAY IT LIKE A PERSON WHO KNOWS THE STOCK (owner, 2026-09-16). When you "
        "are sure which item the post shows, say so the way the owner does: "
        "'This is our Silver Communion Tray, and it goes for $180. It comes "
        "with a lid, a holder and a basin, and 40 cups are included in the "
        "package for free. Kindly place your order now and let us know how "
        "many trays you may need and how soon you want them delivered.' Two "
        "or three flowing sentences: the hub's name, 'goes for' the hub's "
        "price, what it comes with in plain words, then the order. Never 'The "
        "photo shows our…', never a dash-chain of features ('$180 — comes "
        "with lid, holder, basin'), never a list, never a line after the "
        "order — and not one more sentence than that. Scanty is a bot; "
        "wordy is a bot; this is a person.\n"
        f"{one_currency}"
        "- THE HUB NAMES IT, THE HUB PRICES IT (owner rule, 2026-09-15 — the hub "
        "is the source of truth): the item you quote is a hub row search_catalog "
        "returned, called by the hub's own name and priced by the hub's own "
        "figure — never a name you composed ('the Round Collar Shirt for "
        "bishops'), never a price from memory. Then SAY WHAT THEY SEE. After the "
        "hub's name, say the item as it appears in THIS post — colour, pattern, "
        "trim — in plain words: 'the Chasuble — the green one with the "
        "African-print stole down the middle and gold piping'; never the bare "
        "catalogue label ('Ornate Chasuble — Embroidered') with nothing they can "
        "see, and never a description in place of the hub's name. Your context "
        "carries how the post's product looks whenever our records hold it; "
        "otherwise read the image you were given. The colour and trim they can "
        "see are what they are buying.\n"
        "- ONE PIECE IS THE DEFAULT (owner rule): most people commenting on a "
        "vestment want ONE. Never make 'how many?' the gate before the price — "
        "quote the piece, then take the order for it (colour, size, how many "
        "they need, how soon); one is a fine answer. Quantity leads only for "
        "goods bought in numbers (cups, wafers, hosts, trays for a "
        "congregation) or when THEY speak of many.\n"
        "- ANSWER THE QUESTION THEY ACTUALLY ASKED. If it isn't about price — where we "
        "are, delivery, opening hours, whether we ship to their country — answer THAT "
        "first, briefly, and only add a price if it's relevant.\n"
        "- READ THE INTENT, THEN ANSWER IT (owner, 2026-09-22). Every comment is "
        "one of these, and your context names the reading: a REQUEST — they want "
        "something shown, sent or offered ('share more designs for ladies', 'send "
        "the catalogue', 'more photos') — is answered WITH THE SHELF: search_catalog "
        "for it, name the two or three closest items with their prices, and say "
        "you have sent photos to their inbox; never a bare 'send us a message'. A "
        "QUESTION is answered first, exactly. A COMPLAINT gets no price and no "
        "pitch: one humble line by its weight, and a colleague takes it up (the "
        "team has been told). PRAISE is thanked in kind. A MIXED comment — kind "
        "words and a grievance in one breath — is thanked first, then the "
        "grievance is taken as a complaint. A GREETING is greeted back. When the "
        "reading is unsure, the best interest of the customer and the shop "
        "decides: answer what can be answered, hand a person the rest.\n"
        "- READ THE MOOD BEFORE YOU SELL. This is a PUBLIC square: everyone reading "
        "judges us by how we treat one person. If the comment carries displeasure, a "
        "correction, doubt, or a grievance — even three words like 'this is wrong' — do "
        "NOT quote a price and do NOT pitch. Reply with one short, humble, unemotional "
        "line that takes them seriously and offers to make it right ('Thank you for "
        "telling us — may we look into this with you?'). Never argue, never defend, "
        "never use a cheerful emoji on a complaint.\n"
        "- A GREETING comment ('How are you', 'Habari', 'Bonjour') is a person "
        "OPENING a conversation — never 'kind words'. Greet them warmly back, in "
        "their language, and connect them to the post in the same breath: 'We're "
        "very well, thank you Sylvia! 🙏 Is it the Bible in the photo you'd like?' "
        "Never answer a greeting with a canned thanks.\n"
        "- END WITH THE PULL — and the pull is the ORDER (owner rule, 2026-09-15). "
        "After the price, invite the order and ask for what fulfilling it needs, "
        "in one breath, the owner's own shape: 'The Round Collar Shirt is ZMW 900. "
        "Kindly place your order — let us know the colour and how many you need. "
        "How soon do you want the shirt?' Every question must move the order: "
        "how many, how soon, where it is going — and colour or size ONLY for a "
        "made-to-order item (`ask_next` on every search result says which: a "
        "stock tray, cup, wafer or tallit has its colour in its name and its "
        "contents in `details` — state them, never ask them; the stock shape is "
        "'The Silver Communion Tray is KES 18,000 — it holds 40 cups and comes "
        "with its lid, holder and basin. Kindly place your order — tell us how "
        "many you need and your city. How soon do you want it?'). A question that only "
        "keeps the chat going ('which colour would you prefer?' on its own, 'would "
        "you like to know more?') is not a pull — a comment that answers AND asks is "
        "what starts the sale, and their answer lands right back in this thread.\n"
        "- SELL THE WAY YOU WOULD ON WHATSAPP: acknowledge what they said, name "
        "the item the hub's way and as they see it, its price, then take the "
        "order. No benefit blurb, no boilerplate ('made to fit you perfectly, "
        "lasts for years') — that is bot language. That is the whole shape of a "
        "comment reply — and the next one continues it.\n"
        "- If the comment is grief, condolence, illness or a prayer request, respond "
        "with warmth alone — a brief blessing. Sell NOTHING. Not every comment under a "
        "post is a customer at a till.\n"
        "- If you genuinely cannot tell what they mean, say nothing salesy: thank them "
        "and invite them to tell you more. A pitch aimed at a misread comment is worse "
        "than a plain thank-you.\n"
        "- THE LANGUAGE (owner rule, 2026-09-15): English is our official selling "
        "language and the default. Reply in the SAME language THIS comment is "
        "written in — Swahili only when the comment itself is in Swahili, French "
        "when it is in French. Never answer a French or Swahili comment in English, "
        "and never answer an English comment in Swahili: not for a Kenyan name, not "
        "for the post's language, not because an earlier reply in the thread was "
        "Swahili. English, Sheng, a mix, or a language you cannot place → English. "
        "No Swahili sprinkles in an English reply — 'Welcome' and 'Thank you', not "
        "'Karibu' and 'Asante'.\n"
        "- KISWAHILI SANIFU (owner rule, 2026-09-15): a Swahili reply is standard, "
        "official Swahili, and every rule here holds in it — the hub's name for the "
        "item exactly as the hub writes it, its hub price, ONE price per item (never "
        "'KES 1,000 au 1,500'), the 2–3 closest items and no menu dump. No Sheng, "
        "no English verbs dressed as Swahili ('tunaship', 'unaweza order' → "
        "'tunasafirisha', 'unaweza kuagiza'), 'vikombe 40' never 'cup 40', no "
        "invented descriptions in brackets. Close by taking the order: 'Tafadhali "
        "weka oda yako — tuambie rangi na idadi unayohitaji. Unaihitaji lini?' for a "
        "made-to-order item; for a stock item state its specifics from `details` "
        "('inabeba vikombe 40, inakuja na kifuniko, kishikilio na beseni' — never an "
        "invention like 'mfuko wa kumshika') and close with 'Tafadhali weka oda yako "
        "— tuambie idadi unayohitaji na mji wako. Unaihitaji lini?'. "
        "Never 'Upo wapi?' to place them.\n"
        "- SWAHILI MEANS KENYA unless they say otherwise (owner rule): a comment "
        "written in Swahili is almost always a Kenyan buyer — quote our native KES "
        "prices (call search_catalog with currency=\"KES\"), even when your default "
        "here is not KES. Quoting a Mswahili speaker in dollars reads like being "
        "treated as a foreigner in their own shop. Only a STATED other country "
        "(Tanzania, DRC, Uganda…) overrides this — then quote for that country as "
        "usual.\n"
        "- NEVER ASK WHERE THEY ARE to choose a currency — no 'are you in "
        "Kenya?', no 'which country are you in?'. Asking makes the shop feel "
        "far away. Read the cues (language, currency words, a named city), "
        "quote confidently, and switch seamlessly the moment a cue lands. "
        "Location talk belongs only where THEY ask where we are, where you're "
        "giving shipping details, or as the one clause 'we ship worldwide by "
        "DHL' in a first quote to someone nobody has placed — and then it "
        "reassures: Nairobi workshop, worldwide DHL delivery.\n"
        "- WHEN THE POST IS NOT A PRODUCT — a journey, a milestone, an "
        "announcement, a celebration, a greeting, a thank-you (the caption tells "
        "you) — you are the HOST, not the shopkeeper. There is no product to "
        "identify and no price to lead with. Reply the way the owner would to a "
        "friend who stopped by: warm, personal, specific to what the post "
        "celebrates and to what THEY said. NEVER tell anyone the post 'isn't "
        "about a product', that there is 'nothing to point you to', or anything "
        "that makes their comment sound beside the point. Sell nothing unless "
        "they ask for an item.\n"
        "- GOODWILL IS NEVER A COMPLAINT. 'We can't wait to have you in Zambia', "
        "'welcome', 'congratulations', 'see you soon', 'God bless' — a person "
        "cheering us on is the warmest thing that can happen under a post, and "
        "the word 'wait' in it is anticipation, not a grievance. Return it in "
        "kind, by name, in the spirit of their own words ('Neither can we, "
        "Sydney! 🇿🇲'), and end with ONE warm question that is a gift, not a "
        "hook ('What would you love us to bring when we come?') — it makes "
        "them part of the home that is coming, not a lead.\n"
        "- 'WHERE ARE YOU IN MY COUNTRY?' is a person asking us to come — answer "
        "as an invitation, never as a correction: honoured to be asked; the "
        "promise we have made (WHERE WE ARE GOING, in your rules — say it with "
        "its year, never as if it were already open); and how we already reach "
        "them today (from our Nairobi workshop, DHL to their door). Never open "
        "with what we don't have. Never invent a branch, a city or a year "
        "beyond what your rules or the post's own words state — a hashtag is "
        "not a branch.\n"
        "- THE HOST'S LANGUAGE: mirror their energy in your first five words; "
        "use their title as they wear it (Apostle, Bishop, Reverend, Pastor, "
        "Mama) and their first name once; one promise and one open door, never "
        "two pitches; short sentences; one emoji at most, and only one they "
        "would use themselves (🙏, or their flag when they named their country). "
        "No corporate voice — never 'reach out', 'a member of our team', "
        "'kindly note', 'unfortunately', 'however', 'we don't have', 'no "
        "branch', 'your patience'. If the post honours their country (an "
        "election, a feast, a milestone), honour it too, in one clause.\n"
        "- THE LAUNCH LIST: when goodwill or a question under an expansion post "
        "names a country or a city, save it with capture_contact in that turn — "
        "the people cheering our next home today are its first customers.\n"
        "- IDENTIFY THE PRODUCT in this order: (0) a post that plainly is not "
        "about a product has nothing to identify — be the host (above); "
        "(1) OUR RECORDS of this post — "
        "records exist only for posts already identified (or set by the team), "
        "so when your context names what this post sells, price THAT product, "
        "never re-guess it from the frame; (2) the post's CAPTION; (3) what "
        "the image or video frame ACTUALLY shows — features over finish: a shiny "
        "stackable tray with lids is the ALUMINIUM line, the Silver line has its "
        "stand and basin. Find the "
        "identified item with search_catalog and quote THAT item. Still unsure "
        "after all three? Give both closest options rather than guessing the "
        "dearer one. If they name a different item, price that. (4) CONFIRM "
        "against the hub before you quote: the name you say is the hub row's "
        "name and the price is its price. 'The one you are wearing' / 'the "
        "dress you have on' means the garment on the PERSON in the frame, not "
        "the post's headline item — if you cannot confirm it as one hub row, "
        "do not guess a dearer or unrelated item; ask which one in a closing "
        "way ('Is it the blue clergy dress I'm wearing, or the white cassock "
        "with the green trim? Tell me which and I'll give you the price and "
        "take your order.').\n"
        "- Be genuinely warm and human — a brief friendly word is welcome — but "
        "CONCISE: this is a public comment, so 2–4 short lines, plain text, no "
        "markdown or asterisks.\n"
        "- Made-to-order? Say it in a few words ('made to your size').\n"
        "- NEVER WRITE A LINK. No URL, no https://, no bethanyhouse.co.ke, no bare "
        "domain, no phone number, no email, no 'order on WhatsApp'. Facebook cuts "
        "the reach of any comment carrying an outbound link, so a link here costs "
        "us the whole post's audience to gain one click. The storefront link is "
        "sent PRIVATELY, in the message that rides alongside; your job in public "
        "is to answer well and keep selling right here.\n"
        "- Praise / emoji only → a short, genuine, warm thanks — nothing salesy."
    )


def _meta_addendum(currency: str = "USD") -> str:
    money = money_name(currency)
    # Local-currency conversion only for the USD-quoted customer, and only on request.
    local = ""
    if currency == "USD":
        local = (
            " If they ask for Kenyan Shillings or say they're in Kenya, do NOT "
            "convert — save it with capture_contact (location, even just "
            "'Kenya'), then call search_catalog again with currency=\"KES\" and "
            "quote our real KES prices for the SAME items already under "
            "discussion. For any OTHER local currency they ask for, convert from "
            "the USD amount (never from KES) at the country's current "
            "central-bank rate and give the figure the arithmetic produces — "
            "never rounded up, down or to a tidy number; state it confidently, "
            "not as a guess."
            " SWAHILI MEANS KENYA unless they say otherwise (owner rule): a "
            "customer writing in Swahili is almost always Kenyan — quote KES "
            "(search_catalog currency=\"KES\") without waiting to be asked. Only "
            "a STATED other country (Tanzania, DRC, Uganda…) overrides this. "
            "And NEVER ask 'are you in Kenya?' or any country question to pick "
            "a currency — asking makes them feel far from the shop. Choose from "
            "cues, quote confidently, switch seamlessly if a cue proves you "
            "wrong. One currency at a time — never two in one reply."
        )
    return (
        "\n\n## This conversation is on Facebook Messenger / Instagram (not WhatsApp)\n"
        f"- Answer product questions using the catalogue via search_catalog. Prices "
        f"from the tool are already in {money} — quote them exactly, to the cent "
        f"(4.5 is $4.50), never rounded to a whole number or a tidy figure, and "
        f"never invent a product or price. When you cannot find an item, NEVER say we don't have "
        f"it — follow NEVER SPEAK THE ABSENCE above: ask for time warmly, call "
        f"check_availability, and keep serving the closest family of items "
        f"meanwhile.{local}\n"
        "- Write PLAIN TEXT here — Messenger/Instagram show no bold, so use no "
        "asterisks, no `**`, no markdown; use short lines and hyphen lists.\n"
        "- You KNOW their name from their Messenger profile (it's in your context) — "
        "greet them by it and NEVER ask for it; only if no name appears in your "
        "context may you ask once. Do NOT open with location questions — read "
        "where they are from CUES (language, currency, a named city or church) "
        "and save each cue with capture_contact the moment it lands; their city "
        "is asked once, naturally, when the order is settled and delivery comes "
        "up.\n"
        "- At the ORDER stage the same rule holds: delivery details are the phone "
        "and address ONLY — never 'your name' when you already have it. Confirm "
        "it softly as part of confirming the order instead: 'Shall we address "
        "the parcel to your name — Francis Xavier Pereira?' — they may be "
        "ordering for their church or their bishop, and this catches it warmly.\n"
        "- HARD RULE: the MOMENT the customer states their name, city, country, "
        "phone, role/title (Bishop, Pastor, Founder…) or church/ministry — even "
        "partially ('Machakos', just a first name) — call capture_contact IN THAT "
        "SAME TURN with everything they said. A stated detail that goes unsaved "
        "is a lost customer record.\n"
        "- CLOSE THE SALE RIGHT HERE — the WHOLE order happens in this chat, the "
        "same way it does on WhatsApp. Walk it one warm step at a time: item → "
        "colour/design → size → how many they need (ONE PIECE IS THE DEFAULT; "
        "one is a fine answer) → how soon they want it → their city. Build the "
        "cart as they decide "
        "(`update_cart`), then show the items + total and confirm.\n"
        "- THE PHONE IS WHAT MAKES THE ORDER REAL. Once the items are settled, "
        "warmly ask for their WhatsApp/phone number — for the order confirmation "
        "and delivery — and pass it to capture_contact IN THAT SAME TURN. It also "
        "links their Messenger and WhatsApp into one customer. Frame it as "
        "staying in touch, never as sending them away. Without it we cannot place "
        "the order.\n"
        "- That number request IS your one natural WhatsApp invitation (see THE "
        "WHATSAPP INVITATION above) — and once they HAVE shared a phone/WhatsApp "
        "number, DO suggest it, politely and exactly once: 'Thank you — saved for "
        "your order. If it's ever easier, we're also on WhatsApp at this same "
        "number — but we can finish everything right here.' Then keep selling "
        "HERE regardless of whether they take it up. Never repeat the "
        "invitation, and never let it replace the next step of the order.\n"
        "- Then CLOSE IT HERE: ask if they're ready to pay; on their yes call "
        "`create_order` — it registers the order and returns the order number. How "
        "they PAY follows the PAYMENT rule above for THEIR country, right in this "
        "chat: a Kenyan customer gets the M-Pesa link `create_order` returns; an "
        "international customer is NOT sent that link — instead discover their "
        "transfer route and hand off, exactly as the PAYMENT rule says. Never send "
        "a Kenyan M-Pesa link to a customer outside Kenya.\n"
        "- If `create_order` says there's no phone yet, don't apologise for a "
        "system — simply ask for the number warmly, save it, and try again.\n"
        "- Do NOT push them to WhatsApp. Only if they decline to share a number "
        "(or you genuinely cannot place the order) call whatsapp_checkout_link "
        "and share the link it returns EXACTLY as given — never hand-type a wa.me "
        "link or number. That is a fallback, not the plan.\n"
        "- THE BREVITY CONTRACT (STYLE) binds with full force here: Messenger and "
        "Instagram read exactly like WhatsApp — thumb-typed, 1–3 short sentences, "
        "shared facts said once, no how-to-order lectures. You are the same "
        "Bethany House assistant, at the same human length."
    )


def _tiktok_addendum(currency: str = "USD") -> str:
    """System addendum for a TikTok DM (relayed by ManyChat). Same shopkeeper,
    same KES catalogue and order flow as Messenger/IG — with TikTok's physics:
    links don't open when tapped, every automated reply spends one of a capped
    budget (10 per 48h window), and a quiet thread can't be re-opened from our
    side. So: one short message per turn, and the phone number matters early."""
    money = money_name(currency)
    local = ""
    if currency == "USD":
        local = (
            " If they ask for Kenyan Shillings or say they're in Kenya, do NOT "
            "convert — save it with capture_contact (location, even just "
            "'Kenya'), then call search_catalog again with currency=\"KES\" and "
            "quote our real KES prices for the SAME items. SWAHILI MEANS KENYA "
            "unless they say otherwise (owner rule): quote KES without waiting "
            "to be asked; only a STATED other country overrides this. NEVER ask "
            "'are you in Kenya?' or any country question to pick a currency — "
            "read the cues, quote confidently, switch seamlessly if proven "
            "wrong. One currency at a time — never two in one reply."
        )
    return (
        "\n\n## This conversation is on TikTok (DMs relayed by ManyChat — not WhatsApp)\n"
        f"- Answer from the catalogue via search_catalog; prices from the tool are "
        f"already in {money} — quote them exactly, never invent a product or price. "
        f"When an item can't be found, NEVER say we don't have it — follow NEVER "
        f"SPEAK THE ABSENCE above.{local}\n"
        "- Write PLAIN TEXT — no markdown, no asterisks, short lines.\n"
        "- ONE message per turn, EXTRA short (1–3 sentences): TikTok allows only "
        "10 automated replies per 48-hour window, so every reply must count. "
        "Never pad, never re-greet mid-conversation.\n"
        "- LINKS DO NOT OPEN when tapped in TikTok DMs. Share a link only when it "
        "truly serves (a specific product page), on its OWN line, telling them to "
        "copy it into their browser. Prefer our WhatsApp number written as plain "
        "digits (see OUR OFFICIAL CONTACTS) over any wa.me link.\n"
        "- Their display name (from their TikTok/ManyChat profile) may be in your "
        "context — greet with it naturally if it reads like a real name; if it "
        "reads like a username/handle, skip it rather than sounding robotic.\n"
        "- HARD RULE: the MOMENT they state a name, city, country, phone, "
        "role/title or church/ministry — even partially — call capture_contact IN "
        "THAT SAME TURN with everything they said.\n"
        "- CLOSE THE SALE RIGHT HERE, one warm step at a time: item → "
        "colour/design → size → how many they need (ONE PIECE IS THE DEFAULT; "
        "one is a fine answer) → how soon they want it → their city. Build the "
        "cart as they decide "
        "(update_cart), then show items + total and confirm.\n"
        "- THE PHONE IS WHAT MAKES THE ORDER REAL — and on TikTok it is also our "
        "lifeline if this thread goes quiet (we cannot restart a TikTok chat; "
        "they must message first). Once items are settled, warmly ask for their "
        "WhatsApp/phone number for the order confirmation and delivery, and pass "
        "it to capture_contact IN THAT SAME TURN. That ask is your one natural "
        "WhatsApp invitation: mention we're on WhatsApp at the same number, "
        "once, then keep serving HERE.\n"
        "- On their yes, call create_order. Payment follows the PAYMENT rule for "
        "THEIR country: a Kenyan customer gets the M-Pesa details create_order "
        "returns (share the till/paybill as plain text, not a link); an "
        "international customer is handed off per the PAYMENT rule. Never send a "
        "Kenyan M-Pesa link to a customer outside Kenya.\n"
        "- If create_order says there's no phone yet, simply ask for the number "
        "warmly, save it, and try again.\n"
        "- THE BREVITY CONTRACT (STYLE) binds with double force here — TikTok is "
        "the most thumb-typed channel of all."
    )


# Session keys minted by the storefront chat endpoint (routers/web_chat.py:
# "web_" + sha1). Not a phone — this is how a website visitor is recognised.
WEB_KEY_PREFIX = "web_"


def _web_addendum() -> str:
    """System addendum for a visitor chatting on the bethanyhouse.co.ke storefront.

    They are already standing in the shop: the products, the prices and the order
    are all right there. Pushing them to WhatsApp from here is friction, not
    service — so the whole sale happens on the site, and WhatsApp is offered only
    the way THE WHATSAPP INVITATION describes: once, in passing, as an extra."""
    return (
        "\n\n## This conversation is on the Bethany House WEBSITE (not WhatsApp)\n"
        "- They are already on our storefront, where they can see the products and "
        "order. Serve them fully HERE: answer from the catalogue, guide the choice, "
        "and take the order in this chat, exactly as you would on WhatsApp.\n"
        "- Do NOT send them to WhatsApp to buy. Never write a wa.me link or 'message "
        "us on WhatsApp' as the way to order — that sends a customer who is already "
        "in the shop out of it.\n"
        "- Ask for their phone number naturally when the items are settled (for the "
        "order confirmation and delivery) and save it with capture_contact. That is "
        "your ONE natural WhatsApp invitation — mention we're on WhatsApp too only "
        "if it's genuinely easier for them, once, and then carry on selling here "
        "whatever they choose.\n"
        "- If they ASK for WhatsApp, or want a person, give our number warmly (see "
        "OUR OFFICIAL CONTACTS) — that's serving them, not redirecting them.\n"
        "- Write plain, warm sentences — no markdown headings, no asterisks — and "
        "THE BREVITY CONTRACT (STYLE) binds here too: 1–3 short sentences, shared "
        "facts said once, no how-to-order lectures."
    )


# ── Per-turn model routing (roadmap #2) ──────────────────────────────────────
# Route trivial customer turns (pure greetings, thanks/acknowledgements, bare
# affirmations) to the cheap model; anything that could plausibly need a tool
# call — products, prices, quantities, delivery, payment, orders, or any
# question — stays on the main model. High precision on the light path: when
# in doubt, this returns the main model, because a mis-routed sales turn is
# worse than an extra cent spent on a greeting. NOTE: unlike the persistence
# service's ack regex, this one includes bare affirmatives ("yes"/"sawa") —
# there they are load-bearing order confirmations; here a bare "sawa" with
# nothing else said still needs no tool call.
_GREETING_RE = re.compile(
    r"^(hi+|hey+|hello+|helo+|habari|niaje|mambo|sasa|yo+|good\s*(morning|afternoon|evening)|"
    r"vipi|shalom)[\s!.,]*$",
    re.IGNORECASE,
)
# Conversation-CLOSING pleasantries beyond a bare ack: deferrals ("I'll get
# back to you"), farewells, blessings. Short messages only — a real sentence
# with content is never a closer.
_CLOSER_RE = re.compile(
    r"(i(\s*will|'ll)\s*(get\s*back|revert|let\s*you\s*know|be\s*in\s*touch)|"
    r"nitakujulisha|nitarudi|nitawasiliana|talk\s*(later|soon)|"
    r"god\s*bless|be\s*blessed|blessed\s*(day|evening)|goodnight|good\s*night|"
    r"bye+|goodbye|you'?re\s*welcome|most\s*welcome|welcome|no\s*problem|"
    r"have\s*a\s*(good|great|blessed|lovely))", re.IGNORECASE)


def is_closer(text: str) -> bool:
    """A message that ENDS a conversation politely rather than advancing it —
    a bare ack ("thanks", "🙏", "amen") or a short deferral/farewell ("I'll get
    back to you", "God bless"). Used to stop the politeness ping-pong: thanks →
    "you're welcome" → "I'll get back to you" → "I'll be waiting" → "ok" → …
    Each round is a model call and reads more robotic than the last."""
    t = (text or "").strip()
    if not t or len(t.split()) > 8:
        return False
    return bool(_ACK_RE.match(t) or _CLOSER_RE.search(t))


_CLOSER_KEY_TTL = 6 * 3600


async def closer_gate(redis, channel: str, key: str, text: str) -> bool:
    """True → SKIP this turn entirely (no model call, no reply).

    The first closer in a stretch gets Neema's one warm line (the prompt's
    bare-thanks rule) — and the model turn still runs, so a deferral like
    "I'll get back to you" is scribed as the promise it is. Every FURTHER
    closer while the flag stands gets silence: the polite end of a chat is
    silence, not another blessing. Any substantive message clears the flag."""
    if redis is None:
        return False
    rkey = f"closer:{channel}:{key}"
    try:
        if not is_closer(text):
            await redis.delete(rkey)
            return False
        if await redis.get(rkey):
            await redis.expire(rkey, _CLOSER_KEY_TTL)   # keep the lid on
            _log.info("closer gate: politeness ping-pong ended for %s/%s", channel, key)
            return True
    except Exception:
        return False
    return False


async def mark_closer_answered(redis, channel: str, key: str, inbound_text: str) -> None:
    """After WE replied to a closer, arm the gate so the next one is silence."""
    if redis is None or not is_closer(inbound_text):
        return
    try:
        await redis.set(f"closer:{channel}:{key}", "1", ex=_CLOSER_KEY_TTL)
    except Exception:
        pass


_ACK_RE = re.compile(
    r"^(thanks?|thank\s*you|asante(\s*sana)?|thx|ty|amen|ok(ay)?|sawa|poa|got\s*it|"
    r"👍+|🙏+|❤️*|😊+)[\s!.,🙏👍❤😊]*$",
    re.IGNORECASE,
)


def route_model(user_text: str) -> str:
    """Return the model id to use for this turn.

    Returns the light model only for turns that plainly need no tool call —
    pure greetings and thanks/acknowledgements/one-word affirmations with
    nothing else said. Returns the main model for everything else, including
    any mention of products, prices, quantities, delivery, payment, or orders,
    or any question. Respects settings.tier2_model_routing.
    """
    if not settings.tier2_model_routing:
        return settings.tier2_model
    text = (user_text or "").strip()
    if not text:
        return settings.tier2_model
    if _GREETING_RE.match(text) or _ACK_RE.match(text):
        return settings.tier2_model_light
    return settings.tier2_model


# Signals that a public comment carries money or risk — those turns stay on the
# main model. Everything else ("how much?", "location?", "bei gani?") is the
# short price-and-pull shape the light model handles well.
_COMMENT_ESCALATE_RE = re.compile(
    r"(\d|order|buy|nunua|purchase|pay|lipa|deliver|ship|refund|wrong|scam|"
    r"fake|complain|cancel|discount|bei ya jumla|wholesale|bulk)", re.IGNORECASE)


# A comment that asks ONLY the price, in a language the no-model reply pools
# speak (English/Swahili). Strict on purpose: any digit means quantities (cart
# math -> model), any extra clause means nuance (model), and other languages
# keep the model so the mirror-their-language rule holds.
_BARE_PRICE_ASK_RE = re.compile(
    r"^[\s\W]*(how\s+much(\s+is\s+(it|this|that))?|price(\s+please)?|"
    r"bei(\s+gani)?|(pesa\s+)?ngapi|cost(\s+please)?|price\s*\?*)[\s\W]*$",
    re.IGNORECASE)


def is_bare_price_ask(text: str) -> bool:
    """True only for the naked price question the no-model pool answers well."""
    t = (text or "").strip()
    if not t or len(t.split()) > 5 or re.search(r"\d", t):
        return False
    return bool(_BARE_PRICE_ASK_RE.match(t))


def route_comment_model(user_text: str) -> str:
    """Model for a PUBLIC comment turn — the volume driver of the whole bill.

    97% of input tokens ran on the main model, and the bulk were comment
    replies: short, formulaic, tool-grounded ("the Refiller is $20 — how
    many?"). Those default to the LIGHT model. The main model is kept for the
    turns where quality is money: buying intent, quantities (any digit —
    cart math), payment words, complaints or negativity (the mood ladder
    matters most there), and long comments (nuance). Vision turns never come
    here — the caller pins media turns to the main model already."""
    if not settings.tier2_model_routing:
        return settings.tier2_model
    text = (user_text or "").strip()
    if not text:
        return settings.tier2_model_light
    if looks_negative(text):
        return settings.tier2_model
    if _COMMENT_ESCALATE_RE.search(text):
        return settings.tier2_model
    if len(text.split()) > 25:
        return settings.tier2_model
    return settings.tier2_model_light


async def _recent_call_context(db, key: str, channel: str) -> str:
    """The last few phone-call summaries with this customer, for the system
    prompt — voice and chat are ONE memory ('as we discussed on the phone'
    must be real, and what was settled on a call is never re-asked in chat).
    Empty string when there are none (or on any failure)."""
    from sqlalchemy import or_
    from app.models.call import Call
    conds = []
    if channel == "whatsapp":
        conds.append(Call.wa_id == key)
    try:
        from app.models.person import Identity
        ident = (await db.execute(select(Identity).where(
            Identity.channel == channel,
            Identity.external_id == key))).scalar_one_or_none()
        if ident is not None:
            conds.append(Call.person_id == ident.person_id)
    except Exception:
        pass
    if not conds:
        return ""
    rows = (await db.execute(
        select(Call).where(or_(*conds), Call.summary.isnot(None))
        .order_by(Call.started_at.desc()).limit(3))).scalars().all()
    lines = []
    for c in rows:
        s = (c.summary or "").strip()
        if not s:
            continue
        when = c.started_at.strftime("%d %b") if c.started_at else ""
        lines.append(f"- {when}: {s[:220]}")
    if not lines:
        return ""
    return ("\n\nRECENT PHONE CALLS WITH THIS CUSTOMER — what was discussed on "
            "the phone (use it naturally; never re-ask what was already settled "
            "there):\n" + "\n".join(lines))


async def _cross_channel_context(db, key: str, channel: str,
                                 public_comment: bool = False) -> str:
    """The customer's recent messages on their OTHER linked channels — so a
    Facebook→WhatsApp hop continues the ACTUAL conversation ('the black cassock
    at $130 we discussed'), not a vibe. Empty when unlinked or on failure.
    Under a PUBLIC COMMENT the same lines say who they are and what they told
    us — never what this comment is about: the post decides that (owner,
    2026-09-23)."""
    from app.models.person import Identity
    from app.models.conversation import Conversation
    ident = (await db.execute(select(Identity).where(
        Identity.channel == channel,
        Identity.external_id == key))).scalar_one_or_none()
    if ident is None:
        return ""
    convs = (await db.execute(select(Conversation).where(
        Conversation.person_id == ident.person_id))).scalars().all()
    lines = []
    for c in convs:
        if (c.channel == channel and (c.wa_id == key or c.external_id == key)):
            continue
        where = ((Message.wa_id == c.wa_id) if c.channel == "whatsapp" else
                 ((Message.channel == c.channel) & (Message.external_id == c.external_id)))
        rows = (await db.execute(
            select(Message).where(where)
            .where(Message.media_type.is_(None) | (Message.media_type != "note"))
            .order_by(Message.created_at.desc()).limit(4))).scalars().all()
        for m in reversed(rows):
            t = (m.text or "").strip()
            if not t:
                continue
            who = "Customer" if str(getattr(m.direction, "value", m.direction)) == "inbound" else "You"
            lines.append(f"- [{c.channel}] {who}: {t[:150]}")
    if not lines:
        return ""
    if public_comment:
        return ("\n\nTHEIR RECENT MESSAGES ON OTHER CHANNELS (same person, linked "
                "identity — for WHO they are and what they already told us: name, "
                "city, sizes, an order. The product of THIS comment is the POST's, "
                "never one from here):\n" + "\n".join(lines[-8:]))
    return ("\n\nTHEIR RECENT MESSAGES ON OTHER CHANNELS (same person, linked "
            "identity — continue THAT conversation; never re-ask what's here):\n"
            + "\n".join(lines[-8:]))


def _thread_rows(rows: list, post_id: str) -> list:
    """The rows of ONE post's thread: this person's comments under that post
    (their `comment_context.post_id`) and our replies to those comments
    (`comment_context.reply_to` naming one of them). A comment conversation
    is one per person across EVERY post, so without this a follow-up under
    the ring post was answered with the cassock set this person had asked
    about under another post the day before (owner, 2026-09-23: "we are
    speaking the rings and you answer about cassock"). Rows with no post
    attribution (before it existed) are left out — safer than guessing."""
    pid = str(post_id or "")
    if not pid:
        return rows
    mine: set = set()
    kept = []
    for m in rows:
        ctx = getattr(m, "comment_context", None) or {}
        if str(getattr(m.direction, "value", m.direction)) == "inbound":
            if str(ctx.get("post_id") or "") == pid:
                cid = getattr(m, "waba_msg_id", None)
                if cid:
                    mine.add(str(cid))
                kept.append(m)
        elif str(ctx.get("reply_to") or "") in mine:
            kept.append(m)
    return kept


async def _history(db: AsyncSession, key: str, limit: int = 20,
                   *, channel: str = "whatsapp", post_id: str | None = None) -> list[dict]:
    # WhatsApp keys on wa_id (the compat shim); other channels key on
    # (channel, external_id) since their messages carry no wa_id.
    where = (Message.wa_id == key) if channel == "whatsapp" else (
        (Message.channel == channel) & (Message.external_id == key))
    # A public comment turn reads ONE post's thread (see _thread_rows): fetch
    # wider, then keep the thread's last `limit` turns.
    fetch = max(limit * 4, 60) if post_id else limit
    rows = list(reversed((await db.execute(
        select(Message).where(where)
        # Internal NOTES are operator-private (escalation notes, call summaries,
        # silent-decision records) — they were never sent to the customer and must
        # NEVER reach the model as assistant turns it could echo back.
        .where(Message.media_type.is_(None) | (Message.media_type != "note"))
        .order_by(Message.created_at.desc()).limit(fetch)
    )).scalars().all()))
    if post_id:
        rows = _thread_rows(rows, post_id)[-limit:]
    msgs: list[dict] = []
    for m in rows:
        text = (m.text or "").strip()
        if not text:
            continue
        role = "user" if m.direction == MsgDirection.inbound else "assistant"
        # A HUMAN colleague's reply must be recognisable as such (owner,
        # 2026-08-19): Moses answered Mestowt's shipping question by hand —
        # Ethiopian Airlines, 1–2 days — and ten hours later the scheduled
        # check-in was still "following up" as if nothing had been said,
        # because his words read as just another of Neema's own turns. The
        # marker makes a colleague's answer stand out as settled team fact;
        # the prompt forbids echoing the marker itself.
        if (role == "assistant"
                and getattr(m, "sender", None) == MsgSender.human_agent
                and m.media_type != "note"):
            text = f"[TEAM — a human colleague sent this]: {text}"
        # Collapse consecutive same-role turns so the transcript alternates cleanly.
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + text
        else:
            msgs.append({"role": role, "content": text})
    # The model requires the transcript to start with a user turn.
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


async def _meta_market(db: AsyncSession, channel: str, key: str) -> tuple[str, dict, str, dict | None]:
    """(currency, loc, customer_name, source_post) for a Meta contact.
    Messenger/IG carry no phone, so the market is USD — ONE currency — until
    the EVIDENCE on this person's record says Kenya (owner, 2026-09-05; the
    chain lives in services/market.evidence_for_person): a captured location
    (their own words, or a panel edit), a country on a user row (IP, a real
    prefix), a phone on the profile, a WhatsApp identity merged with this
    one, or a phone identifier that carried its country code. Then it is the
    Kenyan market: real KES catalogue prices, M-Pesa, local delivery — never
    a USD conversion. Zambia → ZMW the same way. The name comes from the
    person / identity so a known customer is greeted by name from turn one.
    source_post ({post_id, comment}) is the post their comment funnelled in
    from — a "How much?" DM refers to THAT product, so the agent must never ask
    "what are you looking for?"."""
    from app.models.person import Person, Identity
    from app.services.market import evidence_for_person
    currency, loc, name, source_post = "USD", {}, "", None
    try:
        ident = (await db.execute(select(Identity).where(
            Identity.channel == channel,
            Identity.external_id == key))).scalar_one_or_none()
        if ident is None:
            return currency, loc, name, source_post
        person = await db.get(Person, ident.person_id)
        ev = await evidence_for_person(db, ident, person)
        users, sibs = ev["users"], ev["siblings"]
        u = users[0] if users else None
        name = ((person.display_name if person else None)
                or getattr(ident, "display_name", None)
                or (u.name if u else None) or "")
        if ev.get("country_iso"):
            loc = {"country_iso": ev["country_iso"],
                   "country": ev.get("country") or ev["country_iso"]}
            # Same market gate as WhatsApp: KE → KES, ZM → ZMW, else USD.
            currency = market_currency(ev["country_iso"])
            _log.info("market for %s/%s: %s by %s", channel, key, currency, ev.get("evidence"))
        # Source post: this identity first, then siblings on the same person
        # (a facebook comment identity funnels into a messenger DM identity),
        # then the person state (stamped by the WhatsApp handover link).
        rp = getattr(ident, "raw_profile", None) or {}
        src, comment = rp.get("source_post"), rp.get("comment")
        if not src:
            for s in sibs:
                rp2 = getattr(s, "raw_profile", None) or {}
                if rp2.get("source_post"):
                    src, comment = rp2["source_post"], rp2.get("comment")
                    break
        if not src and person is not None:
            src = (person.state or {}).get("source_post")
        if src:
            source_post = {"post_id": str(src), "comment": comment}
    except Exception:
        _log.warning("meta market lookup failed for %s/%s", channel, key, exc_info=True)
    return currency, loc, name, source_post


async def _ad_headline(db: AsyncSession, channel: str, key: str) -> str:
    """The headline of the ad this Meta contact first arrived through, or "".

    Meta's referral block on a click-to-Messenger ad carries
    ads_context_data.ad_title; routers/meta_webhook stores it on the person
    (state["ad_ref"]["headline"]). "How much is that Holy Communion set?" from
    someone who tapped an ad for the Silver Communion Tray is a question about
    THAT tray — the agent must know which ad they came from (owner,
    2026-09-16), the same way a comment's post is carried into its DM."""
    from app.models.person import Person, Identity
    try:
        ident = (await db.execute(select(Identity).where(
            Identity.channel == channel,
            Identity.external_id == key))).scalar_one_or_none()
        if ident is None:
            return ""
        person = await db.get(Person, ident.person_id)
        st = (getattr(person, "state", None) or {}) if person is not None else {}
        title = ((st.get("ad_ref") or {}).get("headline") or "").strip()
        return title[:200]
    except Exception:
        _log.warning("ad headline lookup failed for %s/%s", channel, key, exc_info=True)
        return ""


async def run_turn(db: AsyncSession, redis, wa_id: str, user_text: str, llm: LLM,
                   media: dict | None = None,
                   *, channel: str = "whatsapp", external_id: str | None = None,
                   public_comment: bool = False, read_only: bool = False,
                   scribe_only: bool = False,
                   product_sink: list | None = None,
                   comment_reading: dict | None = None,
                   comment_post_id: str | None = None,
                   thread_parent: dict | None = None) -> str:
    """Run one agent turn and return the reply text (does NOT send it).

    WhatsApp is the default and unchanged. For Messenger/Instagram, pass
    channel + external_id (the PSID/IGSID): the agent keys history on that,
    skips phone/hub-bound context, uses a read-only catalogue tool set, and is
    told to route checkout to WhatsApp — one brain, one KES catalogue."""
    is_meta = channel in META_CHANNELS
    is_tiktok = channel == TIKTOK_CHANNEL
    # Website storefront visitor (web_chat mints a "web_<sha1>" session key rather
    # than a phone). They're already on the site that sells — see _web_addendum.
    is_web = not is_meta and str(wa_id or "").startswith(WEB_KEY_PREFIX)
    key = external_id if (is_meta or is_tiktok) else wa_id

    # ── The daily spend ceiling — checked before ANY token is bought.
    # Past the soft budget (economy), a main-model turn quietly becomes a
    # light-model turn: every customer still gets answered, at a third of the
    # price. Past the hard stop, the turn refuses here and the caller's
    # existing failure handling takes over — hold line, team flag, "budget" on
    # /api/health — the exact path an out-of-credit day already proved out,
    # but self-imposed and self-clearing at midnight UTC. Fails open: no
    # redis, no verdict, no blocking (services/ai_budget).
    from app.services import ai_budget
    if await ai_budget.guard_turn(redis) == "economy" \
            and getattr(llm, "_model", None) == settings.tier2_model:
        llm = build_llm(model=settings.tier2_model_light)

    # Currency display gate: Kenya → KES; everyone else → USD (= KES /
    # usd_kes_rate, done in the tools). WhatsApp knows Kenya from the +254
    # prefix; Meta channels know it from the captured location.
    if is_meta or is_tiktok:
        # TikTok shares the Meta market path: no phone, so the market comes from
        # the identity's captured location (their own words) — USD until a cue
        # proves Kenya, then real KES prices, exactly like Messenger/IG.
        user = None
        currency, loc, customer_name, source_post = await _meta_market(db, channel, key)
        # The ad they tapped, when there is no post to carry: "that set" in
        # their first message is the product this ad shows.
        ad_headline = (await _ad_headline(db, channel, key)) if is_meta else ""
    else:
        ad_headline = ""
        user = (await db.execute(
            select(User).where(User.wa_id == wa_id))).scalar_one_or_none()
        # A web session key ("web_<sha1>") is NOT a phone — its hex digits used to
        # resolve to a random country/currency. No phone → no country claim,
        # EXCEPT what the storefront already resolved for us: web_chat geolocates
        # the visitor's IP and stamps User.country_iso, so a Nairobi visitor is
        # quoted KES without ever being asked where they are (owner rule).
        from app.core.phone import is_plausible_phone as _plausible
        loc = (resolve_country(wa_id) or {}) if _plausible(wa_id) else {}
        if not loc.get("country_iso") and user is not None and getattr(user, "country_iso", None):
            loc = {"country_iso": user.country_iso,
                   "country": user.country or user.country_iso}
        # Market gate: Kenya → KES; a country whose currency the hub prices
        # (Zambia → ZMW) → that currency; everyone else → USD.
        currency = market_currency(loc.get("country_iso"))
        customer_name = (user.name if user else "") or ""
        source_post = None
    # Standing orders + learned rules: the owner's live steering and the rules
    # they approved from Neema's own weekly distillation.
    try:
        from app.services.app_settings import get_directives, get_learned_rules
        _directives = await get_directives(db, redis)
        _learned = await get_learned_rules(db, redis)
        if _learned:
            _directives = (_directives + "\n\nLEARNED RULES (approved from "
                           "experience — follow them):\n" + _learned).strip()
    except Exception:
        _directives = ""
    # The house voice: the team's own replies, distilled. Best-effort — Neema
    # answers in her default voice if the block can't be read.
    try:
        from app.services.app_settings import get_house_voice
        _house = await get_house_voice(db, redis)
    except Exception:
        _house = ""
    # The offer the owner declared, if one is running today. Best-effort: no
    # campaign, an expired one, or a settings hiccup all mean "no offer", and
    # silence never gives away margin.
    try:
        from app.services import promotions as _promo
        _offer = _promo.describe(await _promo.campaign_now(redis))
    except Exception:
        _offer = ""
    system = build_system_prompt(
        country_iso=loc.get("country_iso") or "",
        currency=currency,
        directives=_directives,
        house_voice=_house,
        offer=_offer,
    )
    if is_meta:
        system += _public_comment_addendum(currency) if public_comment else _meta_addendum(currency)
    elif is_tiktok:
        system += _tiktok_addendum(currency)
    elif is_web:
        system += _web_addendum()
    # Everything about THIS customer goes in a SECOND system block ("the tail"),
    # so the rules block above stays byte-identical fleet-wide and every turn
    # reads it from one shared cache entry instead of writing its own copy
    # (block 0 carries the 1h-TTL breakpoint — see llm._cached_system).
    # A price we already gave this customer stands, whatever the campaign is
    # doing now — otherwise she quotes them MORE today than yesterday.
    try:
        from app.services import promotions as _promo2
        _promise = _promo2.promise_line(
            await _promo2.granted_promise(redis, channel, key))
    except Exception:
        _promise = ""
    tail = customer_context(customer_name, loc.get("country") or "", _promise)

    # 40 messages of context (was 20): re-asking an answered question is the
    # most robotic failure there is, and it usually happened because the answer
    # had scrolled out of a too-short window.
    # Comment threads are short exchanges under one post — 14 messages of
    # history covers them; DMs keep the full window (limit=40) because "the
    # colour named three messages ago is still the colour" needs reach.
    # A public comment turn reads THIS post's thread only (owner, 2026-09-23):
    # the same person's comments under another post are another conversation.
    messages = await _history(db, key,
                              limit=(14 if public_comment else 40), channel=channel,
                              post_id=(comment_post_id if public_comment else None))

    # Voice + text are one memory: recent call summaries join the context
    # (best-effort — a calls hiccup never blocks a chat reply).
    try:
        _call_ctx = await _recent_call_context(db, key, channel)
        if _call_ctx:
            tail += _call_ctx
    except Exception:
        pass

    # Cross-channel memory: what the SAME person said on their other linked
    # channels — the Facebook→WhatsApp bridge continues the real conversation.
    try:
        _xc = await _cross_channel_context(db, key, channel, public_comment=public_comment)
        if _xc:
            tail += _xc
    except Exception:
        pass

    # A shared Facebook link is the customer pointing at a product without
    # words — open it and describe it, rather than asking them to type out
    # what they already sent. Best-effort: a dead link never blocks the reply.
    try:
        from app.services.link_preview import shared_link_context
        _link = await shared_link_context(user_text, redis)
        if _link:
            tail += _link
    except Exception:
        pass

    # Per-deal operator guidance ("no discount on this one") — obeyed for THIS
    # customer only; safety rules still win. Best-effort.
    try:
        from app.services.deals import guidance_for
        _g = await guidance_for(db, key, channel)
        if _g:
            tail += ("\n\nDEAL GUIDANCE FROM THE TEAM — for THIS customer only, "
                     "follow it (pricing/payment/stock safety rules still win):\n" + _g)
    except Exception:
        pass

    # What "this product" means: the products past turns actually surfaced for
    # THIS contact (photo-only asks included — their text history shows
    # nothing). Makes a returning "is it available now?" resolvable without
    # asking the customer to start over. Best-effort (see product_interest).
    try:
        from app.services import product_interest
        _pi = product_interest.context_block(
            await product_interest.recall(redis, channel, key))
        if _pi:
            tail += _pi
    except Exception:
        pass

    # Current inbound turn. An image message has empty text (skipped by _history),
    # so build a multimodal turn — the agent SEES the photo (Claude vision) and
    # can match it to the catalogue. Voice notes already arrive as transcribed
    # text, so they need no special handling here.
    img_block = None
    if settings.tier2_vision and media and (media.get("type") == "image"):
        from app.agent.media import load_image_block
        # to_thread: the loader does blocking I/O (local disk, or an HTTPS fetch
        # of a Meta CDN attachment / post thumbnail) — keep the event loop free.
        img_block = await asyncio.to_thread(load_image_block, media.get("url"))
    if img_block:
        caption = (media.get("caption") or "").strip()
        # The inbound row is often already at the tail of history — as an
        # "[image]" placeholder (Meta path) and/or the bare caption. Fold it
        # into the one multimodal turn so the model sees a single clean photo
        # message and roles keep alternating.
        lead = ""
        if messages and messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], str):
            lead = messages[-1]["content"].strip()
            if lead.endswith("[image]"):
                lead = lead[: -len("[image]")].strip()
            if lead == caption:
                lead = ""
            messages.pop()
        text = "\n".join(p for p in (lead, caption) if p)
        messages.append({"role": "user", "content": [
            img_block,
            {"type": "text", "text": text or
             "(The customer sent this photo. Identify the item and search our catalogue for it.)"},
        ]})
    # The just-received message is already persisted by /message; only append it
    # if history didn't capture it (defensive) so the model always sees it last.
    elif not messages or messages[-1]["role"] != "user" or user_text.strip() not in messages[-1]["content"]:
        text = user_text.strip()
        if not text and media:
            # Image-only turn whose photo couldn't be loaded — never send an
            # empty turn; tell the model what happened so it asks, warmly.
            text = ("(The customer sent a photo that could not be loaded. Ask them "
                    "to describe the item in words so you can help.)")
        messages.append({"role": "user", "content": text or "(empty message)"})

    # Leading context turn: prepended so it stays behind the cached system
    # prefix and ahead of the real transcript, and never touches the dedup
    # check above (which only looks at the last message).
    lead_ctx: list[str] = []
    post_img = None
    if source_post:
        # The customer funnelled in from a specific post — their "How much?"
        # refers to THAT product. Give the agent the post context (and, on the
        # first engagement, the post image itself — native vision) so it never
        # asks "what are you looking for?".
        pctx = {}
        try:
            from app.routers.meta_webhook import _post_context
            # The post lives on the channel that owns the comment: an Instagram DM
            # came from IG media, a Messenger DM from a Facebook post. Reading an
            # IG media with Facebook's fields returns nothing, so this must match.
            post_channel = "instagram" if channel == "instagram" else "facebook"
            pctx = await _post_context(source_post.get("post_id"), redis=redis,
                                       channel=post_channel) or {}
        except Exception:
            pass
        line = "(Context — this customer reached us from our Facebook/Instagram post"
        if pctx.get("title"):
            line += f' "{pctx["title"]}"'
        if source_post.get("comment"):
            line += f'; their comment there was: "{source_post["comment"]}"'
        # History wisdom: a caption-less video post identified once stays
        # identified — later replies price the SAME product, never a re-guess.
        # On the very first contact, the deterministic ladder (caption
        # slug/alias, image fingerprint vs our own catalogue photos) resolves
        # and records it before the model ever has to read the frame.
        try:
            _known = await _post_identity(redis, channel,
                                          {**pctx, "post_id": source_post.get("post_id") or ""})
        except Exception:
            _known = {}
        # What the post SELLS, when it is more than one row: a hub set row
        # (its contents from the hub's description), a combination the
        # caption presents as one outfit, or a caption that merely LISTS
        # several items (owner, 2026-09-21: the price of a set is its total).
        _catalog: list = []
        try:
            from app.services import n8n_bridge as _svc_cat
            _catalog = await _svc_cat.catalog_items(db, redis)
        except Exception:
            _catalog = []
        if _known.get("name"):
            from app.services.post_catalog import identity_trusted as _trusted_id
            if _trusted_id(_known):
                line += (f". Our records identify this post's product as: "
                         f"{_known['name']} — price THAT product; do not "
                         "re-identify it from the image")
                line += _set_context(_known, _catalog)
            else:
                # A model's earlier read, or a record from before provenance:
                # a lead, not a fact (owner, 2026-09-21). The image decides.
                line += (f". An earlier reply under this post priced: {_known['name']} "
                         "— a lead, not a record: CONFIRM it against the caption and "
                         "the image before you rely on it (search_catalog it, compare "
                         "what you see). If the photo plainly shows something else, "
                         "price what you see; if you cannot tell, give the two closest "
                         "options or ask which — never a price on a guess")
            if _known.get("seen"):
                line += (f"; as it appears in the post: {_known['seen']} — name it "
                         "to the customer in those plain words, colour and trim "
                         "included, never the catalogue label alone")
        elif pctx.get("title"):
            line += _listed_items_context(pctx["title"], _catalog)
        line += (". Unless they say otherwise, their questions refer to the product "
                 "in that post — identify it, find it with search_catalog, and "
                 "answer about THAT item. Do not ask what they are looking for.)")
        lead_ctx.append(line)
        if public_comment and thread_parent:
            lead_ctx.append(_thread_parent_context(thread_parent))
        if (settings.tier2_vision and not img_block and pctx.get("thumb")
                and not any(m["role"] == "assistant" for m in messages)):
            from app.agent.media import load_image_block
            post_img = await asyncio.to_thread(load_image_block, pctx["thumb"])
    elif ad_headline:
        # They tapped one of our ads (owner, 2026-09-16): "that set", "that
        # one", "how much is it" in their first messages mean the product the
        # ad shows — price THAT item first, from the hub, then take the order;
        # never open with a menu of dearer siblings.
        lead_ctx.append(
            f'(Context — this customer reached us from our ad "{ad_headline}". '
            "Unless they say otherwise, 'that set', 'that one' and 'how much is "
            "it?' refer to the product this ad shows: find it with "
            "search_catalog by the hub's own name, price THAT item first and "
            "take the order. Do not ask what they are looking for, and do not "
            "open with a list of other products.)")
    if settings.tier2_memory:
        mem_ctx = await build_memory_context(db, redis, key, user=user, channel=channel)
        if mem_ctx:
            lead_ctx.append(f"(Context — what you know about this customer:\n{mem_ctx})")
    if public_comment and comment_reading:
        # What this comment IS (owner, 2026-09-22): a request is answered with
        # the shelf, a question with the answer, praise in kind.
        _rline = _reading_context(comment_reading)
        if _rline:
            lead_ctx.append(_rline)
    if lead_ctx:
        content = "\n\n".join(lead_ctx)
        if post_img:
            messages.insert(0, {"role": "user", "content": [post_img,
                                                            {"type": "text", "text": content}]})
        else:
            messages.insert(0, {"role": "user", "content": content})

    ctx = ToolContext(db=db, redis=redis, wa_id=key, channel=channel,
                      currency=currency, usd_rate=settings.usd_kes_rate,
                      seen_products=(product_sink if product_sink is not None else []),
                      read_only=read_only)
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
              "cache_write_tokens": 0, "cache_write_1h_tokens": 0}

    def _accumulate(u: dict) -> None:
        for k in totals:
            totals[k] += int(u.get(k, 0) or 0)

    if is_meta and public_comment:
        base = PUBLIC_COMMENT_TOOLS       # the comment thread sells — full kit, link-free
    elif is_meta or is_tiktok:
        # TikTok is the same phone-less DM sale as Messenger/IG: full selling
        # kit, order closed in-thread, whatsapp_checkout_link as the fallback.
        base = MESSENGER_TOOLS
    elif is_web:
        # The visitor is ALREADY on our storefront, where the whole order can be
        # taken. Handing them a wa.me link here is pure friction — it sends a
        # ready buyer to another app — so the WhatsApp-link tool is off the table
        # on the website; her one natural invitation is the phone ask instead.
        base = [t for t in TOOLS if t["name"] != "whatsapp_checkout_link"]
    else:
        # On WhatsApp itself the customer is ALREADY in the thread, so a wa.me
        # invitation is a link back to where they are standing — and it is the
        # shape of link that got handed to a buyer as "your order link", landing
        # her in an empty chat. Their order link is create_order's order_url.
        base = [t for t in TOOLS if t["name"] != "whatsapp_checkout_link"] \
            if channel == "whatsapp" else TOOLS
    tools = base if settings.tier2_memory else [t for t in base if t["name"] != "remember"]
    if read_only:
        # Draft mode: strip to read-only tools so composing a suggestion never
        # creates an order, edits the cart, or sends a message.
        tools = [t for t in tools if t["name"] in _READONLY_TOOL_NAMES]
    if scribe_only:
        # Copilot scribe (plan C3): a human is talking to the customer; Neema is
        # ONLY the record-keeper this turn — CRM-writing tools, no reply.
        tools = [t for t in tools if t["name"] in _SCRIBE_TOOL_NAMES]
        system += ("\n\n[SCRIBE MODE — a human colleague is handling this chat. "
                   "You are ONLY the record-keeper this turn: from the latest "
                   "messages, call tools to save any facts revealed (name, city, "
                   "phone, role/title, church/ministry, measurements, durable "
                   "preferences). Do NOT compose anything customer-facing. When "
                   "done (or if there is nothing to save), reply with exactly: "
                   "noted]")

    # Two system blocks: [shared rules | this customer]. The list form is what
    # tells the LLM client to put the fleet-shared 1h cache breakpoint on block 0.
    sys_blocks: str | list[str] = [system, tail] if tail else [system]

    reply = None
    # A public comment reply is one search + one short answer; the full
    # 8-iteration budget belongs to real sales conversations (cart, order,
    # measurements). Half the ceiling caps the worst-case cost of the
    # highest-volume path without touching its normal shape.
    _max_iter = (min(settings.tier2_max_iterations, 4) if public_comment
                 else settings.tier2_max_iterations)
    for _ in range(_max_iter):
        resp: LLMResponse = await llm.complete(system=sys_blocks, messages=messages, tools=tools)
        _accumulate(resp.usage or {})
        messages.append({"role": "assistant", "content": resp.assistant_content})

        if not resp.tool_calls:
            reply = resp.text or "One moment — let me check on that for you."
            break

        results = []
        for call in resp.tool_calls:
            out = await run_tool(call.name, call.input, ctx)
            _log.info("agent tool %s(%s) -> %s", call.name, json.dumps(call.input)[:120],
                      json.dumps(out)[:160])
            # The Activity Log's per-turn trail: every tool call becomes a row
            # a human can read (owner's rule, 2026-08-19 — "every activity in
            # the interaction"). Real turns only — a read-only draft or scribe
            # pass previews, it doesn't act. Best-effort by construction.
            if not read_only and not scribe_only:
                try:
                    from app.services import activity_trail
                    await activity_trail.record(db, channel=channel, contact=key,
                                                tool=call.name, args=call.input,
                                                out=out)
                except Exception:
                    pass
            results.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": json.dumps(out),
            })
        messages.append({"role": "user", "content": results})
    else:
        # Ran out of iterations — return the last text if any, else a safe fallback.
        reply = resp.text or "Let me get a colleague to help you with this."

    # Measure spend so cost is visible, not guessed at (best-effort). Two
    # honesty rules learned when the bill was audited (2026-08-18): log the
    # model that ACTUALLY served the turn — settings.tier2_model recorded every
    # Haiku-routed turn as Sonnet, so the per-model split was fiction — and tag
    # the row with WHERE the money went (comment vs channel), because "the
    # volume driver of the whole bill" was a guess nobody could query.
    # Make this turn's surfaced products durable — the memory the next
    # "is this product available now?" resolves against. Real turns only:
    # a read-only draft or a scribe pass must never pollute the record.
    if not read_only and not scribe_only and ctx.seen_products:
        try:
            from app.services import product_interest
            await product_interest.remember(redis, channel, key, ctx.seen_products)
        except Exception:
            pass

    _served = getattr(llm, "_model", None) or settings.tier2_model
    # Feed the daily breaker FIRST, from the same numbers, independently of the
    # DB — a down database must never blind the spend meter (ai_budget owns
    # its own best-effort guards, so this line can't cost the reply either).
    from app.core.ai_pricing import estimate_cost_usd
    await ai_budget.add_spend(redis, estimate_cost_usd(
        _served,
        totals["input_tokens"] + totals["cache_read_tokens"] + totals["cache_write_tokens"],
        totals["output_tokens"], cached_tokens=totals["cache_read_tokens"],
        cache_write_tokens=totals["cache_write_tokens"],
        cache_write_1h_tokens=totals["cache_write_1h_tokens"]))
    try:
        from app.services import n8n_bridge as svc
        _node = f"{channel}:comment" if public_comment else channel
        await svc.log_agent_usage(db, key, _served, totals, node=_node)
    except Exception:
        _log.warning("usage logging failed for %s", key, exc_info=False)

    # Let the AI keep the lead stage + country tag current (forward-only).
    # WhatsApp only — lead_signals is keyed on wa_id/OrderEvent, which a
    # phone-less Meta or TikTok conversation has none of.
    if not is_meta and not is_tiktok and not read_only:
        from app.services.lead_signals import refresh_lead_signals
        await refresh_lead_signals(db, wa_id)
    return reply


def build_llm(model: str | None = None) -> LLM:
    from app.agent.llm import AnthropicLLM
    return AnthropicLLM(
        api_key=settings.anthropic_api_key,
        model=model or settings.tier2_model,
        max_tokens=settings.tier2_max_tokens,
        cache=settings.tier2_prompt_cache,
    )


# ── Background trigger (used by the /profile hook) ───────────────────────────
# Tier 2 runs the agent OFF the request path so /profile stays fast: it schedules
# a background task that runs the loop, sends the reply, and persists it. n8n's
# 'Should Run AI?' then sees should_run_ai=false and stays silent. Deduped per
# inbound message so a retried /profile never double-replies.

import asyncio  # noqa: E402

_bg_tasks: set = set()


async def _is_paused(redis, channel: str, key: str) -> bool:
    """True while the agent has paused this contact (pause_conversation tool —
    non-buying drift cooldown). Best-effort: no redis → not paused."""
    try:
        if redis is not None and await redis.get(f"agent:pause:{channel}:{key}"):
            _log.info("agent paused for %s/%s — skipping reply", channel, key)
            return True
    except Exception:
        pass
    return False


def _hold_line(channel: str = "whatsapp") -> str:
    """What a customer gets when the turn could not be answered.

    It used to be an apology: a "small technical hitch on my side", a colleague
    alerted, back to you shortly. Two things were wrong with it. It tells a
    customer about OUR problem, which is not theirs to carry — and when the
    tokens are out nobody is coming back to them soon, so the promise is empty.

    So say the true, useful thing instead: welcome them, and give them the ways
    to reach us. It is what the shop says to every arrival, and it works
    whether the outage lasts a minute or the rest of the evening.

    Needs no LLM, no catalogue, no DB — this runs precisely when those are what
    broke, so it is built from config alone. It names NO product and NO price:
    an unpriced guess here would be worse than the silence it replaces.
    """
    wa = (settings.whatsapp_handoff_number or "").strip()
    alt = (settings.whatsapp_handoff_alt or "").strip()
    parts = ["Hello and welcome to Bethany House 🙏 We are so glad to have you here."]
    if channel == "whatsapp":
        # They are already in the WhatsApp thread — quoting the number back at
        # them is noise. The alternative line is the one they cannot see.
        reach = ("For samples, further inquiries, or to place your order, send "
                 "us a message right here and we will take good care of you.")
        if alt:
            reach += f" You can also call us on {alt}."
        parts.append(reach)
    elif wa:
        parts.append("For samples, further inquiries, or to place your order, "
                     f"please reach out to us via WhatsApp at {wa}.")
    elif alt:
        parts.append("For samples, further inquiries, or to place your order, "
                     f"please call us on {alt}.")
    else:
        parts.append("For samples, further inquiries, or to place your order, "
                     "leave us a message here and we will get right back to you.")
    parts.append("Thank you for choosing Bethany House 💛")
    return "\n\n".join(parts)


async def _send_hold_line(redis, channel: str, key: str) -> None:
    """When a turn dies, the customer must never get pure silence.

    Once per thread per two hours: send a short honest hold message (it needs
    no LLM — the send path is independent of what broke) and flag the team in
    the Activity feed. Best-effort everywhere; this runs inside a failure
    handler and must never raise.

    Deliberately NO automatic retry of the failed turn: a turn that died
    mid-loop may already have executed tools (a cart add, an order), and
    re-running it would repeat them. The missed-reply sweeper re-engages the
    thread once the underlying cause clears."""
    try:
        if redis is not None:
            try:
                if not await redis.set(f"agent:holdline:{channel}:{key}", "1",
                                       nx=True, ex=7200):
                    return
            except Exception:
                pass
        from app.database import AsyncSessionLocal
        from app.services import n8n_bridge as svc
        text = _hold_line(channel)
        if channel == "whatsapp":
            wamid = await svc._send_waba(key, text)
            async with AsyncSessionLocal() as db:
                await svc.save_outbound_message(db, redis, key, text,
                                                waba_msg_id=wamid)
        else:
            from app.services.meta_send import send_to_channel
            await send_to_channel(channel, key, text)
            async with AsyncSessionLocal() as db:
                await svc.save_outbound_channel_message(db, redis, channel, key,
                                                        text)
        try:
            async with AsyncSessionLocal() as db:
                from app.models.conversation import Conversation
                from app.models.intercept import Intercept, InterceptAction
                where = (Conversation.wa_id == key) if channel == "whatsapp" else (
                    (Conversation.channel == channel) & (Conversation.external_id == key))
                conv = (await db.execute(
                    select(Conversation).where(where))).scalar_one_or_none()
                if conv is not None:
                    db.add(Intercept(conversation_id=conv.id, agent_id=None,
                                     action=InterceptAction.flag,
                                     note="Neema's reply FAILED here — the customer got the "
                                          "welcome-and-contacts line, not an answer. "
                                          "Please review and reply."))
                    await db.commit()
        except Exception:
            pass
        _log.info("hold line sent to %s/%s", channel, key)
    except Exception:
        _log.warning("hold line failed for %s/%s", channel, key, exc_info=False)


async def _is_echo(db, channel: str, key: str, reply: str,
                   *, window_minutes: int = 10) -> bool:
    """True when `reply` is word-for-word what we JUST sent on this thread.

    Live case (José, 02:25): a burst of rapid messages each drew the same
    'One moment — let me check on that for you.' — three identical stalls in
    58 seconds. An identical reply within minutes of itself never serves the
    customer; it's already the last thing on their screen. The window is short
    ON PURPOSE: a customer re-asking the price tomorrow deserves an answer,
    even an identical one — only the rapid echo is robotic."""
    t = " ".join((reply or "").lower().split())
    if not t:
        return True
    from datetime import datetime, timedelta, timezone
    from app.models.message import Message, MsgDirection
    where = ((Message.wa_id == key) if channel == "whatsapp" else
             ((Message.channel == channel) & (Message.external_id == key)))
    last = (await db.execute(
        select(Message.text).where(
            where, Message.direction == MsgDirection.outbound,
            Message.media_type.is_(None) | (Message.media_type != "note"),
            Message.created_at > datetime.now(timezone.utc) - timedelta(minutes=window_minutes))
        .order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()
    return " ".join((last or "").lower().split()) == t


async def _run_and_send(redis, wa_id: str, text: str, media: dict | None = None) -> None:
    from app.database import AsyncSessionLocal
    from app.services import n8n_bridge as svc
    try:
        # A photo turn always takes the main model — vision + catalogue matching
        # is never "light" work, whatever the caption says.
        model = settings.tier2_model if media else route_model(text)
        async with AsyncSessionLocal() as db:
            reply = await run_turn(db, redis, wa_id, text,
                                   build_llm(model=model), media=media)
            if await _is_echo(db, "whatsapp", wa_id, reply):
                _log.info("echo guard: identical reply within minutes suppressed for %s", wa_id)
                return
        wamid = await svc._send_waba(wa_id, reply)
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_message(db2, redis, wa_id, reply, waba_msg_id=wamid)
        await mark_closer_answered(redis, "whatsapp", wa_id, text)
        _log.info("tier2 replied to %s (%d chars)", wa_id, len(reply))
        # She answered — so whatever a person was told to go and fix is fixed.
        from app.services.agent_health import record_turn_success
        await record_turn_success(redis)
        # The scribe files the turn (deal items/stage/promises) — best-effort.
        try:
            from app.services.deals import scribe_update
            async with AsyncSessionLocal() as db3:
                await scribe_update(db3, wa_id, "whatsapp", reply, inbound_text=text)
        except Exception:
            pass
    except Exception as exc:
        _log.exception("tier2 background turn failed for %s", wa_id)
        # Count it so the hourly self-check can say the AI has stopped replying —
        # and why. An out-of-credit account silenced every channel for days and
        # the only trace was this log line.
        from app.services.agent_health import record_turn_failure
        await record_turn_failure(redis, wa_id, exc)
        await _send_hold_line(redis, "whatsapp", wa_id)


async def schedule_reply(redis, wa_id: str, text: str, dedup_id: str | None,
                         media: dict | None = None) -> bool:
    """Fire the agent for this inbound once. Returns False if already handled."""
    if await _is_paused(redis, "whatsapp", wa_id):
        return False
    if media is None and await closer_gate(redis, "whatsapp", wa_id, text):
        return False
    if redis is not None and dedup_id:
        try:
            ok = await redis.set(f"agent:seen:{dedup_id}", "1", ex=600, nx=True)
            if not ok:
                return False
        except Exception:
            pass  # if the dedup store is down, better to reply than to go silent
    task = asyncio.create_task(_run_and_send(redis, wa_id, text, media))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return True


# ── Messenger / Instagram trigger ─────────────────────────────────────────────
# The Meta webhook calls this after storing an inbound DM. Same agent, one KES
# catalogue; the reply goes out via the Graph Send API and is saved as a
# channel message. Deduped on the Meta message id.

# Meta rejects a send more than 24h after the customer's last message:
# "(#10) This message is sent outside of allowed window", subcode 2018278.
_WINDOW_MARKERS = ("outside of allowed window", "2018278")


def is_outside_window(exc_or_text) -> bool:
    """True when Meta refused a send because its 24-hour messaging window closed
    — a policy wall, not a bug: no retry can fix it, only a human can reply."""
    s = str(exc_or_text or "").lower()
    return any(m in s for m in _WINDOW_MARKERS)


async def escalate_to_human(channel: str, ext: str, note: str,
                            draft: str | None = None, redis=None) -> bool:
    """Hand this conversation to a person: route it out of AI mode and leave the
    reason in the Activity log, so the team sees it needs them. Used when Meta's
    24-hour window has closed — Neema physically cannot reply, but a human still
    can (Meta allows human agents a 7-day window). Best-effort; never raises.

    `draft` is the ONE-TAP flow (owner, 2026-08-19): the reply Neema composed
    but could not send is stored as the thread's held draft, so the dashboard's
    existing draft card shows it the moment the thread opens (and live, over
    the `ai_draft_ready` ws event) — a person reads it and taps Approve, and it
    goes out under Meta's human-agent window. The human'S tap is what makes
    claiming that window honest; nothing here sends anything by itself.

    Idempotent by construction: once the thread is in human mode the sweep no
    longer selects it, so it's flagged once, not every tick."""
    from sqlalchemy import or_
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation, InterceptMode
    from app.models.intercept import Intercept, InterceptAction
    try:
        async with AsyncSessionLocal() as db:
            conv = (await db.execute(select(Conversation).where(
                Conversation.channel == channel,
                or_(Conversation.external_id == ext,
                    Conversation.wa_id == ext)))).scalars().first()
            if conv is None:
                return False
            conv.intercept_mode = InterceptMode.human
            db.add(Intercept(conversation_id=conv.id,
                             action=InterceptAction.flag, note=note[:500],
                             ai_reply_held=(draft or None)))
            await db.commit()
            conv_id = str(conv.id)
        if draft and redis is not None:
            try:
                payload = json.dumps({
                    "type": "ai_draft_ready",
                    "conversationId": conv_id,
                    "waId": ext,
                    "draft": draft,
                })
                await redis.publish(f"ws:channel:{conv_id}", payload)
                await redis.publish("ws:channel:agents:all", json.dumps({
                    "event": "notification", "type": "draft_ready",
                    "title": "✍️ Draft ready — one tap to send",
                    "body": note[:200], "conv_id": conv_id, "wa_id": ext,
                }))
            except Exception:
                pass
        return True
    except Exception:
        _log.warning("human escalation failed for %s/%s", channel, ext, exc_info=True)
        return False


async def _run_and_send_meta(redis, channel: str, external_id: str, text: str,
                             page_id: str | None = None,
                             media: dict | None = None) -> bool:
    """Generate + send one Meta reply. Returns True only when it actually
    reached the customer (so the sweep counts real sends, not attempts)."""
    from app.database import AsyncSessionLocal
    from app.services.meta_send import send_to_channel, send_typing_on
    from app.services import n8n_bridge as svc
    reply = ""
    try:
        # Human presence: "typing…" in their Messenger while the turn composes.
        # Meta-only edge — TikTok (which also rides this path natively) has no
        # typing indicator API.
        try:
            if channel in META_CHANNELS:
                await send_typing_on(external_id, page_id=page_id)
        except Exception:
            pass
        model = settings.tier2_model if media else route_model(text)
        async with AsyncSessionLocal() as db:
            reply = await run_turn(db, redis, wa_id=external_id, user_text=text,
                                   llm=build_llm(model=model),
                                   channel=channel, external_id=external_id,
                                   media=media)
            if await _is_echo(db, channel, external_id, reply):
                _log.info("echo guard: identical reply within minutes suppressed for %s/%s",
                          channel, external_id)
                return True
        await send_to_channel(channel, external_id, reply, page_id=page_id)
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_channel_message(db2, redis, channel, external_id, reply)
        await mark_closer_answered(redis, channel, external_id, text)
        _log.info("tier2 replied on %s to %s (%d chars)", channel, external_id, len(reply))
        from app.services.agent_health import record_turn_success
        await record_turn_success(redis)
        # The scribe files the turn (deal items/stage/promises) — best-effort.
        try:
            from app.services.deals import scribe_update
            async with AsyncSessionLocal() as db3:
                await scribe_update(db3, external_id, channel, reply, inbound_text=text)
        except Exception:
            pass
        return True
    except Exception as exc:
        if is_outside_window(exc):
            # Meta's 24h window shut before we could answer. The reply Neema
            # already composed becomes the thread's held draft — the dashboard
            # shows it with an Approve button, and one tap sends it under the
            # human-agent window (7 days). A person's tap, a person's send.
            note = ("Outside Meta's 24-hour window — Neema drafted a reply; "
                    "review it and tap Approve to send it as a human agent "
                    "(Meta allows 7 days).")
            _log.info("meta 24h window closed for %s/%s — draft held for one-tap send",
                      channel, external_id)
            await escalate_to_human(channel, external_id, note,
                                    draft=(reply or None), redis=redis)
        else:
            _log.exception("tier2 meta turn failed for %s/%s", channel, external_id)
            from app.services.agent_health import record_turn_failure
            await record_turn_failure(redis, external_id, exc)
            await _send_hold_line(redis, channel, external_id)
        return False


async def schedule_meta_reply(redis, channel: str, external_id: str, text: str,
                              dedup_id: str | None, page_id: str | None = None,
                              media: dict | None = None) -> bool:
    """Fire the agent for one inbound Messenger/IG message (text, photo, or
    both — the agent sees images natively). Deduped on the Meta message id so a
    redelivered webhook never double-replies."""
    if await _is_paused(redis, channel, external_id):
        return False
    if media is None and await closer_gate(redis, channel, external_id, text):
        return False
    if redis is not None and dedup_id:
        try:
            ok = await redis.set(f"agent:seen:meta:{dedup_id}", "1", ex=600, nx=True)
            if not ok:
                return False
        except Exception:
            pass
    task = asyncio.create_task(_run_and_send_meta(redis, channel, external_id, text,
                                                  page_id, media))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return True


# ── Facebook / Instagram comment engagement ──────────────────────────────────
# A new comment fires TWO replies: a short PUBLIC acknowledgement under the
# comment, and a PRIVATE reply that opens a Messenger DM with a real Neema answer
# so the sale continues 1:1. Runs off the webhook ack path (Meta wants a fast
# 200); deduped upstream on the comment id.

# The one line under a complaint. Human, not corporate: no "a member of our
# team will reach out", no "thank you for your patience" (which presumes they
# have been kept waiting), and no 💛 — the mood rules forbid cheer on
# displeasure, and this line used to end with it.
_PUBLIC_EMPATHY = (
    "Thank you for telling us{name} 🙏 We take this seriously, and one of us "
    "will speak with you personally to put it right."
)
# The same line in Kiswahili sanifu — for a complaint written in Swahili.
_SW_PUBLIC_EMPATHY = (
    "Asante kwa kutuambia{name} 🙏 Tunalichukulia hili kwa uzito, na mmoja wetu "
    "atazungumza nawe binafsi ili kulirekebisha."
)
# READ THE INTENT, GRADE IT, ROUTE IT (owner, 2026-09-22): "the agent should
# read the intent, grade the intent — is it a request, a complaint, a
# commendation? If a complaint, it should be graded on severity and referred
# to a human agent. If a compliment, handled by Neema. If a statement that
# looks like all three, resolve it wisely, in the best interest of the
# business and the client."
#
# A complaint's WEIGHT decides the words and the hand-off: 1 — a correction
# or a small disappointment (the line above: taken seriously, a person will
# speak with them); 2 — an order gone wrong (not delivered, wrong item, paid
# and nothing came, poor quality): an apology, a colleague today, and a
# private message opened so the details come privately; 3 — grave (a scam or
# fraud accusation, a threat to go public, abuse): the same, said with more
# weight, and the team's bell rings. A MIXED comment (kind words and a
# grievance in one breath) thanks first, then takes the grievance as a
# complaint. No cheer, no price, no pitch on any of them.
_EMPATHY_SERIOUS = (
    "We're sorry{name} 🙏 This is not the experience we want for you. One of our "
    "team is looking into it now{private}."
)
_EMPATHY_GRAVE = (
    "We're truly sorry{name} 🙏 We hear you, and this will be handled personally "
    "by our team today{private}."
)
_PRIVATE_SENT = ", and I've sent you a private message so we can put it right quickly"
_PRIVATE_SENT_GRAVE = ", and I've sent you a private message so we can resolve it with you directly"
_EMPATHY_MIXED = (
    "Thank you for the kind words{name} 🙏 and we're sorry about the part that "
    "went wrong. One of us will speak with you personally to put it right."
)
_SW_EMPATHY_SERIOUS = (
    "Samahani{name} 🙏 Hii si huduma tunayokusudia kwako. Mmoja wa timu yetu "
    "analishughulikia sasa{private}."
)
_SW_EMPATHY_GRAVE = (
    "Samahani sana{name} 🙏 Tumekusikia, na timu yetu italishughulikia binafsi "
    "leo{private}."
)
_SW_PRIVATE_SENT = ", na nimekutumia ujumbe wa faragha ili tulirekebishe haraka"
_SW_PRIVATE_SENT_GRAVE = ", na nimekutumia ujumbe wa faragha ili tulitatue nawe moja kwa moja"
_SW_EMPATHY_MIXED = (
    "Asante kwa maneno yako mazuri{name} 🙏 na samahani kwa sehemu iliyoenda "
    "vibaya. Mmoja wetu atazungumza nawe binafsi ili kulirekebisha."
)
# The private message that follows a serious or grave complaint: the details
# come privately, a person takes it up. No link, no price, no pitch.
_PRIVATE_COMPLAINT = (
    "Hello{name}, this is Bethany House. We're sorry about this, and we want to "
    "put it right. Please share the details here — your name, what you ordered "
    "and when — and a colleague will take it up with you personally today."
)
_SW_PRIVATE_COMPLAINT = (
    "Habari{name}, hapa ni Bethany House. Samahani kwa hili, na tunataka "
    "kulirekebisha. Tafadhali tuandikie maelezo hapa — jina lako, ulichoagiza "
    "na lini — na mwenzetu atalishughulikia nawe binafsi leo."
)
# A REQUEST or a QUESTION we could not answer in the thread (no model: the
# spend stop, the per-post cap, a failed turn): never the old signpost
# ("send us a message"). Their words are noted back to them, a person is
# promised, and the team is handed the ask — so the thread stays the shop.
_REQUEST_ACK_POOL = [
    "Thank you{name} 🙏 Noted: {ask}. One of our team will send you the options right here shortly.",
    "Thank you{name} 🙏 We have you: {ask}. Our team will come back to you here with what we have shortly.",
]
_QUESTION_ACK_POOL = [
    "Thank you{name} 🙏 Good question — one of our team will answer you right here shortly.",
    "Thank you{name} 🙏 Let us get you the exact answer — our team will reply to you here shortly.",
]
_SW_REQUEST_ACK_POOL = [
    "Asante{name} 🙏 Tumepokea: {ask}. Mmoja wa timu yetu atakutumia chaguo hapa hivi karibuni.",
]
_SW_QUESTION_ACK_POOL = [
    "Asante{name} 🙏 Swali zuri — mmoja wa timu yetu atakujibu hapa hivi karibuni.",
]
_INTENTS = ("high", "low", "negative", "spam", "goodwill")
_KINDS = ("request", "question", "complaint", "praise", "mixed", "greeting", "other")

# Dissatisfaction is often three words long ("this is wrong"), and a light model
# reading a clergy-store comment biased toward "buying interest" has labelled
# exactly that as `high` — which answered a complaint with a sales pitch in
# public. Displeasure is the one label we cannot afford to get wrong, so it gets
# a deterministic guard AHEAD of the model: cheap, and it also covers the paths
# where the model errors or returns something unparseable (both default to
# `high`). Precision over recall — these read as complaints in a shop context,
# not as questions.
_NEGATIVE_RE = re.compile(
    r"(?:^|\b)("
    r"this\s+is\s+(?:wrong|not\s+right|false|misleading)|"
    r"(?:that|it)['’]?s\s+(?:wrong|false|a\s+lie)|"
    r"not\s+(?:true|correct|right)|incorrect|misleading|"
    r"wrong\s+(?:information|info|price|colour|color|item|order)|"
    r"poor\s+(?:quality|service)|bad\s+(?:quality|service)|"
    r"never\s+(?:replied|delivered|received|answered|came|arrived)|"
    r"not\s+(?:delivered|received)|"
    r"still\s+(?:waiting|haven'?t)|no\s+one\s+(?:replied|answered)|"
    r"scam|fraud|cheat(?:ed|ing)?|con\s+men|thieves|"
    r"disappoint(?:ed|ing)|refund|"
    r"you\s+(?:people\s+)?(?:lied|are\s+lying)|shame\s+on\s+you"
    r")(?:$|\b)",
    re.IGNORECASE,
)


_GREETING_COMMENT_RE = re.compile(
    r"^(hi+|hey+|hello+|habari( yako| zenu)?|niaje|mambo|sasa|jambo|shalom|"
    r"how are you( doing| today)?|good (morning|afternoon|evening)|"
    r"bonjour|salut|comment (allez[- ]vous|ca va|ça va)|ca va|ça va|hola|"
    r"como estas|greetings|blessings)[\s!?.,🙏❤️😊👋]*$",
    re.IGNORECASE,
)


def looks_greeting(text: str) -> bool:
    """A comment that is a person saying hello — a conversation OPENING, never
    'kind words'. Routed to the model (high) so it gets a real greeting back
    and an invitation, instead of the canned praise thank-you (the Sylvia
    miss: 'How are you' → 'your kind words mean the world to us')."""
    return bool(_GREETING_COMMENT_RE.match((text or "").strip()))


def looks_negative(text: str) -> bool:
    """True when a comment plainly expresses displeasure, a correction, or a
    grievance. Deterministic first pass for `classify_comment_intent`."""
    return bool(_NEGATIVE_RE.search((text or "").strip()))


# A REQUEST — they want something shown, sent or offered: "share more designs
# for ladies", "send the catalogue", "post prices", "more photos please". Read
# deterministically too, so the reading survives a model outage (Queen Gili,
# 2026-09-21: "Please more designs for ladies" during the credit stop got
# "send us a message and we'll help however we can").
_REQUEST_RE = re.compile(
    r"\b(?:share|send|show|post|upload|give|bring|tuma|tutumie|onyesha|weka)\b.{0,40}?"
    r"\b(?:designs?|photos?|pictures?|pics?|images?|videos?|catalogue|catalog|"
    r"options?|samples?|prices?|price\s+list|list|collection|styles?|models?|"
    r"colou?rs?|sizes?|picha|bei|mitindo)\b"
    r"|\b(?:more|other|different|zaidi|nyingine)\s+(?:designs?|photos?|pictures?|pics?|"
    r"options?|styles?|colou?rs?|models?|samples?|picha|mitindo)\b"
    r"|\b(?:designs?|photos?|pictures?|catalogue|price\s+list)\s+(?:please|pls|plz|tafadhali)\b",
    re.IGNORECASE,
)
# Kind words — the praise half of a MIXED comment ("beautiful work, but my
# order never came"), and a compliment on its own.
_PRAISE_RE = re.compile(
    r"\b(?:beautiful|lovely|nice|great|good\s+work|well\s+done|amazing|awesome|"
    r"wonderful|excellent|gorgeous|elegant|superb|perfect|classy|smart|"
    r"love\s+(?:it|this|them|your)|congrat\w*|bless\w*|amen|"
    r"thank\s+you|thanks|asante|nzuri|safi|maridadi|hongera|barikiwa)\b",
    re.IGNORECASE,
)
_QUESTION_MARK_RE = re.compile(r"\?|\b(?:how|what|where|when|which|can|do\s+you|is\s+it|"
                               r"bei|ngapi|wapi|je\b)", re.IGNORECASE)
# The weight of a grievance, from its own words (see the pools above).
# ("stole" is a vestment here, never a theft; a lie is "you lied".)
_GRAVE_RE = re.compile(
    r"\b(?:scam\w*|fraud\w*|cheat\w*|con\s*men|thie\w+|steal\w*|stolen|lied|lying|liars?|"
    r"shame\s+on\s+you|report(?:ed|ing)?\s+(?:you|this)|police|expose|"
    r"wezi|wizi|tapeli|uongo)\b",
    re.IGNORECASE,
)
_SERIOUS_RE = re.compile(
    r"\b(?:refund|never\s+(?:delivered|received|came|arrived|sent)|not\s+(?:delivered|"
    r"received|arrived)|still\s+(?:waiting|haven'?t)|wrong\s+(?:item|order|colour|color|"
    r"size|product)|poor\s+quality|bad\s+quality|torn|broken|damaged|paid\s+(?:and|but)|"
    r"my\s+money|no\s+one\s+(?:replied|answered)|never\s+(?:replied|answered)|"
    r"weeks?\s+(?:ago|now)|months?\s+(?:ago|now)|sijapokea|haijafika|hela\s+yangu|"
    r"pesa\s+yangu)\b",
    re.IGNORECASE,
)


def looks_request(text: str) -> bool:
    """A comment asking us to SHOW or SEND something (designs, photos, the
    catalogue, prices, options) — answered with what the hub has for it."""
    return bool(_REQUEST_RE.search((text or "").strip()))


def looks_praise(text: str) -> bool:
    return bool(_PRAISE_RE.search((text or "").strip()))


def grade_complaint(text: str) -> int:
    """The weight of a grievance, 1–3, from its own words: 3 grave (a scam or
    fraud accusation, a threat to report, abuse), 2 serious (an order gone
    wrong, money paid, nothing received, poor quality, weeks of waiting),
    1 mild (a correction, a disappointment). Never 0 for a complaint."""
    t = (text or "").strip()
    if not t:
        return 1
    if _GRAVE_RE.search(t):
        return 3
    if _SERIOUS_RE.search(t):
        return 2
    return 1


def request_ask(text: str, ask: str = "") -> str:
    """What they asked for, in their own words, short enough for a reply:
    the model's phrase when it gave one, else the comment itself trimmed of
    its politeness ("Share more designs for ladies, interested." → "more
    designs for ladies")."""
    a = " ".join((ask or "").split()).strip(" .,;:!\"'")
    if a and a != "-":
        return a[:80]
    t = " ".join((text or "").split())
    t = re.sub(r"\b(?:please|pls|plz|kindly|tafadhali|interested|thanks?|thank\s+you|asante)\b",
               " ", t, flags=re.IGNORECASE)
    t = re.sub(r"^(?:share|send|show|post|upload|give|bring|tuma|tutumie|onyesha|weka)\s+",
               "", t.strip(), flags=re.IGNORECASE)
    t = " ".join(t.split()).strip(" .,;:!\"'")
    return (t[:80] or "what you asked for").lower() if t else "what you asked for"


# A person CHEERING US ON. "We can't wait to have you Bethany in Zambia" was
# answered with "So sorry to hear this — a member of our team will reach out to
# make it right" and a complaint ticket (2026-09-03): the classifier's model
# is told to lean negative on anything wait-shaped, and this had "wait" in it.
# Anticipation, welcome, congratulation and blessing are the warmest things
# that happen under a post — and under an expansion post they are the whole
# point. Read deterministically, ahead of the model, ahead of the negative
# guard; a grievance cue in the same breath ("can't wait any longer, where is
# my order?") hands it back to the ordinary path.
_GOODWILL_RE = re.compile(
    r"(?:^|\b)("
    r"can'?t\s+wait|cannot\s+wait|looking\s+forward|"
    r"welcome|karibu(?:ni)?|see\s+you\s+(?:soon|there|in\b)|"
    r"congrat(?:s|ulations?)|hongera|god\s+bless|blessings|"
    r"(?:so\s+)?proud\s+of\s+you|well\s+done|all\s+the\s+best|"
    r"safe\s+(?:travels?|journey|flight|trip)|"
    r"we\s+love\s+you|much\s+love|"
    r"waiting\s+for\s+you\s+(?:in|here|to\s+(?:come|arrive|visit|open))"
    r")(?:$|\b)",
    re.IGNORECASE,
)
_GRIEVANCE_CUE_RE = re.compile(
    r"\b(order|refund|deliver(?:y|ed)?|received?|repl(?:y|ied)|answer(?:ed)?|"
    r"paid|payment|money|scam|wrong|fake|cheat(?:ed)?|complain(?:t|ed)?)\b",
    re.IGNORECASE,
)


def looks_goodwill(text: str) -> bool:
    """True when a comment is a person cheering us on — anticipation ("can't
    wait to have you"), a welcome, congratulations, a blessing — and NOT a
    grievance wearing those words. Never a complaint, never a sales lead."""
    t = (text or "").strip()
    return bool(_GOODWILL_RE.search(t)) and not _GRIEVANCE_CUE_RE.search(t)


def _reading(intent: str, kind: str = "other", severity: int = 0, ask: str = "") -> dict:
    return {"intent": intent, "kind": kind, "severity": int(severity), "ask": ask}


_READING_RE = re.compile(
    r"intent\s*=\s*(?P<intent>[a-z]+)|kind\s*=\s*(?P<kind>[a-z]+)|"
    r"severity\s*=\s*(?P<severity>[0-3])|ask\s*=\s*(?P<ask>[^|\n]*)",
    re.IGNORECASE,
)


def parse_comment_reading(text: str) -> dict | None:
    """The light model's one line — `intent=high | kind=request | severity=0 |
    ask=more designs for ladies` — as a reading; a bare label ("high") is an
    intent with nothing else; anything unreadable is None."""
    t = (text or "").strip()
    if not t:
        return None
    found: dict = {}
    for m in _READING_RE.finditer(t):
        for k, v in m.groupdict().items():
            if v is not None and k not in found:
                found[k] = v.strip()
    if "intent" not in found:
        word = t.lower().split(" ")[0].strip(".,!\"'")
        return _reading(word) if word in _INTENTS else None
    intent = found["intent"].lower()
    if intent not in _INTENTS:
        return None
    kind = found.get("kind", "other").lower()
    kind = kind if kind in _KINDS else "other"
    try:
        severity = int(found.get("severity") or 0)
    except ValueError:
        severity = 0
    ask = found.get("ask", "").strip(" .\"'")
    return _reading(intent, kind, max(0, min(severity, 3)), "" if ask == "-" else ask)


def _settle_reading(text: str, r: dict) -> dict:
    """The reading with the deterministic readers laid over it: a grievance is
    a complaint with a grade never below its own words; kind words beside a
    grievance make it mixed; a request shape is a request even when the model
    called it a question; a request always carries its ask."""
    r = dict(r)
    if r["intent"] == "negative":
        r["kind"] = "mixed" if (r["kind"] == "mixed" or looks_praise(text)) else "complaint"
        r["severity"] = max(int(r.get("severity") or 0), grade_complaint(text))
    elif r["kind"] in ("complaint", "mixed"):
        r["intent"] = "negative"
        r["severity"] = max(int(r.get("severity") or 0), grade_complaint(text))
    else:
        r["severity"] = 0
        if r["kind"] in ("other", "question") and looks_request(text):
            r["kind"] = "request"
        if r["intent"] == "goodwill" and r["kind"] in ("other", "question"):
            r["kind"] = "praise"
        # A short cheer ("Awesome 👍", "beautiful work", "❤️") is praise even
        # with no model to say so: thanked, never handed to a person.
        words = re.findall(r"[a-zA-Z']+", text or "")
        if r["kind"] == "other" and r["intent"] in ("high", "low") \
                and not _QUESTION_MARK_RE.search(text or "") \
                and (not words or (len(words) <= 6 and looks_praise(text))):
            r["kind"], r["intent"] = "praise", "low"
    if r["kind"] == "request":
        r["ask"] = request_ask(text, r.get("ask", ""))
        if r["intent"] in ("low", "spam"):
            r["intent"] = "high"          # a request is answered, never thanked away
    else:
        r["ask"] = "" if r["kind"] != "question" else (r.get("ask") or "")
    return r


async def _private_complaint_message(cid: str, page_id, channel: str, name_tag: str,
                                     swahili: bool = False) -> bool:
    """The private message that follows a serious or grave complaint — the
    details come privately, a person takes it up. True when it went; a
    failure is logged and the public line then makes no claim of it."""
    from app.services.meta_send import send_private_reply
    try:
        await send_private_reply(
            cid, (_SW_PRIVATE_COMPLAINT if swahili else _PRIVATE_COMPLAINT).replace("{name}", name_tag),
            page_id=page_id, channel=channel)
        return True
    except Exception as exc:
        _log.warning("private message for complaint %s not delivered: %s", cid, exc)
        return False


def empathy_text(kind: str, severity: int, swahili: bool = False,
                 private_sent: bool = False) -> str:
    """The public line for a grievance, by its weight (owner, 2026-09-22):
    mild — taken seriously, a person will speak with them; serious — an
    apology, a colleague now, the private message when it went; grave — the
    same with more weight. A MIXED comment of mild weight thanks first. The
    `{name}` stays for the caller."""
    sev = max(1, min(int(severity or 1), 3))
    if sev >= 3:
        line = _SW_EMPATHY_GRAVE if swahili else _EMPATHY_GRAVE
        tail = (_SW_PRIVATE_SENT_GRAVE if swahili else _PRIVATE_SENT_GRAVE) if private_sent else ""
        return line.replace("{private}", tail)
    if sev == 2:
        line = _SW_EMPATHY_SERIOUS if swahili else _EMPATHY_SERIOUS
        tail = (_SW_PRIVATE_SENT if swahili else _PRIVATE_SENT) if private_sent else ""
        return line.replace("{private}", tail)
    if kind == "mixed":
        return _SW_EMPATHY_MIXED if swahili else _EMPATHY_MIXED
    return _SW_PUBLIC_EMPATHY if swahili else _PUBLIC_EMPATHY


def _thread_parent_context(parent: dict | None) -> str:
    """The model's line for a REPLY inside a thread (owner, 2026-09-23): the
    comment it answers and what we said there. 'In Kenya shillings' under
    'How much is it?' — '$40' is that item in KES, never another item."""
    p = parent or {}
    said = " ".join(str(p.get("text") or "").split())[:300]
    if not said:
        return ""
    who = str(p.get("by") or "").strip() or "another commenter"
    ours = " ".join(str(p.get("our_reply") or "").split())[:400]
    line = (f'(This comment is a REPLY inside a thread, under {who}\'s comment "{said}"')
    if ours:
        line += f' — which we answered: "{ours}"'
    line += (". Their words continue THAT exchange: a currency, a colour, a size or "
             "\"how much\" refers to the item quoted there — \"in Kenya shillings\" after a "
             "dollar quote is the SAME item re-priced in KES (search_catalog it with "
             "currency KES), never another item. The post's product stays what it is.)")
    return line


async def _thread_parent(parent_id: str) -> dict:
    """The comment a reply answers, and our reply to it, from our own inbox
    (every comment is captured with its id as `waba_msg_id`; our public
    replies carry `comment_context.reply_to`). {} when unknown."""
    pid = (parent_id or "").strip()
    if not pid:
        return {}
    try:
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            parent = (await db.execute(
                select(Message).where(Message.waba_msg_id == pid)
                .order_by(Message.created_at.desc()).limit(1))).scalars().first()
            if parent is None:
                return {}
            ours = (await db.execute(
                select(Message).where(
                    Message.direction == MsgDirection.outbound,
                    Message.comment_context["reply_to"].astext == pid)
                .order_by(Message.created_at.desc()).limit(1))).scalars().first()
            return {"text": parent.text or "", "by": parent.name or "",
                    "our_reply": (ours.text if ours is not None else "") or ""}
    except Exception as exc:
        _log.info("thread parent %s not read: %s", pid, exc)
        return {}


def _reading_context(reading: dict | None) -> str:
    """The model's line about what this comment IS (owner, 2026-09-22) — so a
    request is answered with the shelf, a question with the answer, praise
    in kind, a greeting with a greeting. "" when there is nothing to say."""
    r = reading or {}
    kind = str(r.get("kind") or "other")
    ask = str(r.get("ask") or "").strip()
    if kind == "request":
        return ("(Reading: this comment is a REQUEST — they want: "
                f"{ask or 'to be shown what we have'}. Answer it with what we have for it "
                "from the hub: search_catalog it, give the two or three closest items with "
                "their prices, and say you have sent photos to their inbox. Never a bare "
                "'send us a message'.)")
    if kind == "question":
        return ("(Reading: this comment is a QUESTION"
                + (f" — {ask}" if ask else "")
                + ". Answer it first, briefly and exactly; add a price only if it is "
                "relevant to the question.)")
    if kind == "praise":
        return ("(Reading: this comment is PRAISE. Thank them warmly, in kind and in their "
                "words; no price and no pitch unless they ask for one.)")
    if kind == "greeting":
        return ("(Reading: this comment is a GREETING. Greet them warmly back, in their "
                "language, and connect them to the post's item in the same breath.)")
    if kind == "mixed":
        return ("(Reading: this comment is MIXED — kind words and a grievance, severity "
                f"{int(r.get('severity') or 1)}/3. Thank them first, then take the grievance "
                "seriously in one humble line; no price, no pitch; a colleague has been told.)")
    return ""


async def read_comment(text: str, redis=None) -> dict:
    """READ THE INTENT, GRADE IT (owner, 2026-09-22). One reading of a public
    comment: `intent` — the plan's key (high / low / negative / goodwill /
    spam, exactly as before); `kind` — what it IS: a request (show or send us
    something), a question, a complaint, praise, a mixed comment (kind words
    and a grievance), a greeting, or other; `severity` — a complaint's weight
    1–3; `ask` — what a request wants, in a few words.

    The deterministic readers go first and hold on every path (cheering,
    displeasure, a greeting, a request shape, the grade of a grievance), then
    one cheap light-model line fills the rest. Errs toward engaging on
    uncertainty — better to help than go silent — and an empty comment is
    low. A model outage never loses the reading: the readers still say a
    request is a request and a scam accusation is grave."""
    t = (text or "").strip()
    if not t:
        return _reading("low", "other")
    # Cheering us on is read FIRST: "we can't wait to have you in Zambia" has
    # the word "wait" in it, and a model told to lean negative on anything
    # wait-shaped answered it with an apology and a complaint ticket.
    if looks_goodwill(t):
        return _settle_reading(t, _reading("goodwill", "praise"))
    # Plain displeasure never goes to the model — and never becomes a sales pitch.
    if looks_negative(t):
        return _settle_reading(t, _reading("negative", "complaint"))
    # A hello is a door opening, not praise — engage, never the canned thanks.
    if looks_greeting(t):
        return _settle_reading(t, _reading("high", "greeting"))
    # Past the daily spend stop, even this light call waits for midnight: fall
    # to the same default the except-arm uses. "high" then flows into run_turn
    # (which refuses for free) and lands on the canned pools — so under a
    # budget stop the comment funnel keeps answering at exactly $0.
    try:
        from app.services import ai_budget
        if redis is not None and await ai_budget.mode(redis) == "stop":
            return _settle_reading(t, _reading("high", "other"))
    except Exception:
        pass
    prompt = (
        "Read this public comment on a Christian clergy/communion store's post and "
        "answer on ONE line in exactly this shape:\n"
        "intent=<high|low|negative|goodwill|spam> | kind=<request|question|complaint|"
        "praise|mixed|greeting|other> | severity=<0-3> | ask=<what they want, in a "
        "few words, or ->\n\n"
        "intent — one of high, low, negative, goodwill, or spam:\n"
        "- high: buying interest OR any genuine question — price, availability, sizes, "
        "how to order, where you are located, delivery, opening hours, 'I want this' — "
        "and any REQUEST to be shown or sent something\n"
        "- low: praise, emoji, tagging a friend, 'amen', generic positivity, no question. "
        "A GREETING ('how are you', 'habari', 'bonjour') is NOT low — it is a person "
        "opening a conversation: answer high\n"
        "- negative: ANY dissatisfaction, correction, doubt or grievance — a complaint, "
        "anger, an unresolved order, criticism of us or of the post, or a claim that "
        "something is wrong/untrue. Short ones count: 'this is wrong', 'not true', "
        "'poor quality', 'still waiting', 'you never replied'. If a comment could be "
        "read as either a question OR displeasure, answer negative — a pitch sent to "
        "an unhappy person in public is far costlier than a careful reply.\n"
        "- goodwill: a person CHEERING US ON — 'we can't wait to have you in Zambia', "
        "'welcome', 'congratulations', 'see you soon', 'God bless you', 'safe "
        "travels'. This is NOT negative even when it contains the word 'wait': "
        "anticipation is the warmest thing under a post. A bare 'amen' or emoji "
        "stays low; a sentence addressed to us is goodwill\n"
        "- spam: ONLY bots, ads, promotional links, or abuse\n"
        "kind — what the comment IS:\n"
        "- request: they want something shown, sent or offered ('share more designs "
        "for ladies', 'send the catalogue', 'post prices', 'more photos')\n"
        "- question: they ask something (price, delivery, sizes, where, how)\n"
        "- complaint: a grievance, correction or dissatisfaction\n"
        "- praise: kind words, thanks, a blessing\n"
        "- mixed: kind words AND a grievance in one breath ('beautiful work, but my "
        "order never came')\n"
        "- greeting: a hello\n"
        "- other: none of these\n"
        "severity — the weight of a complaint or mixed comment, else 0: 1 a "
        "correction or a small disappointment; 2 an order gone wrong (not delivered, "
        "wrong item, paid and nothing came, poor quality, weeks of waiting); 3 grave "
        "(a scam or fraud accusation, a threat to report or expose, abuse).\n"
        "ask — for a request or a question, what they want in a few words ('more "
        "designs for ladies', 'delivery to Uganda'); otherwise -\n"
        "Comments come in many languages (French, Swahili, Sheng, Chinese, Dutch…). "
        "A comment you don't understand is NOT spam: if it asks anything, answer "
        "'high'; if it's short and friendly or just a person's name, answer 'low'. "
        "Never answer 'spam' merely because it isn't English.\n"
        f'Comment: "{t[:300]}"\n'
        "Answer with the one line only."
    )
    try:
        llm = build_llm(model=settings.tier2_model_light)
        resp = await llm.complete(system="You read comments precisely. One line only, in the shape asked.",
                                  messages=[{"role": "user", "content": prompt}], tools=[])
        r = parse_comment_reading(resp.text or "")
        if r is None:
            r = _reading("high", "other")
        return _settle_reading(t, r)
    except Exception:
        return _settle_reading(t, _reading("high", "other"))


async def classify_comment_intent(text: str, redis=None) -> str:
    """The plan's key for a public comment — the `intent` of `read_comment`
    (high / low / negative / goodwill / spam). Kept as the name every caller
    and test knows; the full reading (kind, severity, ask) is `read_comment`."""
    return (await read_comment(text, redis=redis))["intent"]


def plan_comment_actions(intent: str) -> dict:
    """Map a comment intent to Neema's response plan.
    high → brief public answer + open a DM · low → light public thanks only ·
    goodwill → a real, personal public reply (the model, post in hand), no DM ·
    negative → empathetic public line + route to a human, no auto-sell ·
    spam → do nothing."""
    if intent == "spam":
        return {"public": False, "style": None, "dm": False, "human": False}
    if intent == "negative":
        return {"public": True, "style": "empathy", "dm": False, "human": True}
    if intent == "low":
        return {"public": True, "style": "light", "dm": False, "human": False}
    if intent == "goodwill":
        # Answered by the model, in public, with the post in hand — but no DM:
        # nobody who wrote "welcome to Zambia" asked to be sold to in their
        # inbox. (The DM still opens when the post sells a product — see
        # _run_comment_engage — because then the link IS the answer.)
        return {"public": True, "style": "answer", "dm": False, "human": False}
    return {"public": True, "style": "answer", "dm": True, "human": False}   # high


_SEVERITY_WORDS = {1: "mild", 2: "serious", 3: "grave"}


def _human_note(kind: str, severity: int, comment: str = "", ask: str = "",
                answered: str = "") -> str:
    """The team's note — what this is, how heavy, what they said, what Neema
    did. The kind decides the ask of the colleague: a graded COMPLAINT to
    follow up and close (today, when serious; at once, when grave); a REQUEST
    or QUESTION Neema could not answer in the thread, to answer right there."""
    said = " ".join((comment or "").split())[:300]
    lines = []
    if kind in ("complaint", "mixed"):
        sev = max(1, min(int(severity or 1), 3))
        label = "MIXED — kind words and a grievance" if kind == "mixed" else "COMPLAINT"
        urgency = {1: "a colleague must follow up and close this",
                   2: "SERIOUS — a colleague must take this up TODAY and close it",
                   3: "GRAVE / URGENT — a colleague must take this up NOW, personally"}[sev]
        lines.append(f"{label} (public comment) — severity {sev}/3 ({_SEVERITY_WORDS[sev]}): {urgency}.")
        if said:
            lines.append(f'• Their comment: "{said}"')
        lines.append("• Answered publicly with an apology only — no price, no pitch."
                     + (" A private message was opened so the details come privately." if sev >= 2 else ""))
        lines.append("• Neema stays available in the thread for factual questions.")
    elif kind == "request":
        lines.append("REQUEST (public comment) — they asked us to show or send something, and "
                     "Neema could not answer it in the thread (no model): a colleague must "
                     "answer them RIGHT THERE in the thread, with what we have.")
        if ask:
            lines.append(f"• They want: {ask}")
        if said:
            lines.append(f'• Their comment: "{said}"')
        if answered:
            lines.append(f'• Neema said: "{answered}"')
    elif kind == "question":
        lines.append("QUESTION (public comment) — Neema could not answer it in the thread (no "
                     "model): a colleague must answer them RIGHT THERE in the thread.")
        if said:
            lines.append(f'• Their comment: "{said}"')
        if answered:
            lines.append(f'• Neema said: "{answered}"')
    else:
        lines.append("PUBLIC COMMENT Neema could not read or answer (no model): a colleague "
                     "must look and reply in the thread.")
        if said:
            lines.append(f'• Their comment: "{said}"')
        if answered:
            lines.append(f'• Neema said: "{answered}"')
    return "\n".join(lines)


async def _route_comment_to_human(channel: str, external_id: str,
                                  comment: str = "", *, kind: str = "complaint",
                                  severity: int = 1, ask: str = "", answered: str = "",
                                  redis=None) -> None:
    """Hand a commenter to the team — WITHOUT muting Neema — with the reading:
    what it is (a complaint, mixed, a request, a question) and how heavy.

    This used to set intercept_mode=human, which stopped the agent replying at
    all and also dropped the thread out of the missed-reply sweeper (it only
    picks up intercept_mode=ai). So a public complaint got one apology and then
    silence until someone opened the dashboard. The team is still brought in and
    still has the final word — they just aren't the customer's only hope of a
    reply in the meantime. A serious or grave complaint (severity ≥ 2) is an
    ESCALATION: the bell rings for the team and the thread shows the pill
    (services/conversation.record_escalation); everything else is a flag."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation
    from app.models.intercept import Intercept, InterceptAction
    note = _human_note(kind, severity, comment, ask=ask, answered=answered)
    async with AsyncSessionLocal() as db:
        conv = (await db.execute(select(Conversation).where(
            Conversation.channel == channel,
            Conversation.external_id == external_id))).scalar_one_or_none()
        if conv is None:
            return
        if kind in ("complaint", "mixed") and int(severity or 1) >= 2:
            from app.services.conversation import record_escalation
            await record_escalation(db, conv.id, note, redis=redis)
            return
        db.add(Intercept(conversation_id=conv.id, action=InterceptAction.flag, note=note))
        await db.commit()


async def _note_silent_decision(channel: str, ext: str, cid: str, intent: str) -> None:
    """Record an operator-visible internal NOTE when Neema deliberately says nothing,
    so silence is a decision a human can see and overrule — not a black hole that
    looks identical to a crash. Written as media_type="note" (rendered as an internal
    note, excluded from previews + unread counts), never broadcast: the live socket
    payload carries no isNote flag, so a pushed note would render as a real reply."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation
    from app.models.message import Message, MsgDirection, MsgSender
    try:
        async with AsyncSessionLocal() as db:
            conv = (await db.execute(select(Conversation).where(
                Conversation.channel == channel,
                Conversation.external_id == ext))).scalar_one_or_none()
            if conv is None:
                return
            db.add(Message(
                channel=channel, external_id=ext, wa_id=None,
                person_id=conv.person_id, conversation_id=conv.id,
                direction=MsgDirection.outbound, sender=MsgSender.ai,
                text=(f"🤖 Neema did not reply to this comment — classified “{intent}”. "
                      "Reply here if it deserves an answer."),
                media_type="note",
            ))
            await db.commit()
    except Exception as exc:
        _log.warning("silent-decision note failed for %s: %s", cid, exc)


# Varied warm lines so a viral post's replies don't read identically. Picked
# deterministically by the commenter id — same person, stable line; different
# people, different lines.
_QUESTION_HINTS = ("?", "how much", "how many", "price", "cost", "bei", "gani",
                   "combien", "quanto", "where", "wapi", "do you", "can i", "is it")


def _looks_like_a_question(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(h in t for h in _QUESTION_HINTS)


def _mentions_catalogue_item(text: str) -> bool:
    """Does the comment actually NAME something we sell?

    The point is only to tell "how much is the Tallit?" (answerable: they named
    it) from "how much?" (not answerable during a broadcast, because the camera
    has shown twenty things).

    Matched on WHOLE words — plus a plural "s" — never as a substring. Held as
    a substring, "across" was a cross, "hosting" was a Host, "facebook" was a
    book and "Bring the price" named a ring; the first of those is the very
    shape of comment that opened this bug ("Watching from Liberia").

    The bias is deliberate: a miss costs a friendly "which one?", while a false
    match costs an arriving viewer a sales reply where a welcome belonged.
    """
    # "the pendant" names our Pectoral Cross (core/synonyms) — read it so.
    return bool(_CATALOGUE_RE.search(_canonical(text or "")))


# The vocabulary of the shop. Not the catalogue itself: this runs on every live
# comment and must not hit the DB, and a broadcast's questions use everyday
# words ("shawl", "cassock") rather than exact product names.
_CATALOGUE_WORDS = (
    "tallit", "talliet", "tallits", "shawl", "prayer shawl",
    "cassock", "cossack", "gown", "robe", "vestment", "chasuble", "cope", "mitre", "mitres",
    "stole", "surplice", "alb", "clergy", "collar", "cincture", "belt", "shirt",
    "communion", "chalice", "paten", "cup", "cups", "wafer", "bread", "host",
    "tray", "burner", "incense", "thurible", "candle", "cross", "crozier", "staff",
    "bible", "book", "stories", "banner", "cloth", "kitambaa", "skull cap", "zucchetto",
    "bag", "shoe", "shoes", "ring", "pectoral", "bell", "offering", "basket",
)

# Whole words, optional plural, compiled once — this runs on every live comment.
_CATALOGUE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _CATALOGUE_WORDS) + r")s?\b",
    re.IGNORECASE,
)

# When a live viewer asks a price without naming the item. The camera has shown
# many things — guessing is how a vestment stream quoted a children's book.
_LIVE_WHICH_POOL = [
    "Which item are you asking about{name}? 🙏 Tell me and I'll give you the price right away 💛",
    "Which one caught your eye{name}? 🙏 Name it and I'll share the price 💛",
    "Of course{name} 🙏 Which piece do you mean? Tell me which and I'll give you the price and take your order 💛",
]

# A live viewer saying "watching from Liberia" is arriving, not shopping. The
# owner's words: "When I go live, I expect you to welcome people in." These are
# warm, varied, and sell NOTHING — the broadcast itself is the pitch.
_LIVE_WELCOME_POOL = [
    "Welcome{name} 🙏 So glad you could join us live — make yourself at home! 💛",
    "A warm welcome{name} 🙏 Lovely to have you with us today 💛",
    "Bless you for joining{name} 🙏 Enjoy the show — ask us anything as we go! 💛",
    "Welcome in{name}! 🙏 Great to see you here with us 💛",
    "So good to have you{name} 🙏 Watch along and say hello anytime 💛",
]

_THANKS_POOL = [
    "Amen{name} 🙏 Thank you so much — God bless you! 💛",
    "Bless you{name} 🙏 We're so glad this speaks to you! 💛",
    "Thank you{name}! 🙏 Your kind words mean the world to us 💛",
    "Thank you kindly{name} 🙏 May God bless you abundantly 💛",
    "So grateful{name} 🙏 Glory to God! 💛",
]
# (The "DM nudge" and "comment invite" pools that once followed an answered
# comment were retired on 2026-08-10 — the thread IS the shop, an answered
# comment stands alone — and removed on 2026-09-22: nothing read them, and a
# residue that says "send us a message" is a residue waiting to be used.)
# Said to a buying comment when the agent could not run (over the per-post cap,
# or the turn failed) but we DO know from the post WHAT they're looking at. "How
# to order" is the highest-intent comment we get, so it gets a real, warm,
# link-free answer with no model call: name the item, invite them to the inbox.
# `{product}` is "the Aluminium Tray" when we identified it, else "it".
_OVER_CAP_POOL = [
    "Thank you{name} 🙏 Yes, {product} is available — send us a message and we'll share the price and get you sorted 💛",
    "Bless you{name}! 🙏 We do have {product} — DM us and we'll take care of the details and delivery 💛",
    "We'd love to help{name} 🙏 {product} is in — send us a message and we'll sort out size, colour and delivery 💛",
    "Welcome{name} 🙏 Yes, we have {product} — message us and we'll handle the price and delivery from there 💛",
]
# Over-cap AND we know the post's product WITH its price (from the post's
# recorded identity): the no-LLM line still SELLS — price + one pull question —
# instead of deflecting to the inbox. The owner's law is the comment thread is
# the shop; running out of model budget must not turn it back into a signpost.
#
# ONE PIECE IS THE DEFAULT (owner, 2026-09-05): "many people want a piece. We
# should not ask how many do you want. We should make sales." And the pull is
# the ORDER (owner, 2026-09-15): "Kindly make your order, let us know how many
# you need and the colour too. How soon do you want the shirt?" — never a
# question that only keeps the chat going. `{product}` is
# the item AS SEEN in the post when our records describe it ("the green
# chasuble with the African-print stole and gold piping"), else its name;
# `{price}` carries the USD figure for outside Kenya beside the KES home price.
_OVER_CAP_SELL_POOL = [
    "Thank you{name} 🙏 {product} is {price}, and we ship worldwide by DHL. Kindly place your order — tell us the colour and how many you need. How soon do you want it? 💛",
    "Thank you{name} 🙏 {product} is {price}, made in our Nairobi workshop and delivered anywhere by DHL. Kindly place your order — tell us the colour and how many you need. How soon would you like it? 💛",
    "Bless you{name}! 🙏 {product} is {price}, and we deliver worldwide by DHL. Kindly place your order — let us know the colour and how many you need. How soon would you like it? 💛",
    "We'd love to serve you{name} 🙏 {product} is {price}, delivered anywhere by DHL. Kindly place your order — the colour and how many you need. When do you want it by? 💛",
]
# A person's FIRST comment to us — the owner's welcome shape: welcome them by
# name, name what they are looking at, the price, one step. No re-welcome for
# anyone we have answered before.
_FIRST_SELL_POOL = [
    "Welcome to Bethany House{name} 🙏 {product} is {price}, and we ship worldwide by DHL. Kindly place your order — tell us the colour and how many you need. How soon do you want it? 💛",
    "Welcome to Bethany House{name} 🙏 {product} is {price}, made in our Nairobi workshop and delivered anywhere by DHL. Kindly place your order — tell us the colour and how many you need. How soon would you like it? 💛",
    "Welcome{name}, we're glad you found us 🙏 {product} is {price}, and we deliver worldwide by DHL. Kindly place your order — let us know the colour and how many you need. How soon would you like it? 💛",
]
# A STOCK item (a tray, a chalice, a tallit — `made_to_order` false in the hub)
# has its colour in its name and its contents in its description: nothing to
# ask but how many, where to and how soon (owner, 2026-09-15: "we have all
# this information, which we do not need to ask"). The pools above are the
# made-to-order shape, where the colour IS the customer's to choose.
_STOCK_SELL_POOL = [
    "Thank you{name} 🙏 {product} is {price}, and we ship worldwide by DHL. Kindly place your order — tell us how many you need and your city. How soon do you want it? 💛",
    "Thank you{name} 🙏 {product} is {price}, from our Nairobi shop and delivered anywhere by DHL. Kindly place your order — how many you need and your city. How soon would you like it? 💛",
    "Bless you{name}! 🙏 {product} is {price}, and we deliver worldwide by DHL. Kindly place your order — let us know how many you need and where to deliver. When do you want it by? 💛",
]
_STOCK_FIRST_SELL_POOL = [
    "Welcome to Bethany House{name} 🙏 {product} is {price}, and we ship worldwide by DHL. Kindly place your order — tell us how many you need and your city. How soon do you want it? 💛",
    "Welcome to Bethany House{name} 🙏 {product} is {price}, from our Nairobi shop and delivered anywhere by DHL. Kindly place your order — how many you need and your city. How soon would you like it? 💛",
]
# Goods bought in numbers (cups, hosts, wafers — the per-piece rows): here
# "how many?" IS the sale, and the price is per piece.
_OVER_CAP_SELL_EACH_POOL = [
    "Thank you{name} 🙏 {product} is {price} each, and we ship worldwide by DHL. How many do you need? 💛",
    "Thank you{name} 🙏 {product} is {price} each, ready for you. Kindly place your order — how many shall we prepare, and how soon? 💛",
    "Bless you{name}! 🙏 {product} is {price} each, delivered anywhere by DHL. How many would you like? 💛",
]
# Said when we could not compose a real answer (over the per-post cap, or the
# agent turn failed) AND we could not identify a product. It must be safe to send
# to ANYONE — a buyer, a critic, someone grieving — so it thanks, opens a door,
# and sells nothing at all.
# No cheerful emoji here (a 🙏 reads as humble; a 💛 reads as cheer) — this
# line may land on a complaint, and the mood rules forbid cheer on displeasure.
# Owner, 2026-09-22 (Queen Gili: "Please more designs for ladies" answered
# with "Send us a message and we'll help however we can"): the thread is the
# shop, so this line never sends anyone away — it promises a person, and the
# engine hands the team the comment to answer right there.
_NEUTRAL_ACK_POOL = [
    "Thank you for reaching out{name} 🙏 One of our team will come back to you right here shortly.",
    "We appreciate you{name} 🙏 A colleague will pick this up with you here shortly.",
    "Thank you{name} 🙏 We're here — one of us will reply to you right here shortly.",
]
# Over the per-post cap (or the turn failed) on a GOODWILL comment — the line a
# host gives when the room is full. Never the neutral "tell us a little more",
# which reads as a form handed to someone who just said "welcome". No promise,
# no year, no pitch: those need the post in hand, and only the model has it.
_GOODWILL_POOL = [
    "Thank you{name} 🙏 A welcome like yours means the world to us.",
    "Bless you{name} 🙏 Kind words like these carry us a long way.",
    "Thank you{name} 🙏 It's an honour to be cheered on like this.",
    "Thank you so much{name} 🙏 We're so grateful for your warmth.",
    "Thank you{name} 🙏 We felt that — and we're so glad you're with us.",
]


# ── Kiswahili sanifu (owner, 2026-09-15): when THEY wrote Swahili, the canned
# line is Swahili — standard and official, the hub's name for the item kept
# exactly as the hub writes it, and the pull is the order. No Sheng, no
# English verbs dressed as Swahili, one question each. `{product}` is the
# bare hub name ("Round Collar Shirt ni KES 4,500").
_SW_LIVE_WHICH_POOL = [
    "Ni bidhaa ipi unayouliza{name}? 🙏 Niambie na nitakupa bei mara moja 💛",
    "Ni ipi iliyokuvutia{name}? 🙏 Itaje na nitakupa bei na kuchukua oda yako 💛",
]
_SW_LIVE_WELCOME_POOL = [
    "Karibu{name} 🙏 Tunafurahi umejiunga nasi — jisikie nyumbani! 💛",
    "Karibu sana{name} 🙏 Ni furaha kuwa nawe leo 💛",
    "Karibu{name}! 🙏 Tazama pamoja nasi na utusalimie wakati wowote 💛",
]
_SW_THANKS_POOL = [
    "Amina{name} 🙏 Asante sana — Mungu akubariki! 💛",
    "Asante{name}! 🙏 Maneno yako mazuri yanatutia moyo 💛",
    "Tunashukuru{name} 🙏 Utukufu kwa Mungu! 💛",
]
_SW_OVER_CAP_POOL = [
    "Asante{name} 🙏 Ndiyo, {product} inapatikana — tutumie ujumbe na tutakupa bei na kukuhudumia 💛",
    "Mungu akubariki{name}! 🙏 Tunayo {product} — tutumie ujumbe na tutashughulikia maelezo na usafirishaji 💛",
]
_SW_OVER_CAP_SELL_POOL = [
    "Asante{name} 🙏 {product} ni {price}, na tunasafirisha kote duniani kwa DHL. Tafadhali weka oda yako — tuambie rangi na idadi unayohitaji. Unaihitaji lini? 💛",
    "Asante{name} 🙏 {product} ni {price}, inatengenezwa katika karakana yetu Nairobi na kufikishwa popote kwa DHL. Tafadhali weka oda yako — tuambie rangi na idadi unayohitaji. Ungependa kuipata lini? 💛",
    "Mungu akubariki{name} 🙏 {product} ni {price}, na tunafikisha kote duniani kwa DHL. Tafadhali weka oda yako — rangi na idadi unayohitaji. Unaihitaji kufikia lini? 💛",
]
_SW_FIRST_SELL_POOL = [
    "Karibu Bethany House{name} 🙏 {product} ni {price}, na tunasafirisha kote duniani kwa DHL. Tafadhali weka oda yako — tuambie rangi na idadi unayohitaji. Unaihitaji lini? 💛",
    "Karibu Bethany House{name} 🙏 {product} ni {price}, inatengenezwa Nairobi na kufikishwa popote kwa DHL. Tafadhali weka oda yako — tuambie rangi na idadi unayohitaji. Ungependa kuipata lini? 💛",
]
_SW_STOCK_SELL_POOL = [
    "Asante{name} 🙏 {product} ni {price}, na tunasafirisha kote duniani kwa DHL. Tafadhali weka oda yako — tuambie idadi unayohitaji na mji wako. Unaihitaji lini? 💛",
    "Asante{name} 🙏 {product} ni {price}, kutoka duka letu Nairobi na kufikishwa popote kwa DHL. Tafadhali weka oda yako — idadi unayohitaji na mji wako. Ungependa kuipata lini? 💛",
]
_SW_STOCK_FIRST_SELL_POOL = [
    "Karibu Bethany House{name} 🙏 {product} ni {price}, na tunasafirisha kote duniani kwa DHL. Tafadhali weka oda yako — tuambie idadi unayohitaji na mji wako. Unaihitaji lini? 💛",
]
_SW_OVER_CAP_SELL_EACH_POOL = [
    "Asante{name} 🙏 {product} ni {price} kila kimoja, na tunasafirisha kote duniani kwa DHL. Tafadhali weka oda yako — unahitaji ngapi, na lini? 💛",
    "Karibu{name} 🙏 {product} ni {price} kila kimoja, tayari kwa ajili yako. Tafadhali weka oda yako — unahitaji ngapi, na unazihitaji lini? 💛",
]
_SW_NEUTRAL_ACK_POOL = [
    "Asante kwa kutufikia{name} 🙏 Mmoja wa timu yetu atakujibu hapa hivi karibuni.",
    "Asante{name} 🙏 Tuko hapa — mwenzetu atakujibu hapa hivi karibuni.",
]
_SW_GOODWILL_POOL = [
    "Asante{name} 🙏 Ukarimu wako unatutia nguvu sana.",
    "Mungu akubariki{name} 🙏 Maneno kama haya yanatupeleka mbali.",
]


# ── A SET IS PRICED AS ITS TOTAL (owner, 2026-09-21) ─────────────────────────
# "The explanation of the pricing for this cassock should include all the
# items listed there — the shirt and the collar, the cassock, the signature
# belt and the stole — so that you give the accurate figure from the hub …
# if we give just one item, people will misunderstand it to mean that that is
# the total amount of the entire set." And, the same day: "think wide and
# deeply, as the best linguist in business and closing the sales."
#
# The line a closer says, in the owner's spoken shape (2026-09-16): name it,
# then the figure WITH ITS SCOPE in the same breath ("goes for $200,
# everything included" — a bare figure under a set is read as one piece's),
# then what it comes with, the main piece first as "the" and the rest as "a"
# ("the cassock, a stole, a belt, a straight collar shirt and a 12 inch
# clergy collar"), "all in one order" (the hub's own promise), and ONE step:
# the order, with the two details the hub cannot answer. No question mark —
# the owner's sentence has none. `{product}` is the hub's bare name,
# `{items}` what it comes with, `{ask}` the details (the colour for a
# made-to-order set; how many sets for a stock one; how soon, always).
_SET_SELL_POOL = [
    "Thank you{name} 🙏 This is our {product}, and it goes for {price}, everything included. It comes with {items}. Kindly place your order now and let us know {ask} 💛",
    "Thank you{name} 🙏 This is our {product}, and the whole set goes for {price}. It comes with {items}, all in one order, and we ship worldwide by DHL. Kindly place your order now and let us know {ask} 💛",
    "Bless you{name}! 🙏 This is our {product}, and it goes for {price} for everything. It comes with {items}, all in one order. Kindly place your order now and let us know {ask} 💛",
]
_SET_FIRST_SELL_POOL = [
    "Welcome to Bethany House{name} 🙏 This is our {product}, and it goes for {price}, everything included. It comes with {items}. Kindly place your order now and let us know {ask} 💛",
    "Welcome to Bethany House{name} 🙏 This is our {product}, and the whole set goes for {price}. It comes with {items}, all in one order, and we ship worldwide by DHL. Kindly place your order now and let us know {ask} 💛",
]
# A combination with no hub set row: the total first (it answers "how much"),
# then every item with its own price, so the total is accounted for.
_BUNDLE_SELL_POOL = [
    "Thank you{name} 🙏 The whole set comes to {price}: {items}. Kindly place your order now and let us know {ask} 💛",
    "Thank you{name} 🙏 All of it together comes to {price} — {items} — and we ship worldwide by DHL. Kindly place your order now and let us know {ask} 💛",
]
_BUNDLE_FIRST_SELL_POOL = [
    "Welcome to Bethany House{name} 🙏 The whole set comes to {price}: {items}. Kindly place your order now and let us know {ask} 💛",
]
_SW_SET_SELL_POOL = [
    "Asante{name} 🙏 Hii ni {product} yetu, na seti kamili ni {price}. Inakuja na {items}, yote katika oda moja. Tafadhali weka oda yako sasa na utuambie {ask} 💛",
    "Asante{name} 🙏 Hii ni {product} yetu, na seti kamili ni {price}. Inakuja na {items}, yote katika oda moja, na tunasafirisha kote duniani kwa DHL. Tafadhali weka oda yako sasa na utuambie {ask} 💛",
]
_SW_SET_FIRST_SELL_POOL = [
    "Karibu Bethany House{name} 🙏 Hii ni {product} yetu, na seti kamili ni {price}. Inakuja na {items}, yote katika oda moja. Tafadhali weka oda yako sasa na utuambie {ask} 💛",
]
_SW_BUNDLE_SELL_POOL = [
    "Asante{name} 🙏 Seti nzima ni {price} kwa jumla: {items}. Tafadhali weka oda yako sasa na utuambie {ask} 💛",
]
_SW_BUNDLE_FIRST_SELL_POOL = [
    "Karibu Bethany House{name} 🙏 Seti nzima ni {price} kwa jumla: {items}. Tafadhali weka oda yako sasa na utuambie {ask} 💛",
]


def _set_ask(swahili: bool, made_to_order: bool, noun: str = "sets") -> str:
    """The two details a set line asks for, in the owner's cadence ("let us
    know how many trays you may need and how soon you want them delivered")
    — ASK ONLY WHAT THE HUB CANNOT ANSWER (owner, 2026-09-15): the colour
    for a made-to-order set; how many for a stock one; how soon, always.
    `noun` is the thing counted ("sets"); "" for a combination."""
    if swahili:
        if made_to_order:
            return "rangi unayohitaji na unaihitaji lini"
        return ("seti ngapi unazohitaji na unazihitaji lini" if noun == "sets"
                else "idadi unayohitaji na unaihitaji lini")
    if made_to_order:
        return "the colour you need and how soon you want it delivered"
    what = f"how many {noun} you may need" if noun else "how many you may need"
    return f"{what} and how soon you want them delivered"


def _join_and(parts: list, swahili: bool = False) -> str:
    parts = [str(p).strip() for p in parts if str(p).strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    joiner = " na " if swahili else " and "
    return ", ".join(parts[:-1]) + joiner + parts[-1]


def _with_article(part: str, definite: bool = False) -> str:
    """'cassock' → 'a cassock' (or 'the cassock' for the set's own main
    piece), '12 inch clergy collar' → 'a 12 inch clergy collar' (the hub's own
    wording); a part that brings its article keeps it."""
    low = part.lower()
    if low.startswith(("a ", "an ", "the ")):
        return part
    if definite:
        return "the " + part
    return ("an " if low[:1] in "aeiou" else "a ") + part


def _components_text(components: list, swahili: bool = False, set_name: str = "") -> str:
    """'the cassock, a stole, a belt, a straight collar shirt and a 12 inch
    clergy collar' — the hub's own words for what the set comes with. The
    piece the set is NAMED for ("Cassock Set" → the cassock) is "the": it is
    the thing they are looking at; the rest come with it."""
    comps = [str(c).strip() for c in (components or []) if str(c).strip()]
    if swahili:
        return _join_and(comps, swahili=True)
    name_toks = _caption_tokens(set_name or "")
    out = []
    for c in comps:
        ctoks = _caption_tokens(c)
        main = bool(ctoks) and bool(name_toks) and ctoks <= name_toks
        out.append(_with_article(c, definite=main))
    return _join_and(out)


def _bundle_items_text(rows: list, currency: str = "USD", swahili: bool = False) -> str:
    """'the Mitre at $60, the Cincture Rope at $20 and the Skull Cap at $20'
    — every item of a combination with its own hub price, so the total that
    follows is accounted for."""
    parts = []
    for r in rows or []:
        name = str(r.get("name") or "").strip()
        price = _public_price_text(r.get("price_kes") or r.get("price"), r.get("price_usd"), currency)
        if not name or not price:
            continue
        parts.append(f"{name} {price}" if swahili else f"the {name} at {price}")
    return _join_and(parts, swahili=swahili)


def _pick(pool: list, seed: str) -> str:
    import hashlib
    i = int(hashlib.sha1((seed or "x").encode()).hexdigest(), 16) % len(pool)
    return pool[i]


def _dm_text(answer: str, product_link: str, seed: str, swahili: bool = False) -> str:
    """The DM: the answer and THE product link — nothing after. The answer
    already ends on the order pull ("Kindly place your order now and let us
    know how many you need and how soon"), and a second line after it ("Tell
    me a little more and I'll sort you out") was a second, aimless ask that
    made the message read like a bot (owner, 2026-09-16). Links live here by
    design — Facebook suppresses the reach of posts and comments carrying
    external links, so the private message is where the storefront link
    travels. `seed` is kept for the callers' signature."""
    lead = "Agiza hapa" if swahili else "Order here"
    if not product_link:
        return answer.strip()
    return f"{answer.strip()}\n\n{lead} 👉 {product_link}"


def _comment_public_reply(answer: str, dm_sent: bool, name_tag: str, seed: str,
                          product_known: bool = False, product_name: str = "",
                          price_text: str = "", goodwill: bool = False,
                          per_piece: bool = False, first_contact: bool = False,
                          swahili: bool = False, made_to_order: bool = False,
                          ask_which: bool = False, set_items: str = "",
                          bundle: bool = False, kind: str = "other",
                          ask: str = "") -> str:
    """The PUBLIC comment text, given the agent's answer and whether the DM landed.

    THIS FUNCTION CANNOT PRODUCE A LINK, by construction: it takes no URL. Meta
    suppresses the reach of posts and comments carrying an external link, so the
    public square is link-free without exception — the storefront link rides the
    private reply instead (see `_dm_text`), and the comment does what a good
    shopkeeper does across a counter: answer, then invite them to talk.

    The earlier version kept a public link "for when the DM did not open, so a
    real buyer is never stranded". They are not stranded — they are invited to
    the inbox, and the whole post keeps its reach.

    2026-08-10 (owner): the comment thread IS the shop. When the agent answered,
    its text already sells and ends with its own next question — appending
    "DM us and we'll sort you out" under a selling reply reads as a brush-off
    and sends the buyer away from the very thread that is converting them. So
    an answered comment stands ALONE; the inbox-invite pools remain only for
    the no-answer fallbacks, where inviting a message is all we have."""
    if answer:
        return answer
    # No answer — we're over the per-post cap, or the agent turn failed. We do NOT
    # know what this person said, so we do NOT sell to them: pitching blind is how
    # "this is wrong" was answered with "Continue on WhatsApp to get yours". A
    # warm, content-free acknowledgement is always safe; the buying line is used
    # only when we DID identify what they're asking about.
    if goodwill:
        # We DO know what they said — they cheered us on. Warmth in kind, and
        # never the product line: "welcome to Zambia" is not a buying question.
        return _pick(_SW_GOODWILL_POOL if swahili else _GOODWILL_POOL, seed).replace("{name}", name_tag)
    if ask_which and not product_known:
        # A price question under a post we could NOT identify with confidence
        # (owner, 2026-09-21): ask which item — never price a guess. The same
        # line a live broadcast uses, for the same reason.
        return _pick(_SW_LIVE_WHICH_POOL if swahili else _LIVE_WHICH_POOL, seed).replace("{name}", name_tag)
    if kind == "request" and not (product_known and price_text):
        # A REQUEST we could not answer here (owner, 2026-09-22): their words
        # noted back, a person promised — never "send us a message".
        return (_pick(_SW_REQUEST_ACK_POOL if swahili else _REQUEST_ACK_POOL, seed)
                .replace("{name}", name_tag).replace("{ask}", (ask or "").strip() or "what you asked for"))
    if kind == "question" and not (product_known and price_text):
        return _pick(_SW_QUESTION_ACK_POOL if swahili else _QUESTION_ACK_POOL, seed).replace("{name}", name_tag)
    if product_known:
        # We know WHICH product the post is about, so a buying question still gets
        # a real, warm answer with no model call — with its PRICE when the post's
        # identity carries one, so even the over-cap line sells instead of
        # signposting the inbox.
        _pn = product_name.strip()
        # Swahili takes the hub's name bare ("Round Collar Shirt ni KES 4,500");
        # English says "the Round Collar Shirt".
        subject = (_pn or "bidhaa hii") if swahili else (f"the {_pn}" if _pn else "it")
        if price_text and set_items and _pn:
            # A SET IS PRICED AS ITS TOTAL (owner, 2026-09-21): the whole
            # set's price and what it comes with — never one piece's price
            # standing for the set.
            if swahili:
                pool = ((_SW_BUNDLE_FIRST_SELL_POOL if first_contact else _SW_BUNDLE_SELL_POOL) if bundle
                        else (_SW_SET_FIRST_SELL_POOL if first_contact else _SW_SET_SELL_POOL))
            else:
                pool = ((_BUNDLE_FIRST_SELL_POOL if first_contact else _BUNDLE_SELL_POOL) if bundle
                        else (_SET_FIRST_SELL_POOL if first_contact else _SET_SELL_POOL))
            return (_pick(pool, seed).replace("{name}", name_tag).replace("{product}", _pn)
                    .replace("{price}", price_text).replace("{items}", set_items)
                    .replace("{ask}", _set_ask(swahili, made_to_order, noun="" if bundle else "sets")))
        if price_text:
            # A per-piece good is sold by the count; anything else is ONE piece,
            # and a first-time commenter is welcomed the owner's way.
            # A per-piece good is sold by the count; a made-to-order item asks
            # its colour; a stock item never does — its details are the hub's
            # (ASK ONLY WHAT THE HUB CANNOT ANSWER, owner 2026-09-15).
            if swahili:
                if per_piece:
                    pool = _SW_OVER_CAP_SELL_EACH_POOL
                elif made_to_order:
                    pool = _SW_FIRST_SELL_POOL if first_contact else _SW_OVER_CAP_SELL_POOL
                else:
                    pool = _SW_STOCK_FIRST_SELL_POOL if first_contact else _SW_STOCK_SELL_POOL
            else:
                if per_piece:
                    pool = _OVER_CAP_SELL_EACH_POOL
                elif made_to_order:
                    pool = _FIRST_SELL_POOL if first_contact else _OVER_CAP_SELL_POOL
                else:
                    pool = _STOCK_FIRST_SELL_POOL if first_contact else _STOCK_SELL_POOL
            return (_pick(pool, seed).replace("{name}", name_tag)
                    .replace("{product}", subject).replace("{price}", price_text))
        return (_pick(_SW_OVER_CAP_POOL if swahili else _OVER_CAP_POOL, seed)
                .replace("{name}", name_tag).replace("{product}", subject))
    return _pick(_SW_NEUTRAL_ACK_POOL if swahili else _NEUTRAL_ACK_POOL, seed).replace("{name}", name_tag)


def _product_matching_answer(answer: str, seen: list) -> dict:
    """The product the reply actually NAMED — the order link must point at the
    same item the text quoted. The Asraya miss: the reply said 'Silver
    Communion Tray' but the link went to seen_products[0], the Silver BREAD
    Tray. Longest name mentioned in the answer wins; falls back to the first
    product seen (the over-cap path has no answer text at all)."""
    a = " ".join((answer or "").lower().split())
    best = None
    if a:
        for p in seen:
            n = " ".join((p.get("name") or "").lower().split())
            if n and n in a and (best is None or
                                 len(n) > len((best.get("name") or "").lower())):
                best = p
    return best or (seen[0] if seen else {})


async def _storefront_product_link(redis, channel: str, ext: str, product: dict) -> str:
    """A link to the product on the Bethany House storefront, carrying a handoff
    ref: `https://bethanyhouse.co.ke/product/<slug>?ref=XXXXXX`.

    The ref is the SAME `waref:` token the WhatsApp handover uses, and it now
    carries the resolved hub CART LINE for this product — so when the shopper
    continues (their inbox, WhatsApp, or the storefront's own Neema chat once it
    forwards the ref), we know who they are AND rebuild the exact item they were
    looking at. Returns "" when there's no slug or no storefront configured."""
    import secrets
    from app.agent import tools as _tools
    slug = (product or {}).get("slug")
    if not slug:
        return ""
    url = _tools._product_url(slug)
    if not url:
        return ""
    ref = secrets.token_hex(3).upper()
    try:
        if redis is not None:
            items = []
            try:                                  # resolve the real hub cart line
                from app.database import AsyncSessionLocal
                async with AsyncSessionLocal() as db:
                    ctx = _tools.ToolContext(db=db, redis=redis, wa_id=ext, channel=channel)
                    items = await _tools._resolve_cart_items(product.get("name") or "", ctx)
            except Exception:
                items = []
            await redis.set(
                f"waref:{ref}",
                json.dumps({"channel": channel, "external_id": ext, "target": url,
                            "product": (product.get("name") or "")[:200], "items": items}),
                ex=14 * 24 * 3600,
            )
            return f"{url}?ref={ref}"
    except Exception:
        pass
    return url


def _post_product_key(channel: str, post_id: str) -> str:
    return f"postprod:{channel}:{post_id}"


def _names_product(text: str, product_name: str) -> bool:
    """Does the comment itself name this product (at least half of the name's
    words, plural-tolerant)? "How much is the tallit?" names the Tallit;
    "share more designs for ladies" names nothing."""
    core = set(_core_tokens({"name": product_name or ""})) or _caption_tokens(product_name or "")
    if not core:
        return False
    shared = core & _caption_tokens(text or "")
    if not shared:
        return False
    return len(shared) / len(core) >= 1 / 3 or any(len(t) >= 6 for t in shared)


async def _recall_post_product(redis, channel: str, post_id: str) -> dict:
    """What our records say this post is about — identified once by an earlier
    reply on the same post, then reused so EVERY answer under that post names
    the SAME product. History wisdom for the caption-less video post: the
    first confident identification becomes the post's identity, and no later
    reply re-guesses it from a shiny frame. {} when nothing is on record."""
    if redis is None or not post_id:
        return {}
    try:
        raw = await redis.get(_post_product_key(channel, post_id))
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


async def _describe_post_image(thumb: str) -> str:
    """How the item in a post's photo LOOKS, in a shopkeeper's plain words —
    "green chasuble with an African-print stole down the middle and gold
    piping". Read once per post by the light model (owner, 2026-09-05: "get
    the colour and some details from the image"), then remembered with the
    post's identity so every later reply — the free path included, which
    never sees the picture — names the item as the customer sees it instead
    of by its catalogue label. Empty on any failure; never blocks a reply."""
    if not thumb or not settings.tier2_vision:
        return ""
    try:
        from app.agent.media import load_image_block
        block = await asyncio.to_thread(load_image_block, thumb)
        if not block:
            return ""
        llm = build_llm(model=settings.tier2_model_light)
        resp = await llm.complete(
            system=("You describe one product photo for a shopkeeper's reply. Plain "
                    "words only: no price, no brand, no praise, no full stop."),
            messages=[{"role": "user", "content": [
                block,
                {"type": "text", "text": (
                    "In at most 18 words, name the item for sale in this photo the way a "
                    "shopkeeper would to a buyer: its colour, then any pattern or trim "
                    "(for example: green chasuble with an African-print stole down the "
                    "middle and gold piping). One lowercase phrase. If no single item is "
                    "clear, reply with the single word NONE.")},
            ]}],
            tools=[])
        text = " ".join((resp.text or "").split()).strip(" .\"'")
        if not text or text.upper() == "NONE" or not (3 < len(text.split()) <= 24):
            return ""
        return text[:140]
    except Exception as exc:
        _log.info("post image description skipped: %s", exc)
        return ""


async def _remember_post_product(redis, channel: str, post_id: str, product: dict,
                                 thumb: str = "") -> None:
    """Record the post's identified product (30 days, best-effort) — and, once,
    how it looks in the post's photo, so replies can name it as seen.

    The record carries its PROVENANCE (owner, 2026-09-21): `source` is the rung
    that identified it (team / link / caption / image / vision / vision-name /
    model) and `confidence` its weight — read off the row's
    `_identity_source` / `_identity_confidence` stamps (post_catalog
    .with_provenance), "model" when the row came unstamped out of a reply.
    Only a trusted source may ever price a canned reply (identity_trusted).
    A record is never DOWNGRADED: a caption-identified post refreshed by a
    model turn keeps "caption"."""
    if redis is None or not post_id or not (product or {}).get("name"):
        return
    try:
        from app.services.post_catalog import SOURCE_CONFIDENCE
        known = await _recall_post_product(redis, channel, post_id)
        same = known.get("name") == product.get("name")
        seen = (known.get("seen") or "") if same else ""
        if not seen and thumb:
            seen = await _describe_post_image(thumb)
        source = str(product.get("_identity_source") or "model")
        try:
            confidence = float(product.get("_identity_confidence")
                               if product.get("_identity_confidence") is not None
                               else SOURCE_CONFIDENCE.get(source, 0.6))
        except (TypeError, ValueError):
            confidence = SOURCE_CONFIDENCE.get(source, 0.6)
        if same and known.get("source"):
            try:
                if float(known.get("confidence") or 0.0) > confidence:
                    source, confidence = known["source"], float(known["confidence"])
            except (TypeError, ValueError):
                pass
        record = {"name": product.get("name"),
                  "slug": product.get("slug") or "",
                  "hub_product_id": product.get("hub_product_id"),
                  "source": source, "confidence": round(confidence, 2)}
        if product.get("price_from"):
            record["price_from"] = True
        if product.get("family"):
            record["family"] = [str(m) for m in product["family"]][:12]
        # A combination the caption presents as one outfit (owner, 2026-09-21):
        # the items, so every later reply re-prices the same set from the hub.
        items = product.get("bundle") or (known.get("bundle") if same else None)
        if items:
            record["bundle"] = [{"name": str(i.get("name") or ""), "slug": str(i.get("slug") or "")}
                                for i in items if i.get("name")][:8]
        if seen:
            record["seen"] = seen
        await redis.set(_post_product_key(channel, post_id), json.dumps(record),
                        ex=30 * 24 * 3600)
    except Exception:
        pass


async def _first_contact(channel: str, ext: str) -> bool:
    """Has this person never been answered by us on this channel? A first
    comment gets the owner's welcome shape; anyone we have replied to before
    gets the answer first, no re-welcome. False on any doubt."""
    try:
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(Message.id).where(
                    Message.channel == channel,
                    Message.external_id == ext,
                    Message.direction == MsgDirection.outbound,
                ).limit(1))).first()
            return row is None
    except Exception:
        return False


def identity_trusted_record(record: dict | None) -> bool:
    from app.services.post_catalog import identity_trusted
    return identity_trusted(record)


def _post_identity_compatible(known: dict, caption: str | None, matched: dict,
                              comment_text: str = "", saw_image: bool = True) -> bool:
    """May `matched` become (or refresh) this post's RECORDED product identity?

    The record outlives every conversation, so a wrong write poisons every
    future commenter (live: a Silver-tray post answered as 'Gold Bread Tray'
    would have anchored the whole thread to the wrong product). The rules:
      - an existing identity is never overwritten by a DIFFERENT product (the
        model pricing a sibling one customer asked about must not rewrite what
        the POST is);
      - a product the COMMENT named ("what is an apostolic ring?") that the
        caption does not is the commenter's question, not the post's identity
        (owner, 2026-09-21: a cope post was recorded as a ring that way);
      - with a caption, the product must be supported by it (≥ half its name
        tokens appear there);
      - a caption-less post (thin reels) trusts the identification only when
        the reader SAW the frame (`saw_image`) — a text-only guess records
        nothing."""
    name = (matched or {}).get("name") or ""
    if not name:
        return False
    if known and known.get("name"):
        return _caption_tokens(known["name"]) == _caption_tokens(name)   # refresh only
    cap = (caption or "").strip()
    ntoks = _caption_tokens(name)
    if not ntoks:
        return False
    cap_toks = _caption_tokens(cap)
    in_caption = bool(cap) and len(ntoks & cap_toks) / len(ntoks) >= 0.5
    if comment_text:
        # Named in the comment but not in the caption → their question, not
        # the post. (Tokens of the name that the comment carries, minus the
        # ones the caption carries too.)
        com_toks = _caption_tokens(comment_text)
        if (ntoks & com_toks) and not (ntoks & cap_toks):
            return False
    if not cap:
        return bool(saw_image)
    return in_caption


async def _post_identity(redis, channel: str, pctx: dict) -> dict:
    """The post's product identity: recalled from our records, else resolved
    NOW by the deterministic ladder (caption slug/alias, then the image
    fingerprint against the hub's own catalogue photos) and remembered — so
    the post is identified once, for everyone who ever comments on it.
    {} when even the ladder can't say (the model then reads carefully and the
    team can set it via POST /admin/posts/{post_id}/product)."""
    post_id = (pctx.get("post_id") or "").strip()
    known = await _recall_post_product(redis, channel, post_id)
    stale = False
    if known.get("name") and known.get("source") and not identity_trusted_record(known):
        # A model's read, a vision name with no photo to compare, a legacy
        # record: a LEAD, not a fact. The ladder gets another go at a trusted
        # identity — once an hour per post, so a comment storm costs one
        # ladder — and a trusted hit replaces the lead (owner, 2026-09-23: the
        # ring post carried the model's "Apostolic Ring" while the caption
        # said "Bishop's Ring", the hub's own "Ring" row).
        retry_key = f"postcat:retry:{channel}:{post_id}"
        try:
            fresh = bool(await redis.set(retry_key, "1", nx=True, ex=3600)) if redis is not None else True
        except Exception:
            fresh = True
        if fresh and (pctx.get("title") or pctx.get("thumb")):
            try:
                from app.database import AsyncSessionLocal as _ASL2
                from app.services import n8n_bridge as _svc2
                from app.services import post_catalog as _pc2
                async with _ASL2() as _db2:
                    _cat2 = await _svc2.catalog_items(_db2, redis)
                hit = await _pc2.resolve_post(redis, pctx, _cat2)
                if hit is not None and _pc2.identity_trusted(
                        {"name": hit.get("name"), "source": hit.get("_identity_source"),
                         "confidence": hit.get("_identity_confidence")}):
                    await _remember_post_product(redis, channel, post_id, hit,
                                                 thumb=(pctx.get("thumb") or "").strip())
                    _log.info("post %s: lead %r replaced by trusted %r (%s)", post_id,
                              known.get("name"), hit.get("name"), hit.get("_identity_source"))
                    return await _recall_post_product(redis, channel, post_id) or known
            except Exception as exc:
                _log.info("post %s: ladder retry failed: %s", post_id, exc)
        return known
    if known.get("name") and known.get("source"):
        # A caption-stamped record of ONE piece under a caption that lists
        # several (owner, 2026-09-21: "Cassock" under the five-piece outfit)
        # is re-read by the ladder: the set row or the total replaces it,
        # and nothing at all replaces it when neither can be named.
        if known.get("source") == "caption" and (pctx.get("title") or "").strip():
            try:
                from app.database import AsyncSessionLocal as _ASL
                from app.services import n8n_bridge as _svc
                from app.services import post_catalog as _pc
                async with _ASL() as _db:
                    _cat = await _svc.catalog_items(_db, redis)
                stale = _pc.caption_record_stale(known, pctx.get("title") or "", _cat)
            except Exception:
                stale = False
        if not stale:
            return known
    try:
        from app.database import AsyncSessionLocal
        from app.services import n8n_bridge as svc
        from app.services import post_catalog
        async with AsyncSessionLocal() as db:
            catalog = await svc.catalog_items(db, redis)
        hit = await post_catalog.resolve_post(redis, pctx, catalog)
        if stale:
            if hit is not None:
                await _remember_post_product(redis, channel, post_id, hit,
                                             thumb=(pctx.get("thumb") or "").strip())
                _log.info("post %s: stale caption identity %r replaced by %r",
                          post_id, known.get("name"), hit.get("name"))
                return await _recall_post_product(redis, channel, post_id) or known
            try:
                await redis.delete(_post_product_key(channel, post_id))
            except Exception:
                pass
            _log.info("post %s: stale caption identity %r dropped — the caption lists "
                      "several items and names no set", post_id, known.get("name"))
            return {}
        if known.get("name"):
            # A record from before provenance existed (owner, 2026-09-21): the
            # ladder re-reads the post; if it agrees, the record takes the
            # ladder's rung, otherwise it stays as "legacy" — kept for the
            # model's context, never trusted to price a canned reply.
            if hit is not None and _caption_tokens(hit.get("name") or "") == \
                    _caption_tokens(known["name"]):
                await _remember_post_product(redis, channel, post_id, hit,
                                             thumb=(pctx.get("thumb") or "").strip())
            else:
                await _remember_post_product(
                    redis, channel, post_id,
                    {**known, "_identity_source": "legacy", "_identity_confidence": 0.5})
            return await _recall_post_product(redis, channel, post_id) or known
        if hit is not None:
            await _remember_post_product(redis, channel, post_id, hit,
                                         thumb=(pctx.get("thumb") or "").strip())
            return await _recall_post_product(redis, channel, post_id) or \
                {"name": hit.get("name"), "slug": hit.get("slug") or "",
                 "source": hit.get("_identity_source") or "model",
                 "confidence": hit.get("_identity_confidence") or 0.6}
    except Exception as exc:
        _log.info("deep post resolve failed for %s/%s: %s", channel, post_id, exc)
    return known if known.get("name") else {}


# Caption spelling drifts the hub's names don't: US spellings and plurals must
# still hit ("Aluminum trays" → Aluminium Tray).
_CAPTION_NORM = {"aluminum": "aluminium", "colors": "colour", "color": "colour"}


def _caption_tokens(text: str) -> set:
    return set(_caption_token_seq(text))


def _caption_token_seq(text: str) -> list:
    """Normalized tokens in ORDER (same stemming as _caption_tokens) — so a
    product name can be checked as a contiguous phrase, not just a bag of words."""
    out = []
    for t in re.findall(r"[a-z0-9']+", (text or "").lower()):
        t = _CAPTION_NORM.get(t, t)
        if len(t) > 2:
            out.append(t[:-1] if t.endswith("s") and len(t) > 3 else t)
    return out


def _contains_phrase(hay: list, needle: list) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def _hub_caption_match(catalog: list, title: str) -> dict | None:
    """The hub product a post caption is ABOUT — deterministic, no model.

    Scores every product against the WHOLE caption: full-name coverage is the
    strongest signal, a whole alias phrase counts alone ("communion cup filler"
    names the Refiller without the word Refiller). A near-tie means the caption
    honestly matches several siblings — return None and let the model (which
    can SEE the frame) or the both-options rule decide, never silently pick
    one. This is what identifies the product when a reel has a thin caption:
    the hub's own names and aliases ARE the intelligence."""
    # The caption in the hub's words first: "Cross and chain available" is
    # a Pectoral Cross post (core/synonyms), and scores as one.
    title = _canonical(title or "")
    text_l = title.lower()
    toks = _caption_tokens(title)
    cap_seq = _caption_token_seq(title)
    if not toks:
        return None
    # Rows that are one item in several sizes share a CORE name once the size
    # words are stripped ("Tallit (Prayer Shawl) - Medium", "Large Prayer Shawl
    # / Tallit"). Only THOSE rows are scored on the core — a caption saying
    # "Tallits / Prayer shawls" covers the item fully, the size word no
    # longer dilutes it below the bar (owner, 2026-09-21). A lone "Small
    # cross" or "Large bell" keeps its size word: there it is the product.
    core_count: dict = {}
    for prod in catalog:
        c = _core_tokens(prod)
        if c:
            core_count[c] = core_count.get(c, 0) + 1
    scored = []
    for prod in catalog:
        full_seq = _caption_token_seq(prod.get("name") or "")
        core = _core_tokens(prod)
        if core and core_count.get(core, 0) > 1:
            name_seq = [t for t in _caption_token_seq(_strip_size(prod.get("name") or ""))
                        if t not in _SIZE_WORDS] or full_seq
        else:
            name_seq = full_seq
        ntoks = set(name_seq)
        if not ntoks:
            continue
        cov = len(ntoks & toks) / len(ntoks)
        score = 3.0 * cov + (2.0 if cov == 1.0 else 0.0)
        # The caption literally SAYING the product name, in order, is decisive:
        # "We have Silver Communion Trays… holds 40 cups" gives full bag-of-words
        # coverage to BOTH the Tray and the Cups — the tie made the ladder refuse
        # to pick, and a model free-styled "Gold Bread Tray" under a Silver-tray
        # post (live, Arman thread). A contiguous phrase breaks such ties the way
        # a human reads the caption.
        if _contains_phrase(cap_seq, name_seq):
            score += 4.0
        for a in (prod.get("aliases") or []):
            if len(str(a)) > 3 and str(a).lower() in text_l:
                score += 3.0
                break
        if score > 0:
            scored.append((score, prod))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0]
    if best_score < 3.0:
        return None
    if len(scored) > 1 and (best_score - scored[1][0]) < 0.5:
        # Ambiguous siblings. When every tied row is the SAME item in another
        # size ("Tallit (Prayer Shawl) - Medium", "Large Prayer Shawl /
        # Tallit"), the caption named the item and the tie is only its sizes:
        # one family identity, priced "from" the cheapest (owner, 2026-09-21:
        # this tie left a tallit post unidentified and a guess sold oil).
        tied = [prod for sc, prod in scored if best_score - sc < 0.5]
        return _size_family(tied, toks)     # None: different products — don't guess
    # A clear winner that has SIZE siblings (same core name) is still one item
    # in several sizes: the family, priced from the cheapest.
    siblings = [prod for _sc, prod in scored[1:] if _core_tokens(prod) == _core_tokens(best)]
    if siblings:
        fam = _size_family([best] + siblings, toks)
        if fam is not None:
            return fam
    return best


def _core_tokens(prod: dict) -> frozenset:
    """The name's tokens with its size words removed."""
    return frozenset(t for t in _caption_token_seq(_strip_size(prod.get("name") or ""))
                     if t not in _SIZE_WORDS)


_SIZE_WORDS = {"small", "medium", "large", "big", "xl", "xxl", "xs", "sm", "md", "lg",
               "mini", "jumbo", "size", "sized"}


def _strip_size(name: str) -> str:
    """'Tallit (Prayer Shawl) - Medium' → 'Tallit (Prayer Shawl)';
    'Large Prayer Shawl / Tallit' → 'Prayer Shawl / Tallit'."""
    n = re.sub(r"\s*[-—–:]\s*(?:" + "|".join(_SIZE_WORDS) + r")\b.*$", "", name or "", flags=re.I)
    n = re.sub(r"^(?:" + "|".join(_SIZE_WORDS) + r")\s+", "", n, flags=re.I)
    n = re.sub(r"\s*\((?:" + "|".join(_SIZE_WORDS) + r")\)\s*", " ", n, flags=re.I)
    return " ".join(n.split()).strip(" -—–:/")


def _size_family(rows: list, caption_toks: set) -> dict | None:
    """One identity for rows that are the same item in different sizes: all of
    them must share the caption's product word(s) once size words are removed,
    and differ only by size words. Priced 'from' the cheapest, linked to it."""
    if len(rows) < 2:
        return None
    cores = [set(_core_tokens(r)) for r in rows]
    if any(not c for c in cores):
        return None
    shared = set.intersection(*cores)
    if not shared or not (shared & caption_toks):
        return None
    # IDENTICAL cores only: "Silver Communion Tray" and "Golden Communion Tray"
    # share a core but are two products; a stray word means a different item.
    if any(core != shared for core in cores):
        return None

    def _kes(r):
        try:
            v = float(r.get("price") or 0)
        except (TypeError, ValueError):
            v = 0.0
        return v if v > 0 else float("inf")

    cheapest = min(rows, key=_kes)
    prices = [_kes(r) for r in rows if _kes(r) != float("inf")]
    fam = dict(cheapest)
    fam["name"] = _strip_size(cheapest.get("name") or "") or cheapest.get("name")
    fam["family"] = [r.get("slug") or r.get("name") for r in rows]
    fam["price_from"] = bool(prices) and (max(prices) > min(prices))
    return fam


async def _resolve_post_product(redis, channel: str, ext: str,
                                post_ctx: dict, sink: list) -> None:
    """When the comment itself didn't price a product ("where is the shop?"),
    identify it from the post's IDENTITY (our records, else the deterministic
    ladder — caption slug/alias, image fingerprint), falling back to the
    caption's lead words — so the public CTA still lands on the exact
    storefront product page, never the bare wa.me fallback. Appends the
    matched hub rows into `sink` (the same seen_products list)."""
    known = await _post_identity(redis, channel, post_ctx)
    title = (post_ctx.get("title") or "").strip()
    from app.database import AsyncSessionLocal
    from app.agent import tools as _tools
    from app.services import post_catalog as _pc
    q = (known.get("name") or "").strip()
    cat: list = []
    if (not q and title) or known.get("bundle") or q:
        try:
            from app.services import n8n_bridge as _svc
            async with AsyncSessionLocal() as _db0:
                cat = await _svc.catalog_items(_db0, redis)
        except Exception:
            cat = []
    if not q and title:
        # No record yet: score the WHOLE caption against the hub's names and
        # aliases. A confident winner is the post's identity (source
        # "caption"), and the search runs on its exact name so the row
        # priced is the one recorded. NO confident winner → NO search: the
        # caption's lead words used to go into search_catalog here, and its
        # any-token fallback handed back an arbitrary row that a canned line
        # then sold — a tallit post priced anointing oil, a dress design a
        # bell (owner, 2026-09-21). A post we cannot name gets no product.
        # A caption that LISTS several items ("cassock, shirt, collar, belt
        # and stole") is never scored down to one of them either: the ladder
        # already tried the set row and the total (post_catalog), and a set
        # with no hub row and no clean total is the model's to price.
        try:
            from app.services.post_catalog import with_provenance
            hit = None
            if cat and len(_pc.caption_item_kinds(title, cat)) < 2:
                hit = _hub_caption_match(cat, title)
            if hit is not None and hit.get("name"):
                q = hit["name"]
                known = {**known, "name": hit["name"], "family": hit.get("family"),
                         "price_from": bool(hit.get("price_from"))}
                await _remember_post_product(
                    redis, channel, (post_ctx.get("post_id") or "").strip(),
                    with_provenance(hit, "caption"),
                    thumb=(post_ctx.get("thumb") or "").strip())
        except Exception:
            pass
    if not q:
        return
    try:
        async with AsyncSessionLocal() as db:
            ctx = _tools.ToolContext(db=db, redis=redis, wa_id=ext, channel=channel,
                                     seen_products=sink)
            if known.get("bundle"):
                # A combination the caption presents as one outfit (owner,
                # 2026-09-21): search every item by name and total them from
                # the hub's fresh rows — the synthetic total row leads the
                # sink, the items behind it. A piece the hub no longer sells
                # leaves nothing to price: no row, no guess.
                for item in known["bundle"]:
                    await run_tool("search_catalog", {"query": str(item.get("name") or "")}, ctx)
                rows = []
                for item in known["bundle"]:
                    row = _exact_row(sink, item.get("slug") or "", item.get("name") or "")
                    if row is None:
                        rows = []
                        break
                    rows.append(row)
                total = _pc.bundle_row(rows) if rows else None
                sink[:] = ([total] + rows) if total else []
                return
            await run_tool("search_catalog", {"query": q}, ctx)
            # A family identity ("Tallit (Prayer Shawl)", priced from the
            # cheapest size) is not a hub row name — search each member so
            # the rows are in hand, and keep the family's own label and
            # "from" price on the row the canned line will read.
            if not sink and known.get("family"):
                for member in known["family"]:
                    await run_tool("search_catalog", {"query": str(member)}, ctx)
            # The row RECORDED leads the sink — by slug, else by exact name —
            # not whichever row the search ranked first: "cassock set" also
            # finds the cheaper Classic Princes Cassock Set, and the canned
            # line reads sink[0] (owner, 2026-09-21: the hub names it, the
            # hub prices it).
            lead = _exact_row(sink, known.get("slug") or "", known.get("name") or "")
            if lead is not None and sink and sink[0] is not lead:
                sink.remove(lead)
                sink.insert(0, lead)
            if sink and known.get("price_from"):
                sink[0] = {**sink[0], "name": known.get("name") or sink[0].get("name"),
                           "price_from": True}
            # A hub SET row carries what it comes with (the hub's own
            # description), so the no-model line can say it.
            if sink and _pc.is_set_row(sink[0]):
                comps = _pc.set_components(sink[0], cat)
                if comps:
                    sink[0] = {**sink[0], "components": comps}
    except Exception as exc:
        _log.info("post-product resolve failed for %s: %s", ext, exc)


def _exact_row(rows: list, slug: str = "", name: str = "") -> dict | None:
    """The row that IS the recorded identity: the same slug, else the same
    name word for word. None when the search brought back only neighbours."""
    slug_l = (slug or "").strip().lower()
    if slug_l:
        for r in rows:
            if (r.get("slug") or "").strip().lower() == slug_l:
                return r
    want = _caption_tokens(name or "")
    if want:
        for r in rows:
            if _caption_tokens(r.get("name") or "") == want:
                return r
    return None


def _set_context(known: dict, catalog: list) -> str:
    """The model's line about a post that sells MORE than one row (owner,
    2026-09-21): a hub set row — its one price for everything and what it
    comes with — or a combination the caption presents as one outfit, to be
    totalled. "" for an ordinary single product."""
    from app.services import post_catalog as _pc
    if known.get("bundle"):
        names = ", ".join(str(i.get("name") or "") for i in known["bundle"] if i.get("name"))
        return (f". This post presents ONE outfit made of several hub items: {names} — "
                "search_catalog each of them and give the TOTAL of all of them with the "
                "items, never one item's price as if it were the whole; if they ask about "
                "one piece, give that piece's own price and the total in the same reply")
    row = _exact_row(catalog or [], known.get("slug") or "", known.get("name") or "")
    if row is None or not _pc.is_set_row(row):
        return ""
    comps = _pc.set_components(row, catalog)
    contents = (f"; it comes with {', '.join(comps)}" if comps
                else "; its contents are in the row's `details`")
    return (". It is a SET the hub prices as ONE row: give that one price for the whole "
            f"set{contents} — never one piece's price as the set's; if they ask about one "
            "piece, give that piece's own hub price and the set's total in the same reply")


def _listed_items_context(caption: str, catalog: list) -> str:
    """When no identity is on record but the caption LISTS several items, tell
    the model the rule (owner, 2026-09-21) instead of leaving it to pick one."""
    from app.services import post_catalog as _pc
    try:
        kinds = _pc.caption_item_kinds(caption or "", catalog or [])
    except Exception:
        kinds = []
    if len(kinds) < 2:
        return ""
    return (f". The caption lists several items ({', '.join(kinds)}). If the post presents "
            "them as ONE outfit or set, find every listed item with search_catalog and "
            "give the TOTAL with the items — never one item's price as if it were the "
            "whole; if they are separate products, give each its own price")


async def _order_link(redis, channel: str, ext: str, product: str = "") -> str:
    """A SHORT tap-to-order link that reaches a pre-filled WhatsApp order in one tap.

    NOTE: the comment funnel no longer calls this — public comment replies are
    link-free, so its only former consumer is gone. Kept (and still unit-tested)
    as the wa.me shortener for any surface that may legitimately send a link;
    delete it if nothing claims it.

    Returns our own short URL (`{media_public_url}/api/o/{ref}`) that 302-redirects
    to the real wa.me target stored in redis — a clean link, not a 300-char
    wa.me?text=… monster. Falls back to the raw wa.me link if no public host is
    configured."""
    import secrets
    from urllib.parse import quote
    num = (settings.whatsapp_handoff_number or "").lstrip("+").strip()
    if not num:
        return ""
    ref = secrets.token_hex(3).upper()
    # Keep the WhatsApp opener SHORT + sane — never stuff a whole post caption in.
    hint = " ".join((product or "").split())[:40].strip()
    body = (f"Hi Bethany House! I'd like to order {hint} (ref {ref})"
            if hint else f"Hi Bethany House! I'd like to order (ref {ref})")
    target = f"https://wa.me/{num}?text={quote(body)}"
    try:
        if redis is not None:
            await redis.set(
                f"waref:{ref}",
                json.dumps({"channel": channel, "external_id": ext, "target": target}),
                ex=14 * 24 * 3600,
            )
    except Exception:
        pass
    base = (settings.media_public_url or "").rstrip("/")
    return f"{base}/api/o/{ref}" if base else target


async def _post_over_cap(redis, post_id: str) -> bool:
    """True once this post has spent `meta_comment_agent_cap` full agent replies
    TODAY — beyond that, buying comments still get a warm reply, just a lighter
    (no-LLM) one. Caps AI cost + Graph rate on a viral post.

    Per-DAY on purpose: the old counter was per-post-per-14-days, so one boosted
    post (1,337 comments) burned its lifetime budget in hours and every buyer
    after that got the canned "DM us" line for the rest of a fortnight. A daily
    window keeps the runaway-cost backstop while the hot post — the one actually
    selling — reopens every morning."""
    if not redis or not post_id:
        return False
    from datetime import datetime, timezone
    try:
        key = f"meta:postcap:{post_id}:{datetime.now(timezone.utc):%Y%m%d}"
        n = await redis.incr(key)
        if n == 1:
            await redis.expire(key, 2 * 24 * 3600)
        return n > settings.meta_comment_agent_cap
    except Exception:
        return False


async def _run_comment_engage(redis, channel: str, comment: dict, own_pages: set) -> None:
    from app.database import AsyncSessionLocal
    from app.services import n8n_bridge as svc
    from app.services.meta_send import like_comment, reply_to_comment, send_private_reply

    cid = comment.get("comment_id")
    ext = comment.get("from_id")
    comment_text = (comment.get("text") or "").strip()
    first = (comment.get("from_name") or "").strip().split(" ")[0]
    name_tag = f" {first}" if first else ""

    # READ THE INTENT, GRADE IT, ROUTE IT (owner, 2026-09-22): one reading —
    # the plan's intent, what the comment IS (a request, a question, a
    # complaint, praise, mixed, a greeting), a complaint's weight, a request's
    # ask — and everything below acts on it.
    reading = await read_comment(comment_text, redis=redis)
    intent = reading["intent"]
    kind, severity, ask = reading["kind"], int(reading.get("severity") or 0), reading.get("ask") or ""
    plan = plan_comment_actions(intent)

    # ── LIVE BROADCAST ───────────────────────────────────────────────────────
    # During a live stream the room is full of people ARRIVING. classify_comment
    # sends a greeting to `high` on purpose — under a product photo a hello is a
    # door opening — but on a live video that turned "Watching from Liberia 🇱🇷"
    # into a price quote. Worse, the product is guessed from a video FRAME and
    # then recorded as the post's identity, so one bad guess priced every later
    # comment on the broadcast: a stream about vestments answered every question
    # with the price of a children's book.
    #
    # So while live: greet the greeters, and never guess a product.
    is_live = bool((comment.get("post_context") or {}).get("is_live"))
    # Kiswahili sanifu for a comment written in Swahili (owner, 2026-09-15);
    # every other canned line is English — never guessed from a name or flag.
    swahili = looks_swahili(comment_text)
    if is_live and intent in {"high", "low"} and not _mentions_catalogue_item(comment_text):
        # Nothing nameable in the comment. Either they are saying hello (welcome
        # them) or asking a price without saying of what (ask — never guess).
        style = "which" if intent == "high" and _looks_like_a_question(comment_text) else "welcome"
        plan = {"public": True, "style": style, "dm": False, "human": False}

    _log.info("comment %s intent=%s live=%s plan=%s", cid, intent, is_live, plan)
    if not (plan["public"] or plan["dm"] or plan["human"]):
        # Spam → stay silent publicly, but leave an internal note so the team can
        # SEE that Neema decided not to reply (and step in if it misjudged).
        await _note_silent_decision(channel, ext, cid, intent)
        return

    async def _post_public(text: str) -> bool:
        """The public reply. True when it landed — the Like below follows only
        a reply that did."""
        if not own_pages:                        # loop guard: can't tell our own reply apart
            _log.warning("META_PAGE_ID unset — skipping public reply for %s", cid)
            return False
        try:
            # Plain and human at the seam (voice.py): no markdown, no "$450
            # USD", no butler's "Very well." — whatever composed the text.
            await reply_to_comment(cid, plain_public_voice(text),
                                   page_id=comment.get("page_id"), channel=channel)
            return True
        except Exception as exc:
            _log.warning("public comment reply failed for %s: %s", cid, exc)
            return False

    async def _like_answered() -> None:
        """LIKE EVERY ANSWERED COMMENT (owner, 2026-09-22). The Page's Like
        follows the reply — a beat later, the way a person reacts after
        answering — on every comment we answered: a question, a hello, a
        cheer, an "amen". Never on a complaint (a Like on a grievance reads
        as mockery), never on spam (we did not reply), never on Instagram
        (no such edge). Best-effort: it never delays or fails the reply."""
        if not settings.meta_comment_like or intent in ("negative", "spam"):
            return
        if channel == "instagram":               # no comment-like edge on IG
            return
        try:
            import random
            await asyncio.sleep(random.uniform(1.0, 3.0))
            if await like_comment(cid, page_id=comment.get("page_id"), channel=channel):
                _log.info("comment %s liked after the reply (intent=%s)", cid, intent)
        except Exception as exc:
            _log.info("comment %s like skipped: %s", cid, exc)

    # ── Low intent (praise/emoji): a brief, VARIED, human thank-you — no pitch.
    # ── Negative: an empathetic line + route the conversation to a human.
    # Keyed on the STYLE, not the DM flag: goodwill gets a real answer from the
    # model below without opening a DM.
    if plan["style"] != "answer":
        if plan["public"]:
            if plan["style"] == "welcome":
                text = _pick(_SW_LIVE_WELCOME_POOL if swahili else _LIVE_WELCOME_POOL, ext).replace("{name}", name_tag)
            elif plan["style"] == "which":
                text = _pick(_SW_LIVE_WHICH_POOL if swahili else _LIVE_WHICH_POOL, ext).replace("{name}", name_tag)
            elif plan["style"] == "light":
                text = _pick(_SW_THANKS_POOL if swahili else _THANKS_POOL, ext).replace("{name}", name_tag)
            else:
                # A grievance: the private message FIRST for a serious or
                # grave one (so the details come privately), then the public
                # line by its weight — which claims the message only when it
                # went. Never a price, never a pitch, never cheer.
                private_sent = False
                if severity >= 2:
                    private_sent = await _private_complaint_message(
                        cid, comment.get("page_id"), channel, name_tag, swahili)
                text = empathy_text(kind, severity, swahili, private_sent=private_sent).replace("{name}", name_tag)
            posted = await _post_public(text)
            # Persist it threaded under the comment — the inbox must show every
            # outgoing reply, not just the high-intent ones.
            try:
                async with AsyncSessionLocal() as db2:
                    await svc.save_outbound_channel_message(db2, redis, channel, ext, text,
                                                            reply_to_comment_id=cid)
            except Exception as exc:
                _log.warning("saving light reply failed for %s: %s", cid, exc)
            if posted:
                await _like_answered()
        if plan["human"]:
            try:
                await _route_comment_to_human(channel, ext, comment_text, kind=kind,
                                              severity=severity, ask=ask, redis=redis)
            except Exception as exc:
                _log.warning("route-to-human failed for comment %s: %s", cid, exc)
        return

    # ── High intent: answer warmly in the public comment, then CONTINUE THE SALE
    # in the DM the comment opens — that Messenger thread is where we sell,
    # close, and capture the phone, unrushed. WhatsApp is NOT pushed in the
    # comment; the public CTA pulls them to their inbox instead. The comment
    # NEVER carries a link, whether or not the DM opened: an external link taxes
    # the reach of the whole post, so the invitation to write to us is the door.
    prompt_text = comment_text or "How much?"
    post_ctx = comment.get("post_context") or {}
    post_id = comment.get("post_id") or post_ctx.get("post_id") or ""
    thumb = (post_ctx.get("thumb") or "").strip()
    # Let the agent SEE the product in the post image and match it to the catalogue
    # (they rarely name the item — "how much?" under a photo is meaningless alone).
    # BUT only while we are actually unsure. Once a post is identified, our own
    # comment rule tells the model to price THAT product and "never re-guess it
    # from the frame" — so shipping the picture anyway buys nothing and costs a
    # great deal on the highest-volume path in the system: full-price vision
    # tokens (a thumbnail is ~1.6k, and an image in `messages` never rides the
    # cached prefix) AND a forced upgrade to the main model, because the caller
    # pins every media turn there. A pure redis recall decides it.
    _known_product = await _recall_post_product(redis, channel, post_id)
    # TRUST decides everything below (owner, 2026-09-21: see the image, compare
    # it, and never price a guess). A trusted identity — the team's word, a
    # storefront link, the hub's name in the caption, the hub's own photo, or a
    # vision read confirmed against the catalogue photo — may answer a bare
    # price ask with no model at all. Anything less (a model's earlier guess, a
    # record from before provenance) keeps the model reading the post IMAGE on
    # every turn until the ladder, the vision compare or the team settles it.
    from app.services.post_catalog import identity_trusted
    _trusted = identity_trusted(_known_product)
    # NEVER read the frame of a live broadcast for a product. A live frame is a
    # person talking in a shop full of stock — the match is a coin toss, and the
    # result gets recorded as the post's identity for every later comment.
    media = ({"type": "image", "url": thumb}
             if thumb and not is_live and not _trusted else None)

    # THE FREE PATH (owner's affordability push, 2026-08-18). The single most
    # common comment is a naked "How much?"/"Bei gani?" — and on a post our
    # records have already identified, everything a model call would produce is
    # already known: the product, its live hub price, and the storefront link.
    # The over-cap machinery below composes exactly that reply with NO model
    # call (_OVER_CAP_SELL_POOL: warm line + real price + one question), and the
    # DM still carries the product link. So an identified post answers its
    # price-asks for $0; the model is saved for comments that actually need
    # reading. English/Swahili only — other languages keep the model so replies
    # stay in the commenter's tongue.
    # Checked BEFORE the cap counter: a free reply must not spend the post's
    # daily model budget (the counter increments on every call).
    free_ask = _trusted and is_bare_price_ask(prompt_text)
    skip_model = free_ask or await _post_over_cap(redis, post_id)

    answer = ""
    seen_products: list = []          # the catalogue rows the agent actually priced
    if not skip_model:
        # Full agent reply — SEES the post image, quotes the REAL price, warm + short.
        try:
            # Cost routing: comment replies are the volume driver of the whole
            # bill. Light model by default; the main model for vision turns and
            # for comments carrying money or risk (see route_comment_model).
            _cmodel = settings.tier2_model if media else route_comment_model(prompt_text)
            async with AsyncSessionLocal() as db:
                # A reply inside a thread carries the comment it answers and
                # what we said there (owner, 2026-09-23).
                _parent = await _thread_parent(comment.get("parent_id") or "")
                answer = (await run_turn(
                    db, redis, wa_id=ext, user_text=prompt_text,
                    llm=build_llm(model=_cmodel),
                    media=media, channel=channel, external_id=ext,
                    public_comment=True, product_sink=seen_products,
                    comment_reading=reading, comment_post_id=post_id,
                    thread_parent=_parent)).strip()
        except Exception as exc:
            _log.warning("public agent reply failed for %s: %s", cid, exc)

    # Resolve the product FIRST — the exact storefront link belongs in the DM.
    # The comment may never name the product ("where is the shop?") — the POST
    # did (its recorded identity, its caption, its image). Resolved even when
    # there is NO agent answer (over the per-post cap, or the turn failed):
    # "How do I order?" is answerable without a model.
    if not seen_products:
        await _resolve_post_product(redis, channel, ext, post_ctx, seen_products)
        # The resolver may have just recorded a caption identity — re-read it,
        # so the canned line below sells only what the record now trusts.
        _known_product = await _recall_post_product(redis, channel, post_id)
        _trusted = identity_trusted(_known_product)
    product_link = ""
    matched: dict = {}
    if seen_products:
        matched = _product_matching_answer(answer, seen_products)
        try:
            product_link = await _storefront_product_link(redis, channel, ext, matched)
        except Exception as exc:
            _log.warning("product link failed for %s: %s", cid, exc)
        # This identification becomes the POST's identity: every later comment
        # under it prices the same product instead of re-guessing the frame.
        # GUARDED: a model guess that contradicts the caption — or differs from
        # an identity already on record — must never poison that record.
        if is_live:
            # A broadcast shows many products over an hour; it HAS no single
            # identity, and pinning one makes every later comment wrong.
            _log.info("post %s is live — not recording a product identity", post_id)
        elif _post_identity_compatible(_known_product, post_ctx.get("title"), matched,
                                       comment_text=comment_text, saw_image=bool(media)):
            # Recorded as the MODEL's read (source "model" unless the row came
            # stamped by the ladder): enough to keep later replies on the same
            # product, never enough to price a canned line on its own.
            await _remember_post_product(redis, channel, post_id, matched, thumb=thumb)
        else:
            _log.info("post %s: not recording %r as identity (known=%r, caption or comment disagrees)",
                      post_id, (matched or {}).get("name"), _known_product.get("name"))

    # Open the DM (so the public CTA can honestly point to the inbox). The DM
    # carries the answer, THE product link, and a warm invitation to continue
    # the sale right there — links live in DMs, where no algorithm scores the
    # post: Facebook suppresses the reach of link-carrying posts and comments,
    # so the private reply is the ONLY place the storefront link may travel.
    dm_sent = False
    # Goodwill opens no DM — unless the post sells a product, where the link is
    # the most useful thing we can hand them.
    if answer and (plan["dm"] or product_link):
        dm_text = _dm_text(plain_public_voice(answer), product_link, ext, swahili=swahili)
        try:
            await send_private_reply(cid, dm_text, page_id=comment.get("page_id"),
                                     channel=channel)
            dm_sent = True
        except Exception as exc:
            # Now that the public comment is unconditionally link-free, the
            # private reply is the ONLY route the storefront link has. A failure
            # here is a lost sale path, not a cosmetic miss — it used to be
            # papered over by pasting the link publicly. WARNING, so the rate of
            # it is visible in the logs (a steady stream means the page is
            # missing the `pages_messaging` permission, not that buyers are rare).
            _log.warning("comment DM not delivered for %s (%s) — the link had no "
                         "way to reach them: %s", cid, channel, exc)

    # The public reply is composed from FACTS, never from links: whether we
    # answered, whether the DM landed, and what the post sells. No URL is even
    # passed in — see _comment_public_reply, and the send-boundary guard in
    # meta_send.reply_to_comment that backs it up.
    #
    # Note what this is gated on: the product's NAME, not a mintable link. The
    # over-cap reply used to need `product_link`, so a catalogue row without a
    # storefront slug fell all the way back to the content-free acknowledgement.
    # A public reply no longer carries a link, so it no longer needs one to be
    # useful — knowing WHAT they're asking about is enough to answer warmly.
    product_name = (matched.get("name") or "").strip()
    # NO MODEL ANSWER → the canned line may name and price the product ONLY on
    # a trusted identity, and only when the comment asks for it (a bare price
    # ask, or the comment naming that very product). Everything else without
    # an answer is a warm acknowledgement, or "which item?" for a price ask
    # under a post we could not identify — never a price on a guess.
    ask_which = False
    if not answer:
        asks_it = is_bare_price_ask(prompt_text) or _names_product(prompt_text, product_name)
        if not _trusted or _caption_tokens(_known_product.get("name") or "") != _caption_tokens(product_name):
            ask_which = is_bare_price_ask(prompt_text)
            product_name = ""
            matched = {}
        elif not asks_it:
            matched = {k: v for k, v in matched.items()
                       if k not in ("price", "price_kes", "price_usd")}
    # The no-model line names the item AS SEEN when our records describe it —
    # a SET keeps the hub's name: "This is our Cassock Set" (owner's shape).
    if product_name and _known_product.get("seen") \
            and _known_product.get("name") == product_name \
            and not (matched.get("components") or matched.get("bundle")):
        product_name = _known_product["seen"]
    # The post identity carries hub prices. ONE currency (owner, 2026-09-05):
    # the canned line is priced in the commenter's own money — KES only when
    # their record (a captured location, a linked Kenyan number) says Kenya,
    # USD otherwise — and a per-piece good says "each". Looked up only when a
    # canned line is actually going out; the model path resolved it already.
    _usd, _kes = matched.get("price_usd"), matched.get("price_kes") or matched.get("price")
    _ccy = "USD"
    if not answer and product_name and (_kes or _usd):
        try:
            async with AsyncSessionLocal() as _db3:
                _ccy = (await _meta_market(_db3, channel, ext))[0]
        except Exception:
            _ccy = "USD"
    price_text = _public_price_text(_kes, _usd, _ccy)
    if price_text and (matched.get("price_from") or _known_product.get("price_from")):
        price_text = "from " + price_text        # one item in several sizes
    from app.services.price_audit import looks_per_piece as _per_piece
    per_piece = bool(matched) and _per_piece(matched)
    # The hub says whether this is made to order (its colour and size are the
    # customer's) or a stock item (its details are already known — never ask).
    made_to_order = bool(matched) and matched.get("product_type") == "variable" \
        and bool(matched.get("is_producible"))
    first = False
    if not answer and product_name and price_text and not per_piece:
        first = await _first_contact(channel, ext)
    # A SET IS PRICED AS ITS TOTAL (owner, 2026-09-21): a hub set row says
    # what it comes with; a combination says every item with its price.
    set_items, is_bundle = "", False
    if not answer and product_name and price_text:
        if matched.get("bundle") and matched.get("bundle_rows"):
            is_bundle = True
            set_items = _bundle_items_text(matched["bundle_rows"], _ccy, swahili)
        elif matched.get("components"):
            set_items = _components_text(matched["components"], swahili, set_name=product_name)
    public_text = _comment_public_reply(answer, dm_sent, name_tag, ext,
                                        product_known=bool(product_name),
                                        product_name=product_name,
                                        price_text=price_text,
                                        goodwill=(intent == "goodwill"),
                                        per_piece=per_piece, first_contact=first,
                                        swahili=swahili, made_to_order=made_to_order,
                                        ask_which=ask_which, set_items=set_items,
                                        bundle=is_bundle, kind=kind, ask=ask)
    public_text = plain_public_voice(public_text)

    posted = await _post_public(public_text)
    # NO MODEL ANSWER and nothing sold: the canned line promised a person, so
    # a person is told — the request, the question, or the comment we could
    # not read goes to the team to answer RIGHT THERE in the thread (owner,
    # 2026-09-22). A cheer needs no one; "which item?" is a real question back.
    if not answer and intent != "goodwill" and not ask_which and not (product_name and price_text):
        try:
            await _route_comment_to_human(
                channel, ext, comment_text,
                kind=(kind if kind in ("request", "question") else "other"),
                severity=0, ask=ask, answered=public_text, redis=redis)
        except Exception as exc:
            _log.warning("route-to-human failed for comment %s: %s", cid, exc)

    # Save our public reply THREADED to the comment it answers, so the inbox shows
    # comment → reply the way Facebook does (reply_to = this comment id).
    try:
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_channel_message(db2, redis, channel, ext, public_text,
                                                    reply_to_comment_id=cid)
    except Exception as exc:
        _log.warning("saving public reply to thread failed for %s: %s", cid, exc)
    if posted:
        await _like_answered()

    _log.info("comment %s engaged: agent=%s free_ask=%s dm=%s",
              cid, not skip_model, free_ask, dm_sent)


def _public_price_text(kes, usd, currency: str = "USD") -> str:
    """The price as a PUBLIC reply says it — ONE currency (owner, 2026-09-05):
    KES when the commenter's record shows Kenya, USD otherwise. The hub's own
    figure in that currency when it has one; else the other converted at the
    owner's rate, exactly as the tools do."""
    rate = settings.usd_kes_rate or 100
    try:
        if (currency or "").upper() == "KES":
            if kes:
                return money.fmt(kes, "KES")
            return money.fmt(money.exact(float(usd) * rate), "KES") if usd else ""
        if usd:
            return money.fmt(usd, "USD")
        return money.fmt(money.exact(float(kes) / rate, floor_cent=True), "USD") if kes else ""
    except (TypeError, ValueError):
        return ""


def schedule_comment_engage(redis, channel: str, comment: dict, own_pages: set) -> None:
    """Fire the intent-gated public + private replies for one comment, off the
    webhook ack path. A crash in the worker is logged (never silently swallowed by
    asyncio) so "no reply appeared" is always explainable from the logs."""
    task = asyncio.create_task(_run_comment_engage(redis, channel, comment, own_pages))
    _bg_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _bg_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            _log.warning("comment engage crashed for %s: %s",
                         comment.get("comment_id"), t.exception())

    task.add_done_callback(_done)
