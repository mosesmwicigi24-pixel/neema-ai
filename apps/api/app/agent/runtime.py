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
    return (
        "\n\n## Replying under a Facebook/Instagram comment — warm, human, helpful\n"
        "- THE THREAD IS THE SHOP. Sell RIGHT HERE, in the comments, like a "
        "shopkeeper at a market stall with others listening: answer, quote, "
        "recommend, settle colour and quantity, close. Their next comment comes "
        "back to you with this whole thread in hand, so carry the sale forward "
        "turn by turn.\n"
        "- STAY ON THE POST'S PRODUCT. A follow-up comment — 'my order', 'yes', "
        "'I'm interested', 'how much' — continues the SAME product as the post "
        "and your own earlier replies in this thread. NEVER switch to a product "
        "nobody named: answering a Silver-tray thread with a Gold Bread Tray is "
        "a wrong answer even at the right price. Finish and colour are part of "
        "identity — silver is not gold. Only if THEY name a different product do "
        "you price that one, and the post's product stays what it was.\n"
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
        "- No greeting ritual here: a comment reply's first line is the ANSWER, "
        "never 'Good morning' — the FIRST CONTACT greeting rules do not apply to "
        "public comments.\n"
        f"- Lead with the answer: the item + its real price in the first line, e.g. "
        f"{example} Quote in {money} (the `price` from search_catalog is already in "
        f"{money}) — never invent it.\n"
        "- ANSWER THE QUESTION THEY ACTUALLY ASKED. If it isn't about price — where we "
        "are, delivery, opening hours, whether we ship to their country — answer THAT "
        "first, briefly, and only add a price if it's relevant.\n"
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
        "very well, asante Sylvia! 🙏 Is it the Bible in the photo you'd like?' "
        "Never answer a greeting with a canned thanks.\n"
        "- END WITH THE PULL: after the answer, ONE short inviting question that "
        "draws them into the conversation (which colour? how many? which country "
        "for delivery?) — a comment that answers AND asks is what starts the "
        "sale, and their answer lands right back in this thread.\n"
        "- SELL THE WAY YOU WOULD ON WHATSAPP: acknowledge what they said, name "
        "the item and its price, give one concrete benefit, then ask the one "
        "question that moves it forward. That is the whole shape of a comment "
        "reply — and the next one continues it.\n"
        "- If the comment is grief, condolence, illness or a prayer request, respond "
        "with warmth alone — a brief blessing. Sell NOTHING. Not every comment under a "
        "post is a customer at a till.\n"
        "- If you genuinely cannot tell what they mean, say nothing salesy: thank them "
        "and invite them to tell you more. A pitch aimed at a misread comment is worse "
        "than a plain thank-you.\n"
        "- Reply in the SAME language the comment is written in (French → French, "
        "Swahili → Swahili, etc.). Never answer a French or Swahili comment in English.\n"
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
        "quote confidently — USD when nothing places them — and switch "
        "seamlessly the moment a cue lands. Location talk belongs only where "
        "THEY ask where we are, or where you're giving shipping details — and "
        "then it reassures: Nairobi workshop, worldwide DHL delivery.\n"
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
        "dearer one. If they name a different item, price that.\n"
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
            "wrong."
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
        "colour/design → size → quantity → their city. Build the cart as they "
        "decide (`update_cart`), then show the items + total and confirm.\n"
        "- THE PHONE IS WHAT MAKES THE ORDER REAL. Once the items are settled, "
        "warmly ask for their WhatsApp/phone number — for the order confirmation "
        "and delivery — and pass it to capture_contact IN THAT SAME TURN. It also "
        "links their Messenger and WhatsApp into one customer. Frame it as "
        "staying in touch, never as sending them away. Without it we cannot place "
        "the order.\n"
        "- That number request IS your one natural WhatsApp invitation (see THE "
        "WHATSAPP INVITATION above) — and once they HAVE shared a phone/WhatsApp "
        "number, DO suggest it, politely and exactly once: 'Asante — saved for "
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
            "wrong."
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
        "colour/design → size → quantity → their city. Build the cart as they "
        "decide (update_cart), then show items + total and confirm.\n"
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


async def _cross_channel_context(db, key: str, channel: str) -> str:
    """The customer's recent messages on their OTHER linked channels — so a
    Facebook→WhatsApp hop continues the ACTUAL conversation ('the black cassock
    at $130 we discussed'), not a vibe. Empty when unlinked or on failure."""
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
    return ("\n\nTHEIR RECENT MESSAGES ON OTHER CHANNELS (same person, linked "
            "identity — continue THAT conversation; never re-ask what's here):\n"
            + "\n".join(lines[-8:]))


async def _history(db: AsyncSession, key: str, limit: int = 20,
                   *, channel: str = "whatsapp") -> list[dict]:
    # WhatsApp keys on wa_id (the compat shim); other channels key on
    # (channel, external_id) since their messages carry no wa_id.
    where = (Message.wa_id == key) if channel == "whatsapp" else (
        (Message.channel == channel) & (Message.external_id == key))
    rows = list(reversed((await db.execute(
        select(Message).where(where)
        # Internal NOTES are operator-private (escalation notes, call summaries,
        # silent-decision records) — they were never sent to the customer and must
        # NEVER reach the model as assistant turns it could echo back.
        .where(Message.media_type.is_(None) | (Message.media_type != "note"))
        .order_by(Message.created_at.desc()).limit(limit)
    )).scalars().all()))
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
    Messenger/IG carry no phone, so the default market is USD/worldwide — but a
    customer whose captured location (their own words via capture_contact, or a
    panel edit) resolves to Kenya IS the Kenyan market: real KES catalogue
    prices, M-Pesa, local delivery — never a USD conversion. The name comes from
    the person / identity so a known customer is greeted by name from turn one.
    source_post ({post_id, comment}) is the post their comment funnelled in
    from — a "How much?" DM refers to THAT product, so the agent must never ask
    "what are you looking for?"."""
    from app.core.countries import iso_from_text
    from app.models.person import Person, Identity
    currency, loc, name, source_post = "USD", {}, "", None
    try:
        ident = (await db.execute(select(Identity).where(
            Identity.channel == channel,
            Identity.external_id == key))).scalar_one_or_none()
        if ident is None:
            return currency, loc, name, source_post
        person = await db.get(Person, ident.person_id)
        u = (await db.execute(select(User).where(
            User.person_id == ident.person_id))).scalar_one_or_none()
        location = (((person.state or {}).get("location") if person else None)
                    or (u.location if u else None) or "")
        name = ((person.display_name if person else None)
                or getattr(ident, "display_name", None)
                or (u.name if u else None) or "")
        iso = iso_from_text(location)
        if iso:
            loc = {"country_iso": iso, "country": location}
            # Same market gate as WhatsApp: KE → KES, ZM → ZMW, else USD.
            currency = market_currency(iso)
        # Source post: this identity first, then siblings on the same person
        # (a facebook comment identity funnels into a messenger DM identity),
        # then the person state (stamped by the WhatsApp handover link).
        rp = getattr(ident, "raw_profile", None) or {}
        src, comment = rp.get("source_post"), rp.get("comment")
        if not src:
            sibs = (await db.execute(select(Identity).where(
                Identity.person_id == ident.person_id))).scalars().all()
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


async def run_turn(db: AsyncSession, redis, wa_id: str, user_text: str, llm: LLM,
                   media: dict | None = None,
                   *, channel: str = "whatsapp", external_id: str | None = None,
                   public_comment: bool = False, read_only: bool = False,
                   scribe_only: bool = False,
                   product_sink: list | None = None) -> str:
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
    else:
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
    messages = await _history(db, key,
                              limit=(14 if public_comment else 40), channel=channel)

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
        _xc = await _cross_channel_context(db, key, channel)
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
        if _known.get("name"):
            line += (f". Our records identify this post's product as: "
                     f"{_known['name']} — price THAT product; do not "
                     "re-identify it from the image")
        line += (". Unless they say otherwise, their questions refer to the product "
                 "in that post — identify it, find it with search_catalog, and "
                 "answer about THAT item. Do not ask what they are looking for.)")
        lead_ctx.append(line)
        if (settings.tier2_vision and not img_block and pctx.get("thumb")
                and not any(m["role"] == "assistant" for m in messages)):
            from app.agent.media import load_image_block
            post_img = await asyncio.to_thread(load_image_block, pctx["thumb"])
    if settings.tier2_memory:
        mem_ctx = await build_memory_context(db, redis, key, user=user, channel=channel)
        if mem_ctx:
            lead_ctx.append(f"(Context — what you know about this customer:\n{mem_ctx})")
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
    parts.append("Asante for choosing Bethany House 💛")
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
_INTENTS = ("high", "low", "negative", "spam", "goodwill")

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
    r"never\s+(?:replied|delivered|received|answered)|"
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


async def classify_comment_intent(text: str, redis=None) -> str:
    """Label a public comment so we react appropriately. Cheap light-model call.
    Errs toward 'high' (engage) on uncertainty — better to help than go silent —
    but returns 'low' for an empty comment (emoji/sticker with no text).

    `high` covers ANY genuine question, not just a price one: a location/delivery/
    hours question ("where are you?", "are you in Kenya?") used to fit no bucket
    and fell into `spam` by elimination, which meant total silence. `spam` is now
    only actual spam, and a comment we can't read is never spam for that reason."""
    t = (text or "").strip()
    if not t:
        return "low"
    # Cheering us on is read FIRST: "we can't wait to have you in Zambia" has
    # the word "wait" in it, and a model told to lean negative on anything
    # wait-shaped answered it with an apology and a complaint ticket.
    if looks_goodwill(t):
        return "goodwill"
    # Plain displeasure never goes to the model — and never becomes a sales pitch.
    if looks_negative(t):
        return "negative"
    # A hello is a door opening, not praise — engage, never the canned thanks.
    if looks_greeting(t):
        return "high"
    # Past the daily spend stop, even this light call waits for midnight: fall
    # to the same default the except-arm uses. "high" then flows into run_turn
    # (which refuses for free) and lands on the canned sell pools — so under a
    # budget stop the comment funnel keeps answering at exactly $0.
    try:
        from app.services import ai_budget
        if redis is not None and await ai_budget.mode(redis) == "stop":
            return "high"
    except Exception:
        pass
    prompt = (
        "Classify this public comment on a Christian clergy/communion store's post "
        "into ONE word:\n"
        "- high: buying interest OR any genuine question — price, availability, sizes, "
        "how to order, where you are located, delivery, opening hours, 'I want this'\n"
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
        "Comments come in many languages (French, Swahili, Sheng, Chinese, Dutch…). "
        "A comment you don't understand is NOT spam: if it asks anything, answer "
        "'high'; if it's short and friendly or just a person's name, answer 'low'. "
        "Never answer 'spam' merely because it isn't English.\n"
        f'Comment: "{t[:300]}"\n'
        "Answer with exactly one word: high, low, negative, goodwill, or spam."
    )
    try:
        llm = build_llm(model=settings.tier2_model_light)
        resp = await llm.complete(system="You label comments precisely. One word only.",
                                  messages=[{"role": "user", "content": prompt}], tools=[])
        word = (resp.text or "").strip().lower().split(" ")[0].strip(".,!\"'")
        return word if word in _INTENTS else "high"
    except Exception:
        return "high"


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


async def _route_comment_to_human(channel: str, external_id: str,
                                  comment: str = "") -> None:
    """Flag an unhappy commenter for the team — WITHOUT muting Neema.

    This used to set intercept_mode=human, which stopped the agent replying at
    all and also dropped the thread out of the missed-reply sweeper (it only
    picks up intercept_mode=ai). So a public complaint got one apology and then
    silence until someone opened the dashboard. The team is still brought in and
    still has the final word — they just aren't the customer's only hope of a
    reply in the meantime."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation
    from app.models.intercept import Intercept, InterceptAction
    async with AsyncSessionLocal() as db:
        conv = (await db.execute(select(Conversation).where(
            Conversation.channel == channel,
            Conversation.external_id == external_id))).scalar_one_or_none()
        if conv is None:
            return
        note = ("COMPLAINT (public comment) — a colleague must follow up and close this."
                + (f'\n• Their comment: "{" ".join(comment.split())[:300]}"' if comment else "")
                + "\n• Answered publicly with an apology only — no price, no pitch."
                + "\n• Neema stays available in the thread for factual questions.")
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
    return bool(_CATALOGUE_RE.search(text or ""))


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
    "Great question{name} 🙏 Which item are you asking about? Tell me and I'll give you the price right away 💛",
    "Happy to help{name}! 🙏 Which one caught your eye? Name it and I'll share the price 💛",
    "Of course{name} 🙏 Which piece do you mean? Let me know and I'll quote it for you 💛",
]

# A live viewer saying "watching from Liberia" is arriving, not shopping. The
# owner's words: "When I go live, I expect you to welcome people in." These are
# warm, varied, and sell NOTHING — the broadcast itself is the pitch.
_LIVE_WELCOME_POOL = [
    "Welcome{name} 🙏 So glad you could join us live — make yourself at home! 💛",
    "Karibu sana{name} 🙏 Lovely to have you with us today 💛",
    "Bless you for joining{name} 🙏 Enjoy the show — ask us anything as we go! 💛",
    "Welcome in{name}! 🙏 Great to see you here with us 💛",
    "So good to have you{name} 🙏 Watch along and say hello anytime 💛",
]

_THANKS_POOL = [
    "Amen{name} 🙏 Thank you so much — God bless you! 💛",
    "Bless you{name} 🙏 We're so glad this speaks to you! 💛",
    "Thank you{name}! 🙏 Your kind words mean the world to us 💛",
    "Asante{name}! 🙏 May God bless you abundantly 💛",
    "So grateful{name} 🙏 Glory to God! 💛",
]
# RETIRED from the answered path (2026-08-10: the comment thread IS the shop —
# an answered comment stands alone). Kept only as safe warm lines; nothing
# appends them to a selling reply anymore.
_DM_NUDGE_POOL = [
    "I've sent you a message — let's finish there 💬",
    "Check your inbox 💬 I've messaged you the details 💛",
    "Replied in your inbox — let's sort it out there 💛",
    "Sent you a DM so we can get you sorted 💬",
]
# Public-comment CTA when the DM did NOT open. We answered them, so we close the
# only way a public comment may: by asking them to write to us. This used to
# append the storefront link ("their only door") — the door is now the inbox,
# because a link in a comment taxes the reach of the whole post.
_COMMENT_INVITE_POOL = [
    "Send us a message and we'll sort you out 💛",
    "DM us and we'll get you sorted — colour, size and delivery 💛",
    "Message us and we'll take it from there 💛",
    "Send us a DM and we'll help you order 💛",
]
# Said to a buying comment when the agent could not run (over the per-post cap,
# or the turn failed) but we DO know from the post WHAT they're looking at. "How
# to order" is the highest-intent comment we get, so it gets a real, warm,
# link-free answer with no model call: name the item, invite them to the inbox.
# `{product}` is "the Aluminium Tray" when we identified it, else "it".
_OVER_CAP_POOL = [
    "Thank you{name} 🙏 Yes, {product} is available — send us a message and we'll share the price and get you sorted 💛",
    "Bless you{name}! 🙏 We do have {product} — DM us and we'll take care of the details and delivery 💛",
    "We'd love to help{name} 🙏 {product} is in — send us a message and we'll sort out size, colour and delivery 💛",
    "Karibu{name} 🙏 Yes, we have {product} — message us and we'll handle the price and delivery from there 💛",
]
# Over-cap AND we know the post's product WITH its price (from the post's
# recorded identity): the no-LLM line still SELLS — price + one pull question —
# instead of deflecting to the inbox. The owner's law is the comment thread is
# the shop; running out of model budget must not turn it back into a signpost.
_OVER_CAP_SELL_POOL = [
    "Thank you{name} 🙏 {product} is {price} — how many would you like? 💛",
    "Karibu{name} 🙏 {product} is {price}, ready for you — how many should we prepare? 💛",
    "Bless you{name}! 🙏 {product} is {price} — which quantity works for you? 💛",
    "We'd love to serve you{name} 🙏 {product} is {price} — how many would you like? 💛",
]
# Said when we could not compose a real answer (over the per-post cap, or the
# agent turn failed) AND we could not identify a product. It must be safe to send
# to ANYONE — a buyer, a critic, someone grieving — so it thanks, opens a door,
# and sells nothing at all.
# No cheerful emoji here (a 🙏 reads as humble; a 💛 reads as cheer) — this
# line may land on a complaint, and the mood rules forbid cheer on displeasure.
_NEUTRAL_ACK_POOL = [
    "Thank you for reaching out{name} 🙏 Tell us a little more and we'll gladly help.",
    "We appreciate you{name} 🙏 Send us a message and we'll help however we can.",
    "Thank you{name} 🙏 We're here — let us know what you need and we'll assist.",
    "Asante{name} 🙏 We'd be glad to help — just tell us a bit more.",
]
# The line that continues the sale INSIDE the DM the comment opens. Kept SHORT
# on purpose: this rides under the model's answer + the order link, and a long
# closing line is what made comment-DMs read like essays (2026-08-11).
_DM_CONTINUE_POOL = [
    "Reply here and I'll get yours sorted. 💛",
    "Reply here and we'll take it from there. 💛",
    "Tell me a little more and I'll sort you out. 💛",
]
# Over the per-post cap (or the turn failed) on a GOODWILL comment — the line a
# host gives when the room is full. Never the neutral "tell us a little more",
# which reads as a form handed to someone who just said "welcome". No promise,
# no year, no pitch: those need the post in hand, and only the model has it.
_GOODWILL_POOL = [
    "Thank you{name} 🙏 A welcome like yours means the world to us.",
    "Bless you{name} 🙏 Kind words like these carry us a long way.",
    "Thank you{name} 🙏 It's an honour to be cheered on like this.",
    "Asante sana{name} 🙏 We're so grateful for your warmth.",
    "Thank you{name} 🙏 We felt that — and we're so glad you're with us.",
]


def _pick(pool: list, seed: str) -> str:
    import hashlib
    i = int(hashlib.sha1((seed or "x").encode()).hexdigest(), 16) % len(pool)
    return pool[i]


def _dm_text(answer: str, product_link: str, seed: str) -> str:
    """The DM: the answer, THE product link, and the warm continue line. Links
    live here by design — Facebook suppresses the reach of posts and comments
    carrying external links, so the private message is where the storefront
    link travels."""
    link_line = f"Order here 👉 {product_link}\n" if product_link else ""
    return f"{answer}\n\n{link_line}{_pick(_DM_CONTINUE_POOL, seed)}"


def _comment_public_reply(answer: str, dm_sent: bool, name_tag: str, seed: str,
                          product_known: bool = False, product_name: str = "",
                          price_text: str = "", goodwill: bool = False) -> str:
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
        return _pick(_GOODWILL_POOL, seed).replace("{name}", name_tag)
    if product_known:
        # We know WHICH product the post is about, so a buying question still gets
        # a real, warm answer with no model call — with its PRICE when the post's
        # identity carries one, so even the over-cap line sells instead of
        # signposting the inbox.
        subject = f"the {product_name.strip()}" if product_name.strip() else "it"
        if price_text:
            return (_pick(_OVER_CAP_SELL_POOL, seed).replace("{name}", name_tag)
                    .replace("{product}", subject).replace("{price}", price_text))
        return (_pick(_OVER_CAP_POOL, seed)
                .replace("{name}", name_tag).replace("{product}", subject))
    return _pick(_NEUTRAL_ACK_POOL, seed).replace("{name}", name_tag)


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


async def _remember_post_product(redis, channel: str, post_id: str, product: dict) -> None:
    """Record the post's identified product (30 days, best-effort)."""
    if redis is None or not post_id or not (product or {}).get("name"):
        return
    try:
        await redis.set(_post_product_key(channel, post_id),
                        json.dumps({"name": product.get("name"),
                                    "slug": product.get("slug") or "",
                                    "hub_product_id": product.get("hub_product_id")}),
                        ex=30 * 24 * 3600)
    except Exception:
        pass


def _post_identity_compatible(known: dict, caption: str | None, matched: dict) -> bool:
    """May `matched` become (or refresh) this post's RECORDED product identity?

    The record outlives every conversation, so a wrong write poisons every
    future commenter (live: a Silver-tray post answered as 'Gold Bread Tray'
    would have anchored the whole thread to the wrong product). Three rules:
      - an existing identity is never overwritten by a DIFFERENT product (the
        model pricing a sibling one customer asked about must not rewrite what
        the POST is);
      - with a caption, the product must be supported by it (≥ half its name
        tokens appear there);
      - a caption-less post (thin reels) trusts the identification — recording
        the model's read is the whole point there."""
    name = (matched or {}).get("name") or ""
    if not name:
        return False
    if known and known.get("name"):
        return _caption_tokens(known["name"]) == _caption_tokens(name)   # refresh only
    cap = (caption or "").strip()
    if not cap:
        return True
    ntoks = _caption_tokens(name)
    if not ntoks:
        return False
    return len(ntoks & _caption_tokens(cap)) / len(ntoks) >= 0.5


async def _post_identity(redis, channel: str, pctx: dict) -> dict:
    """The post's product identity: recalled from our records, else resolved
    NOW by the deterministic ladder (caption slug/alias, then the image
    fingerprint against the hub's own catalogue photos) and remembered — so
    the post is identified once, for everyone who ever comments on it.
    {} when even the ladder can't say (the model then reads carefully and the
    team can set it via POST /admin/posts/{post_id}/product)."""
    post_id = (pctx.get("post_id") or "").strip()
    known = await _recall_post_product(redis, channel, post_id)
    if known.get("name"):
        return known
    try:
        from app.database import AsyncSessionLocal
        from app.services import n8n_bridge as svc
        from app.services import post_catalog
        async with AsyncSessionLocal() as db:
            catalog = await svc.catalog_items(db, redis)
        hit = await post_catalog.resolve_post(redis, pctx, catalog)
        if hit is not None:
            await _remember_post_product(redis, channel, post_id, hit)
            return {"name": hit.get("name"), "slug": hit.get("slug") or ""}
    except Exception as exc:
        _log.info("deep post resolve failed for %s/%s: %s", channel, post_id, exc)
    return {}


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
    text_l = (title or "").lower()
    toks = _caption_tokens(title)
    cap_seq = _caption_token_seq(title)
    if not toks:
        return None
    scored = []
    for prod in catalog:
        name_seq = _caption_token_seq(prod.get("name") or "")
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
        return None                     # ambiguous siblings — don't guess
    return best


async def _resolve_post_product(redis, channel: str, ext: str,
                                post_ctx: dict, sink: list) -> None:
    """When the comment itself didn't price a product ("where is the shop?"),
    identify it from the post's IDENTITY (our records, else the deterministic
    ladder — caption slug/alias, image fingerprint), falling back to the
    caption's lead words — so the public CTA still lands on the exact
    storefront product page, never the bare wa.me fallback. Appends the
    matched hub rows into `sink` (the same seen_products list)."""
    known = await _post_identity(redis, channel, post_ctx)
    title = (known.get("name") or "").strip() or (post_ctx.get("title") or "").strip()
    if not title:
        return
    from app.database import AsyncSessionLocal
    from app.agent import tools as _tools
    q = " ".join(title.split()[:8])            # captions run long; lead words name the item
    if not known.get("name"):
        # No record yet: score the WHOLE caption against the hub's names and
        # aliases. A confident winner narrows the search to its exact name, so
        # the identified product (and its live hub price) is the one recorded.
        try:
            from app.services import n8n_bridge as _svc
            async with AsyncSessionLocal() as _db0:
                cat = await _svc.catalog_items(_db0, redis)
            hit = _hub_caption_match(cat, title)
            if hit is not None and hit.get("name"):
                q = hit["name"]
        except Exception:
            pass
    try:
        async with AsyncSessionLocal() as db:
            ctx = _tools.ToolContext(db=db, redis=redis, wa_id=ext, channel=channel,
                                     seen_products=sink)
            await run_tool("search_catalog", {"query": q}, ctx)
    except Exception as exc:
        _log.info("post-product resolve failed for %s: %s", ext, exc)


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
    from app.services.meta_send import reply_to_comment, send_private_reply

    cid = comment.get("comment_id")
    ext = comment.get("from_id")
    comment_text = (comment.get("text") or "").strip()
    first = (comment.get("from_name") or "").strip().split(" ")[0]
    name_tag = f" {first}" if first else ""

    intent = await classify_comment_intent(comment_text, redis=redis)
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

    async def _post_public(text: str) -> None:
        if not own_pages:                        # loop guard: can't tell our own reply apart
            _log.warning("META_PAGE_ID unset — skipping public reply for %s", cid)
            return
        try:
            await reply_to_comment(cid, (text or "").strip(),
                                   page_id=comment.get("page_id"), channel=channel)
        except Exception as exc:
            _log.warning("public comment reply failed for %s: %s", cid, exc)

    # ── Low intent (praise/emoji): a brief, VARIED, human thank-you — no pitch.
    # ── Negative: an empathetic line + route the conversation to a human.
    # Keyed on the STYLE, not the DM flag: goodwill gets a real answer from the
    # model below without opening a DM.
    if plan["style"] != "answer":
        if plan["public"]:
            if plan["style"] == "welcome":
                text = _pick(_LIVE_WELCOME_POOL, ext).replace("{name}", name_tag)
            elif plan["style"] == "which":
                text = _pick(_LIVE_WHICH_POOL, ext).replace("{name}", name_tag)
            elif plan["style"] == "light":
                text = _pick(_THANKS_POOL, ext).replace("{name}", name_tag)
            else:
                text = _PUBLIC_EMPATHY.replace("{name}", name_tag)
            await _post_public(text)
            # Persist it threaded under the comment — the inbox must show every
            # outgoing reply, not just the high-intent ones.
            try:
                async with AsyncSessionLocal() as db2:
                    await svc.save_outbound_channel_message(db2, redis, channel, ext, text,
                                                            reply_to_comment_id=cid)
            except Exception as exc:
                _log.warning("saving light reply failed for %s: %s", cid, exc)
        if plan["human"]:
            try:
                await _route_comment_to_human(channel, ext, comment_text)
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
    # NEVER read the frame of a live broadcast for a product. A live frame is a
    # person talking in a shop full of stock — the match is a coin toss, and the
    # result gets recorded as the post's identity for every later comment.
    media = ({"type": "image", "url": thumb}
             if thumb and not is_live and not _known_product.get("name") else None)

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
    free_ask = bool(_known_product.get("name")) and is_bare_price_ask(prompt_text)
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
                answer = (await run_turn(
                    db, redis, wa_id=ext, user_text=prompt_text,
                    llm=build_llm(model=_cmodel),
                    media=media, channel=channel, external_id=ext,
                    public_comment=True, product_sink=seen_products)).strip()
        except Exception as exc:
            _log.warning("public agent reply failed for %s: %s", cid, exc)

    # Resolve the product FIRST — the exact storefront link belongs in the DM.
    # The comment may never name the product ("where is the shop?") — the POST
    # did (its recorded identity, its caption, its image). Resolved even when
    # there is NO agent answer (over the per-post cap, or the turn failed):
    # "How do I order?" is answerable without a model.
    if not seen_products:
        await _resolve_post_product(redis, channel, ext, post_ctx, seen_products)
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
        elif _post_identity_compatible(_known_product, post_ctx.get("title"), matched):
            await _remember_post_product(redis, channel, post_id, matched)
        else:
            _log.info("post %s: not recording %r as identity (known=%r, caption disagrees)",
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
        dm_text = _dm_text(answer, product_link, ext)
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
    # The post identity carries hub prices — comments quote USD by default.
    _usd, _kes = matched.get("price_usd"), matched.get("price_kes") or matched.get("price")
    price_text = money.fmt(_usd, "USD") if _usd else (money.fmt(_kes, "KES") if _kes else "")
    public_text = _comment_public_reply(answer, dm_sent, name_tag, ext,
                                        product_known=bool(product_name),
                                        product_name=product_name,
                                        price_text=price_text,
                                        goodwill=(intent == "goodwill"))

    await _post_public(public_text)

    # Save our public reply THREADED to the comment it answers, so the inbox shows
    # comment → reply the way Facebook does (reply_to = this comment id).
    try:
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_channel_message(db2, redis, channel, ext, public_text,
                                                    reply_to_comment_id=cid)
    except Exception as exc:
        _log.warning("saving public reply to thread failed for %s: %s", cid, exc)

    _log.info("comment %s engaged: agent=%s free_ask=%s dm=%s",
              cid, not skip_model, free_ask, dm_sent)


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
