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
from app.core.config import settings
from app.core.countries import resolve_country
from app.models.message import Message, MsgDirection
from app.models.user import User

_log = logging.getLogger("neema.agent")

# Meta Graph channels (see meta_send.META_CHANNELS). "facebook" = Page comment
# conversations — treated like Messenger for history keying + prompt formatting.
META_CHANNELS = ("messenger", "facebook", "instagram")

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

# A PUBLIC comment reply is short and read-only — it just needs the real price, so
# the catalogue tool (+ memory) is enough. The tap-to-order WhatsApp link is
# appended in code, not by the model.
_PUBLIC_COMMENT_TOOL_NAMES = {"search_catalog", "remember"}
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
    it reads like a friendly shopkeeper, not a price bot. Answer the question with
    the real price, then invite them to continue in the inbox (a call-to-action is
    added after your text). The full sale is closed 1:1 in the DM that follows."""
    money = "Kenyan Shillings (KES)" if currency == "KES" else "US Dollars (USD)"
    example = "'This gown is KES 13,000.'" if currency == "KES" else "'This gown is $130.'"
    return (
        "\n\n## Replying under a Facebook/Instagram comment — warm, human, helpful\n"
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
        "- If the comment is grief, condolence, illness or a prayer request, respond "
        "with warmth alone — a brief blessing. Sell NOTHING. Not every comment under a "
        "post is a customer at a till.\n"
        "- If you genuinely cannot tell what they mean, say nothing salesy: thank them "
        "and invite them to tell you more. A pitch aimed at a misread comment is worse "
        "than a plain thank-you.\n"
        "- Reply in the SAME language the comment is written in (French → French, "
        "Swahili → Swahili, etc.). Never answer a French or Swahili comment in English.\n"
        "- Recognise the product from the POST IMAGE (you can see it) and find it in "
        "the catalogue with search_catalog; if they name a different item, price that.\n"
        "- Be genuinely warm and human — a brief friendly word is welcome — but "
        "CONCISE: this is a public comment, so 1–2 short lines, plain text, no "
        "markdown or asterisks.\n"
        "- Made-to-order? Say it in a few words ('made to your size').\n"
        "- Do NOT write any link, phone number, or 'order on WhatsApp' — a friendly "
        "invitation to continue in their inbox is added after your text, and the "
        "real selling happens there.\n"
        "- Praise / emoji only → a short, genuine, warm thanks — nothing salesy."
    )


def _meta_addendum(currency: str = "USD") -> str:
    money = "Kenyan Shillings (KES)" if currency == "KES" else "US Dollars (USD)"
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
            "central-bank rate, rounding UP to the nearest 10; state it "
            "confidently, not as a guess."
        )
    return (
        "\n\n## This conversation is on Facebook Messenger / Instagram (not WhatsApp)\n"
        f"- Answer product questions using the catalogue via search_catalog. Prices "
        f"from the tool are already in {money} — quote them exactly, and never invent "
        f"a product or price; if something isn't in the catalogue, say so.{local}\n"
        "- Write PLAIN TEXT here — Messenger/Instagram show no bold, so use no "
        "asterisks, no `**`, no markdown; use short lines and hyphen lists.\n"
        "- You KNOW their name from their Messenger profile (it's in your context) — "
        "greet them by it and NEVER ask for it; only if no name appears in your "
        "context may you ask once. Early on, warmly ask just their city & country "
        "(we ship worldwide from Nairobi).\n"
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
        "WHATSAPP INVITATION above) — you may add, lightly and once, that we're on "
        "WhatsApp too if that's easier for them. Then keep selling HERE regardless "
        "of whether they take it up. Never repeat the invitation, and never let it "
        "replace the next step of the order.\n"
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
        "- Keep replies short, precise, and friendly; you are the same Bethany House assistant."
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
        "- Write plain, warm sentences — no markdown headings, no asterisks."
    )


def is_tier2(wa_id: str) -> bool:
    return settings.tier2_all or wa_id in settings.tier2_wa_ids()


# ── Per-turn model routing (roadmap #2) ──────────────────────────────────────
# Route trivial customer turns (pure greetings, thanks/acknowledgements, bare
# affirmations) to the cheap model; anything that could plausibly need a tool
# call — products, prices, quantities, delivery, payment, orders, or any
# question — stays on the main model. High precision on the light path: when
# in doubt, this returns the main model, because a mis-routed sales turn is
# worse than an extra cent spent on a greeting. Defined locally (not imported
# from n8n_bridge) since Tier 1's _ACK_RE deliberately excludes affirmatives
# like "yes"/"sawa" — those are load-bearing order confirmations there, but a
# bare "sawa"/"ok" with nothing else said still needs no tool call here.
_GREETING_RE = re.compile(
    r"^(hi+|hey+|hello+|helo+|habari|niaje|mambo|sasa|yo+|good\s*(morning|afternoon|evening)|"
    r"vipi|shalom)[\s!.,]*$",
    re.IGNORECASE,
)
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
            if iso == "KE":
                currency = "KES"
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
    # Website storefront visitor (web_chat mints a "web_<sha1>" session key rather
    # than a phone). They're already on the site that sells — see _web_addendum.
    is_web = not is_meta and str(wa_id or "").startswith(WEB_KEY_PREFIX)
    key = external_id if is_meta else wa_id

    # Currency display gate: Kenya → KES; everyone else → USD (= KES /
    # usd_kes_rate, done in the tools). WhatsApp knows Kenya from the +254
    # prefix; Meta channels know it from the captured location.
    if is_meta:
        user = None
        currency, loc, customer_name, source_post = await _meta_market(db, channel, key)
    else:
        user = (await db.execute(
            select(User).where(User.wa_id == wa_id))).scalar_one_or_none()
        # A web session key ("web_<sha1>") is NOT a phone — its hex digits used to
        # resolve to a random country/currency. No phone → no country claim.
        from app.core.phone import is_plausible_phone as _plausible
        loc = (resolve_country(wa_id) or {}) if _plausible(wa_id) else {}
        currency = "KES" if (loc.get("country_iso") or "").upper() == "KE" else "USD"
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
    system = build_system_prompt(
        country_iso=loc.get("country_iso") or "",
        currency=currency,
        directives=_directives,
    )
    if is_meta:
        system += _public_comment_addendum(currency) if public_comment else _meta_addendum(currency)
    elif is_web:
        system += _web_addendum()
    # Everything about THIS customer goes in a SECOND system block ("the tail"),
    # so the rules block above stays byte-identical fleet-wide and every turn
    # reads it from one shared cache entry instead of writing its own copy
    # (block 0 carries the 1h-TTL breakpoint — see llm._cached_system).
    tail = customer_context(customer_name, loc.get("country") or "")

    # 40 messages of context (was 20): re-asking an answered question is the
    # most robotic failure there is, and it usually happened because the answer
    # had scrolled out of a too-short window.
    messages = await _history(db, key, limit=40, channel=channel)

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
        base = PUBLIC_COMMENT_TOOLS       # read-only: just enough to quote a real price
    elif is_meta:
        base = MESSENGER_TOOLS
    elif is_web:
        # The visitor is ALREADY on our storefront, where the whole order can be
        # taken. Handing them a wa.me link here is pure friction — it sends a
        # ready buyer to another app — so the WhatsApp-link tool is off the table
        # on the website; her one natural invitation is the phone ask instead.
        base = [t for t in TOOLS if t["name"] != "whatsapp_checkout_link"]
    else:
        base = TOOLS
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
    for _ in range(settings.tier2_max_iterations):
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
            results.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": json.dumps(out),
            })
        messages.append({"role": "user", "content": results})
    else:
        # Ran out of iterations — return the last text if any, else a safe fallback.
        reply = resp.text or "Let me get a colleague to help you with this."

    # Measure spend so cost is visible, not guessed at (best-effort).
    try:
        from app.services import n8n_bridge as svc
        await svc.log_agent_usage(db, key, settings.tier2_model, totals)
    except Exception:
        _log.warning("usage logging failed for %s", key, exc_info=False)

    # Let the AI keep the lead stage + country tag current (forward-only).
    # WhatsApp only — lead_signals is keyed on wa_id/OrderEvent, which a
    # phone-less Meta conversation has none of.
    if not is_meta and not read_only:
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


_HOLD_LINE = ("Samahani for the wait — I'm having a small technical hitch on my "
              "side. A colleague has been alerted, and we'll be right back to "
              "you. Asante for your patience 🙏")


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
        if channel == "whatsapp":
            wamid = await svc._send_waba(key, _HOLD_LINE)
            async with AsyncSessionLocal() as db:
                await svc.save_outbound_message(db, redis, key, _HOLD_LINE,
                                                waba_msg_id=wamid)
        else:
            from app.services.meta_send import send_to_channel
            await send_to_channel(channel, key, _HOLD_LINE)
            async with AsyncSessionLocal() as db:
                await svc.save_outbound_channel_message(db, redis, channel, key,
                                                        _HOLD_LINE)
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
                                     note="Neema's reply FAILED here — she sent a short "
                                          "hold message; please review and answer."))
                    await db.commit()
        except Exception:
            pass
        _log.info("hold line sent to %s/%s", channel, key)
    except Exception:
        _log.warning("hold line failed for %s/%s", channel, key, exc_info=False)


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
        wamid = await svc._send_waba(wa_id, reply)
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_message(db2, redis, wa_id, reply, waba_msg_id=wamid)
        _log.info("tier2 replied to %s (%d chars)", wa_id, len(reply))
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


async def escalate_to_human(channel: str, ext: str, note: str) -> bool:
    """Hand this conversation to a person: route it out of AI mode and leave the
    reason in the Activity log, so the team sees it needs them. Used when Meta's
    24-hour window has closed — Neema physically cannot reply, but a human still
    can (Meta allows human agents a 7-day window). Best-effort; never raises.

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
                             action=InterceptAction.flag, note=note[:500]))
            await db.commit()
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
        try:
            await send_typing_on(external_id, page_id=page_id)
        except Exception:
            pass
        model = settings.tier2_model if media else route_model(text)
        async with AsyncSessionLocal() as db:
            reply = await run_turn(db, redis, wa_id=external_id, user_text=text,
                                   llm=build_llm(model=model),
                                   channel=channel, external_id=external_id,
                                   media=media)
        await send_to_channel(channel, external_id, reply, page_id=page_id)
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_channel_message(db2, redis, channel, external_id, reply)
        _log.info("tier2 replied on %s to %s (%d chars)", channel, external_id, len(reply))
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
            # Meta's 24h window shut before we could answer. Ask a human to take
            # it — and hand them Neema's drafted reply so they can just send it.
            draft = " ".join((reply or "").split())[:220]
            note = ("Outside Meta's 24-hour window — Neema can't reply. Please respond "
                    "from here (human agents get a 7-day window)."
                    + (f' Neema had drafted: "{draft}"' if draft else ""))
            _log.info("meta 24h window closed for %s/%s — routing to a human", channel, external_id)
            await escalate_to_human(channel, external_id, note)
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

