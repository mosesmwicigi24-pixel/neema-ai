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
from app.agent.prompt import build_system_prompt
from app.agent.tools import TOOLS, ToolContext, run_tool
from app.core.config import settings
from app.core.countries import resolve_country
from app.models.message import Message, MsgDirection
from app.models.user import User

_log = logging.getLogger("neema.agent")

# Meta Graph channels (see meta_send.META_CHANNELS). "facebook" = Page comment
# conversations — treated like Messenger for history keying + prompt formatting.
META_CHANNELS = ("messenger", "facebook", "instagram")

# On Messenger/Instagram the customer has no phone, so we can't take payment or
# push an order to the hub. The agent answers product questions from the SAME
# hub catalogue (KES) — one source of truth, never USD, never invented items —
# and moves serious buyers to WhatsApp to check out. So it gets a read-only tool
# set (no cart / order / hub tools).
_META_TOOL_NAMES = {"search_catalog", "remember", "handoff_to_human", "whatsapp_checkout_link",
                    "share_catalog", "capture_contact", "pause_conversation"}
MESSENGER_TOOLS = [t for t in TOOLS if t["name"] in _META_TOOL_NAMES]

# A PUBLIC comment reply is short and read-only — it just needs the real price, so
# the catalogue tool (+ memory) is enough. The tap-to-order WhatsApp link is
# appended in code, not by the model.
_PUBLIC_COMMENT_TOOL_NAMES = {"search_catalog", "remember"}
PUBLIC_COMMENT_TOOLS = [t for t in TOOLS if t["name"] in _PUBLIC_COMMENT_TOOL_NAMES]


