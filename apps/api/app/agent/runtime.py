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

META_CHANNELS = ("messenger", "instagram")

# On Messenger/Instagram the customer has no phone, so we can't take payment or
# push an order to the hub. The agent answers product questions from the SAME
# hub catalogue (KES) — one source of truth, never USD, never invented items —
# and moves serious buyers to WhatsApp to check out. So it gets a read-only tool
# set (no cart / order / hub tools).
_META_TOOL_NAMES = {"search_catalog", "remember", "handoff_to_human"}
MESSENGER_TOOLS = [t for t in TOOLS if t["name"] in _META_TOOL_NAMES]


def _meta_addendum(currency: str = "USD") -> str:
    wa = (settings.whatsapp_handoff_number or "").strip()
    where = f"on WhatsApp at {wa}" if wa else "on WhatsApp"
    money = "Kenyan Shillings (KES)" if currency == "KES" else "US Dollars (USD)"
    # Local-currency conversion only for the USD-quoted customer, and only on request.
    local = ""
    if currency == "USD":
        local = (
            " If they explicitly ask for their own local currency, convert from the "
            "USD amount (never from KES) at the country's current central-bank rate, "
            "rounding UP to the nearest 10; state it confidently, not as a guess."
        )
    return (
        "\n\n## This conversation is on Facebook Messenger / Instagram (not WhatsApp)\n"
        f"- Answer product questions using the catalogue via search_catalog. Prices "
        f"from the tool are already in {money} — quote them exactly, and never invent "
        f"a product or price; if something isn't in the catalogue, say so.{local}\n"
        "- Write PLAIN TEXT here — Messenger/Instagram show no bold, so use no "
        "asterisks, no `**`, no markdown; use short lines and hyphen lists.\n"
        f"- You CANNOT take payment or place an order here. When the customer is "
        f"ready to order, warmly invite them to continue {where} to confirm and pay.\n"
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


async def run_turn(db: AsyncSession, redis, wa_id: str, user_text: str, llm: LLM,
                   media: dict | None = None,
                   *, channel: str = "whatsapp", external_id: str | None = None) -> str:
    """Run one agent turn and return the reply text (does NOT send it).

    WhatsApp is the default and unchanged. For Messenger/Instagram, pass
    channel + external_id (the PSID/IGSID): the agent keys history on that,
    skips phone/hub-bound context, uses a read-only catalogue tool set, and is
    told to route checkout to WhatsApp — one brain, one KES catalogue."""
    is_meta = channel in META_CHANNELS
    key = external_id if is_meta else wa_id

    user = None if is_meta else (
        await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()
    loc = {} if is_meta else (resolve_country(wa_id) or {})
    # Currency display gate: Kenya (+254) → KES; everyone else, and all
    # Messenger/IG (no phone), → USD (= KES / usd_kes_rate, done in the tools).
    currency = "USD" if is_meta else (
        "KES" if (loc.get("country_iso") or "").upper() == "KE" else "USD")
    system = build_system_prompt(
        customer_name=(user.name if user else "") or "",
        country=loc.get("country") or "",
        country_iso=loc.get("country_iso") or "",
        currency=currency,
    )
    if is_meta:
        system += _meta_addendum(currency)

    messages = await _history(db, key, channel=channel)

    # Current inbound turn. An image message has empty text (skipped by _history),
    # so build a multimodal turn — the agent SEES the photo (Claude vision) and
    # can match it to the catalogue. Voice notes already arrive as transcribed
    # text, so they need no special handling here.
    img_block = None
    if settings.tier2_vision and media and (media.get("type") == "image"):
        from app.agent.media import load_image_block
        img_block = load_image_block(media.get("url"))
    if img_block:
        caption = (media.get("caption") or "").strip()
        messages.append({"role": "user", "content": [
            img_block,
            {"type": "text", "text": caption or
             "(The customer sent this photo. Identify the item and search our catalogue for it.)"},
        ]})
    # The just-received message is already persisted by /message; only append it
    # if history didn't capture it (defensive) so the model always sees it last.
    elif not messages or messages[-1]["role"] != "user" or user_text.strip() not in messages[-1]["content"]:
        messages.append({"role": "user", "content": user_text})

    # Cross-conversation memory: prepend as a leading context turn so it stays
    # behind the cached system prefix and ahead of the real transcript, and
    # never touches the dedup check above (which only looks at the last message).
    if settings.tier2_memory:
        mem_ctx = await build_memory_context(db, redis, key, user=user)
        if mem_ctx:
            messages.insert(0, {"role": "user",
                                "content": f"(Context — what you know about this customer:\n{mem_ctx})"})

    ctx = ToolContext(db=db, redis=redis, wa_id=key,
                      currency=currency, usd_rate=settings.usd_kes_rate)
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}

    def _accumulate(u: dict) -> None:
        for k in totals:
            totals[k] += int(u.get(k, 0) or 0)

    if is_meta:
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


async def _run_and_send(redis, wa_id: str, text: str, media: dict | None = None) -> None:
    from app.database import AsyncSessionLocal
    from app.services import n8n_bridge as svc
    try:
        async with AsyncSessionLocal() as db:
            reply = await run_turn(db, redis, wa_id, text,
                                   build_llm(model=route_model(text)), media=media)
        await svc._send_waba(wa_id, reply)
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_message(db2, redis, wa_id, reply)
        _log.info("tier2 replied to %s (%d chars)", wa_id, len(reply))
    except Exception:
        _log.exception("tier2 background turn failed for %s", wa_id)


async def schedule_reply(redis, wa_id: str, text: str, dedup_id: str | None,
                         media: dict | None = None) -> bool:
    """Fire the agent for this inbound once. Returns False if already handled."""
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

async def _run_and_send_meta(redis, channel: str, external_id: str, text: str) -> None:
    from app.database import AsyncSessionLocal
    from app.services.meta_send import send_to_channel
    from app.services import n8n_bridge as svc
    try:
        async with AsyncSessionLocal() as db:
            reply = await run_turn(db, redis, wa_id=external_id, user_text=text,
                                   llm=build_llm(model=route_model(text)),
                                   channel=channel, external_id=external_id)
        await send_to_channel(channel, external_id, reply)
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_channel_message(db2, redis, channel, external_id, reply)
        _log.info("tier2 replied on %s to %s (%d chars)", channel, external_id, len(reply))
    except Exception:
        _log.exception("tier2 meta turn failed for %s/%s", channel, external_id)


async def schedule_meta_reply(redis, channel: str, external_id: str, text: str,
                              dedup_id: str | None) -> bool:
    """Fire the agent for one inbound Messenger/IG message. Deduped on the Meta
    message id so a redelivered webhook never double-replies."""
    if redis is not None and dedup_id:
        try:
            ok = await redis.set(f"agent:seen:meta:{dedup_id}", "1", ex=600, nx=True)
            if not ok:
                return False
        except Exception:
            pass
    task = asyncio.create_task(_run_and_send_meta(redis, channel, external_id, text))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return True