_PUBLIC_EMPATHY = (
    "So sorry to hear this{name} 🙏 A member of our team will reach out to you "
    "personally to make it right — thank you for your patience. 💛"
)
_INTENTS = ("high", "low", "negative", "spam")

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


def looks_negative(text: str) -> bool:
    """True when a comment plainly expresses displeasure, a correction, or a
    grievance. Deterministic first pass for `classify_comment_intent`."""
    return bool(_NEGATIVE_RE.search((text or "").strip()))


async def classify_comment_intent(text: str) -> str:
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
    # Plain displeasure never goes to the model — and never becomes a sales pitch.
    if looks_negative(t):
        return "negative"
    prompt = (
        "Classify this public comment on a Christian clergy/communion store's post "
        "into ONE word:\n"
        "- high: buying interest OR any genuine question — price, availability, sizes, "
        "how to order, where you are located, delivery, opening hours, 'I want this'\n"
        "- low: praise, emoji, tagging a friend, 'amen', generic positivity, no question\n"
        "- negative: ANY dissatisfaction, correction, doubt or grievance — a complaint, "
        "anger, an unresolved order, criticism of us or of the post, or a claim that "
        "something is wrong/untrue. Short ones count: 'this is wrong', 'not true', "
        "'poor quality', 'still waiting', 'you never replied'. If a comment could be "
        "read as either a question OR displeasure, answer negative — a pitch sent to "
        "an unhappy person in public is far costlier than a careful reply.\n"
        "- spam: ONLY bots, ads, promotional links, or abuse\n"
        "Comments come in many languages (French, Swahili, Sheng, Chinese, Dutch…). "
        "A comment you don't understand is NOT spam: if it asks anything, answer "
        "'high'; if it's short and friendly or just a person's name, answer 'low'. "
        "Never answer 'spam' merely because it isn't English.\n"
        f'Comment: "{t[:300]}"\n'
        "Answer with exactly one word: high, low, negative, or spam."
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
    negative → empathetic public line + route to a human, no auto-sell ·
    spam → do nothing."""
    if intent == "spam":
        return {"public": False, "style": None, "dm": False, "human": False}
    if intent == "negative":
        return {"public": True, "style": "empathy", "dm": False, "human": True}
    if intent == "low":
        return {"public": True, "style": "light", "dm": False, "human": False}
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
_THANKS_POOL = [
    "Amen{name} 🙏 Thank you so much — God bless you! 💛",
    "Bless you{name} 🙏 We're so glad this speaks to you! 💛",
    "Thank you{name}! 🙏 Your kind words mean the world to us 💛",
    "Asante{name}! 🙏 May God bless you abundantly 💛",
    "So grateful{name} 🙏 Glory to God! 💛",
]
_WA_INVITE_POOL = [
    "Thank you{name} 🙏 Message us on WhatsApp and we'll help you order right away 💛",
    "Bless you{name}! 🙏 Reach us on WhatsApp and we'll sort you out 💛",
    "We'd love to help{name}! 🙏 Continue on WhatsApp to get yours 💛",
    "Karibu{name} 🙏 Tap through to WhatsApp and we'll take it from there 💛",
]
# Public-comment CTA when we've opened a DM: pull them to their inbox (where the
# real, unrushed selling happens) — NOT to WhatsApp.
_DM_NUDGE_POOL = [
    "I've sent you a message — let's finish there 💬",
    "Check your inbox 💬 I've messaged you the details 💛",
    "Replied in your inbox — let's sort it out there 💛",
    "Sent you a DM so we can get you sorted 💬",
]
# Said to a buying comment when the agent could not run (over the per-post cap,
# or the turn failed) but we DO know the product from the post. "How to order" is
# the highest-intent comment we get and it used to receive a bare "message us on
# WhatsApp" — on precisely the posts performing well enough to exhaust the cap.
# These answer the question instead, with no model call.
_OVER_CAP_POOL = [
    "Thank you{name} 🙏 You can order it right here 👉 {link} — tap through and we'll take care of the rest 💛",
    "Bless you{name}! 🙏 Order yours here 👉 {link} — a few taps and it's done 💛",
    "We'd love to help{name} 🙏 Here it is 👉 {link} — order in a tap, and message us if you'd like any help 💛",
    "Karibu{name} 🙏 You can see it and order here 👉 {link} — we'll handle delivery from there 💛",
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
# The line that continues the sale INSIDE the DM the comment opens.
_DM_CONTINUE_POOL = [
    "Reply here and I'll help you get yours — we'll sort out colour, size and delivery together. 💛",
    "Just reply here and we'll get you sorted — colour, size and delivery, step by step. 💛",
    "Tell me a little more here and I'll guide you all the way to your order. 💛",
]


def _pick(pool: list, seed: str) -> str:
    import hashlib
    i = int(hashlib.sha1((seed or "x").encode()).hexdigest(), 16) % len(pool)
    return pool[i]


def _comment_public_reply(answer: str, dm_sent: bool, link: str, name_tag: str, seed: str,
                          product_link: str = "") -> str:
    """The PUBLIC comment text, given the agent's answer and whether the DM landed.

    When we know WHICH product they're asking about, the comment links straight to
    that product on the Bethany House storefront — they can buy it right there, and
    Neema is on the page to answer anything. That link is the primary CTA; the
    inbox nudge still follows when the DM landed, and the tap-to-order WhatsApp
    link remains the fallback for when we couldn't identify the product AND the DM
    didn't land, so a real buyer is never stranded."""
    if answer and product_link:
        # One CTA, not three. They already have the product page (where Neema is
        # on hand) and a DM — adding "or message us on WhatsApp" made every public
        # reply a push to another app instead of an answer.
        tail = "Order here 👉 " + product_link + "\nNeema can help you right there 💬"
        return f"{answer}\n{tail}"
    if answer and dm_sent:
        return f"{answer}\n{_pick(_DM_NUDGE_POOL, seed)}"
    if answer:
        return f"{answer}\nOrder here 👉 {link}" if link else answer
    # No answer — we're over the per-post cap, or the agent turn failed. We do NOT
    # know what this person said, so we do NOT sell to them: pitching blind is how
    # "this is wrong" was answered with "Continue on WhatsApp to get yours". A
    # warm, content-free acknowledgement is always safe; the tap-to-order link is
    # added only when we DID identify what they're asking about.
    if product_link:
        # We know WHICH product the post is about, so a buying question still gets
        # a real answer — the product page, where they can order in a tap and
        # Neema is on hand. No model call needed.
        return (_pick(_OVER_CAP_POOL, seed)
                .replace("{name}", name_tag).replace("{link}", product_link))
    if link:
        return _pick(_WA_INVITE_POOL, seed).replace("{name}", name_tag)
    return _pick(_NEUTRAL_ACK_POOL, seed).replace("{name}", name_tag)


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


async def _resolve_post_product(redis, channel: str, ext: str,
                                post_ctx: dict, sink: list) -> None:
    """When the comment itself didn't price a product ("where is the shop?"),
    identify it from the POST's caption so the public CTA still lands on the
    exact storefront product page — never the bare wa.me fallback. Appends the
    matched hub rows into `sink` (the same seen_products list)."""
    title = (post_ctx.get("title") or "").strip()
    if not title:
        return
    from app.database import AsyncSessionLocal
    from app.agent import tools as _tools
    q = " ".join(title.split()[:8])            # captions run long; lead words name the item
    try:
        async with AsyncSessionLocal() as db:
            ctx = _tools.ToolContext(db=db, redis=redis, wa_id=ext, channel=channel,
                                     seen_products=sink)
            await run_tool("search_catalog", {"query": q}, ctx)
    except Exception as exc:
        _log.info("post-product resolve failed for %s: %s", ext, exc)


async def _order_link(redis, channel: str, ext: str, product: str = "") -> str:
    """A SHORT tap-to-order link the commenter can tap to reach a pre-filled
    WhatsApp order in one tap. Returns our own short URL
    (`{media_public_url}/api/o/{ref}`) that 302-redirects to the real wa.me target
    stored in redis — so the comment shows a clean link, not a 300-char wa.me?text=…
    monster. Falls back to the raw wa.me link only if no public host is configured."""
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
    """True once we've already spent `meta_comment_agent_cap` full agent replies on
    this post — beyond that, buying comments still get a warm reply, just a lighter
    (no-LLM) one. Caps AI cost + Graph rate on a viral post."""
    if not redis or not post_id:
        return False
    try:
        n = await redis.incr(f"meta:postcap:{post_id}")
        if n == 1:
            await redis.expire(f"meta:postcap:{post_id}", 14 * 24 * 3600)
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

    intent = await classify_comment_intent(comment_text)
    plan = plan_comment_actions(intent)
    _log.info("comment %s intent=%s plan=%s", cid, intent, plan)
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
    if not plan["dm"]:
        if plan["public"]:
            text = (_pick(_THANKS_POOL, ext).replace("{name}", name_tag)
                    if plan["style"] == "light"
                    else _PUBLIC_EMPATHY.replace("{name}", name_tag))
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
    # comment; the public CTA pulls them to their inbox instead. We only fall
    # back to a WhatsApp order link when the DM couldn't be delivered, so a real
    # buyer is never left with no way to reach us.
    prompt_text = comment_text or "How much?"
    post_ctx = comment.get("post_context") or {}
    post_id = comment.get("post_id") or post_ctx.get("post_id") or ""
    thumb = (post_ctx.get("thumb") or "").strip()
    # Let the agent SEE the product in the post image and match it to the catalogue
    # (they rarely name the item — "how much?" under a photo is meaningless alone).
    media = {"type": "image", "url": thumb} if thumb else None

    over_cap = await _post_over_cap(redis, post_id)

    answer = ""
    seen_products: list = []          # the catalogue rows the agent actually priced
    if not over_cap:
        # Full agent reply — SEES the post image, quotes the REAL price, warm + short.
        try:
            async with AsyncSessionLocal() as db:
                answer = (await run_turn(
                    db, redis, wa_id=ext, user_text=prompt_text, llm=build_llm(),
                    media=media, channel=channel, external_id=ext,
                    public_comment=True, product_sink=seen_products)).strip()
        except Exception as exc:
            _log.warning("public agent reply failed for %s: %s", cid, exc)

    # Open the DM first (so the public CTA can honestly point to the inbox). The DM
    # carries the answer + a warm invitation to continue the sale right there.
    dm_sent = False
    if answer:
        dm_text = f"{answer}\n\n{_pick(_DM_CONTINUE_POOL, ext)}"
        try:
            await send_private_reply(cid, dm_text, page_id=comment.get("page_id"),
                                     channel=channel)
            dm_sent = True
        except Exception as exc:
            _log.info("comment DM not delivered for %s: %s", cid, exc)

    # Build the PUBLIC reply CTA (see _comment_public_reply). Prefer a link to the
    # EXACT product the agent priced on the Bethany House storefront — they can buy
    # it there and Neema is on the page to help. The tap-to-order WhatsApp link is
    # only the fallback: no product identified AND the DM didn't land.
    # The comment may never name the product ("where is the shop?") — the POST
    # did. Resolve it from the post caption so the CTA still lands on the exact
    # bethanyhouse.co.ke product page with a ref.
    # Resolve the product even when there is NO agent answer (over the per-post
    # cap, or the turn failed). "How do I order?" is answerable without a model —
    # the post already tells us what they're looking at — and answering it with a
    # bare "message us on WhatsApp" wasted the highest-intent comment we get, on
    # exactly the posts that are working.
    if not seen_products:
        await _resolve_post_product(redis, channel, ext, post_ctx, seen_products)
    product_link = ""
    if seen_products:
        try:
            product_link = await _storefront_product_link(redis, channel, ext, seen_products[0])
        except Exception as exc:
            _log.warning("product link failed for %s: %s", cid, exc)
    link = (await _order_link(redis, channel, ext)
            if (answer and not dm_sent and not product_link) else "")
    public_text = _comment_public_reply(answer, dm_sent, link, name_tag, ext,
                                        product_link=product_link)

    await _post_public(public_text)

    # Save our public reply THREADED to the comment it answers, so the inbox shows
    # comment → reply the way Facebook does (reply_to = this comment id).
    try:
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_channel_message(db2, redis, channel, ext, public_text,
                                                    reply_to_comment_id=cid)
    except Exception as exc:
        _log.warning("saving public reply to thread failed for %s: %s", cid, exc)

    _log.info("comment %s engaged: agent=%s over_cap=%s dm=%s", cid, not over_cap, over_cap, dm_sent)


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