def _public_comment_addendum(currency: str = "USD") -> str:
    """System addendum for a PUBLIC comment reply — warm, human, and helpful, so
    it reads like a friendly shopkeeper, not a price bot. Answer the question with
    the real price, then invite them to continue in the inbox (a call-to-action is
    added after your text). The full sale is closed 1:1 in the DM that follows."""
    money = "Kenyan Shillings (KES)" if currency == "KES" else "US Dollars (USD)"
    example = "'This gown is KES 13,000.'" if currency == "KES" else "'This gown is $130.'"
    return (
        "\n\n## Replying under a Facebook/Instagram comment — warm, human, helpful\n"
        f"- Lead with the answer: the item + its real price in the first line, e.g. "
        f"{example} Quote in {money} (the `price` from search_catalog is already in "
        f"{money}) — never invent it.\n"
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
        "- HARD RULE: the MOMENT the customer states their name, city, country, or "
        "phone — even partially ('Machakos', just a first name) — call "
        "capture_contact IN THAT SAME TURN with everything they said. A stated "
        "detail that goes unsaved is a lost customer record.\n"
        "- CLOSE THE SALE RIGHT HERE — do not rush them to another app. Walk the "
        "whole order in Messenger, one warm step at a time: item → colour/design "
        "→ size → quantity → their city, then confirm the items and the total. "
        "Keep it moving until the order is fully agreed.\n"
        "- BEHIND THE SCENES, once the item is settled, warmly ask for their "
        "WhatsApp/phone number for ease of communication and to confirm delivery, "
        "and pass it to capture_contact — it links their Messenger and WhatsApp "
        "into one customer. Frame it as staying in touch, never as sending them "
        "away.\n"
        "- Payment is the ONLY step that happens on WhatsApp (our secure "
        "M-Pesa/checkout lives there). So ONLY once the full order is agreed AND "
        "they're ready to pay, call whatsapp_checkout_link with the product(s) and "
        "share the link it returns EXACTLY as given — never hand-type a wa.me link "
        "or number. Until that moment, keep selling here; do NOT point them to "
        "WhatsApp early — WhatsApp is only for the final payment.\n"
        "- Keep replies short, precise, and friendly; you are the same Bethany House assistant."
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


async def _history(db: AsyncSession, key: str, limit: int = 20,
                   *, channel: str = "whatsapp") -> list[dict]:
    # WhatsApp keys on wa_id (the compat shim); other channels key on
    # (channel, external_id) since their messages carry no wa_id.
    where = (Message.wa_id == key) if channel == "whatsapp" else (
        (Message.channel == channel) & (Message.external_id == key))
    rows = list(reversed((await db.execute(
        select(Message).where(where)
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
                   public_comment: bool = False) -> str:
    """Run one agent turn and return the reply text (does NOT send it).

    WhatsApp is the default and unchanged. For Messenger/Instagram, pass
    channel + external_id (the PSID/IGSID): the agent keys history on that,
    skips phone/hub-bound context, uses a read-only catalogue tool set, and is
    told to route checkout to WhatsApp — one brain, one KES catalogue."""
    is_meta = channel in META_CHANNELS
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
        loc = resolve_country(wa_id) or {}
        currency = "KES" if (loc.get("country_iso") or "").upper() == "KE" else "USD"
        customer_name = (user.name if user else "") or ""
        source_post = None
    system = build_system_prompt(
        customer_name=customer_name,
        country=loc.get("country") or "",
        country_iso=loc.get("country_iso") or "",
        currency=currency,
    )
    if is_meta:
        system += _public_comment_addendum(currency) if public_comment else _meta_addendum(currency)

    messages = await _history(db, key, channel=channel)

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
            pctx = await _post_context(source_post.get("post_id"), redis=redis) or {}
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
                      currency=currency, usd_rate=settings.usd_kes_rate)
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}

    def _accumulate(u: dict) -> None:
        for k in totals:
            totals[k] += int(u.get(k, 0) or 0)

    if is_meta and public_comment:
        base = PUBLIC_COMMENT_TOOLS       # read-only: just enough to quote a real price
    elif is_meta:
        base = MESSENGER_TOOLS
    else:
        base = TOOLS
    tools = base if settings.tier2_memory else [t for t in base if t["name"] != "remember"]

    reply = None
    for _ in range(settings.tier2_max_iterations):
        resp: LLMResponse = await llm.complete(system=system, messages=messages, tools=tools)
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
    if not is_meta:
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
        await svc._send_waba(wa_id, reply)
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_message(db2, redis, wa_id, reply)
        _log.info("tier2 replied to %s (%d chars)", wa_id, len(reply))
    except Exception:
        _log.exception("tier2 background turn failed for %s", wa_id)


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

async def _run_and_send_meta(redis, channel: str, external_id: str, text: str,
                             page_id: str | None = None,
                             media: dict | None = None) -> None:
    from app.database import AsyncSessionLocal
    from app.services.meta_send import send_to_channel
    from app.services import n8n_bridge as svc
    try:
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
    except Exception:
        _log.exception("tier2 meta turn failed for %s/%s", channel, external_id)


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


async def classify_comment_intent(text: str) -> str:
    """Label a public comment so we react appropriately. Cheap light-model call.
    Errs toward 'high' (engage) on uncertainty — better to help than go silent —
    but returns 'low' for an empty comment (emoji/sticker with no text)."""
    t = (text or "").strip()
    if not t:
        return "low"
    prompt = (
        "Classify this public comment on a Christian clergy/communion store's post "
        "into ONE word:\n"
        "- high: buying interest — price, availability, sizes, how to order, 'I want this'\n"
        "- low: praise, emoji, tagging a friend, 'amen', generic positivity, no question\n"
        "- negative: a complaint, anger, an unresolved order, or criticism\n"
        "- spam: bots, ads, links, abuse, or unrelated\n"
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


async def _route_comment_to_human(channel: str, external_id: str) -> None:
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation, InterceptMode
    async with AsyncSessionLocal() as db:
        conv = (await db.execute(select(Conversation).where(
            Conversation.channel == channel,
            Conversation.external_id == external_id))).scalar_one_or_none()
        if conv is not None:
            conv.intercept_mode = InterceptMode.human
            await db.commit()


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


def _comment_public_reply(answer: str, dm_sent: bool, link: str, name_tag: str, seed: str) -> str:
    """The PUBLIC comment text, given the agent's answer and whether the DM
    landed. DM delivered → pull them to their inbox (never push WhatsApp in the
    comment). DM failed → fall back to the tap-to-order WhatsApp link so a buyer
    isn't stranded. No answer (over cap / agent failed) → a warm light invite."""
    if answer and dm_sent:
        return f"{answer}\n{_pick(_DM_NUDGE_POOL, seed)}"
    if answer:
        return f"{answer}\nOrder here 👉 {link}" if link else answer
    return _pick(_WA_INVITE_POOL, seed).replace("{name}", name_tag)


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
        return                                   # spam → silent

    async def _post_public(text: str) -> None:
        if not own_pages:                        # loop guard: can't tell our own reply apart
            _log.warning("META_PAGE_ID unset — skipping public reply for %s", cid)
            return
        try:
            await reply_to_comment(cid, (text or "").strip(), page_id=comment.get("page_id"))
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
                await _route_comment_to_human(channel, ext)
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
    if not over_cap:
        # Full agent reply — SEES the post image, quotes the REAL price, warm + short.
        try:
            async with AsyncSessionLocal() as db:
                answer = (await run_turn(
                    db, redis, wa_id=ext, user_text=prompt_text, llm=build_llm(),
                    media=media, channel=channel, external_id=ext,
                    public_comment=True)).strip()
        except Exception as exc:
            _log.warning("public agent reply failed for %s: %s", cid, exc)

    # Open the DM first (so the public CTA can honestly point to the inbox). The DM
    # carries the answer + a warm invitation to continue the sale right there.
    dm_sent = False
    if answer:
        dm_text = f"{answer}\n\n{_pick(_DM_CONTINUE_POOL, ext)}"
        try:
            await send_private_reply(cid, dm_text, page_id=comment.get("page_id"))
            dm_sent = True
        except Exception as exc:
            _log.info("comment DM not delivered for %s: %s", cid, exc)

    # Build the PUBLIC reply CTA (see _comment_public_reply). Only mint the
    # WhatsApp order link when it's actually the fallback (answer but no DM).
    link = await _order_link(redis, channel, ext) if (answer and not dm_sent) else ""
    public_text = _comment_public_reply(answer, dm_sent, link, name_tag, ext)

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
    webhook ack path."""
    task = asyncio.create_task(_run_comment_engage(redis, channel, comment, own_pages))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
