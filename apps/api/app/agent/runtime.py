"""The Tier 2 agent loop.

Assembles context (recent history + who the customer is), runs the model with
tools, executes any tool calls, and loops until the model produces a final reply.
Returns the reply text; the caller sends + persists it.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import LLM, LLMResponse
from app.agent.prompt import build_system_prompt
from app.agent.tools import TOOLS, ToolContext, run_tool
from app.core.config import settings
from app.core.countries import resolve_country
from app.models.message import Message, MsgDirection
from app.models.user import User

_log = logging.getLogger("neema.agent")


def is_tier2(wa_id: str) -> bool:
    return settings.tier2_all or wa_id in settings.tier2_wa_ids()


async def _history(db: AsyncSession, wa_id: str, limit: int = 20) -> list[dict]:
    rows = list(reversed((await db.execute(
        select(Message).where(Message.wa_id == wa_id)
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


async def run_turn(db: AsyncSession, redis, wa_id: str, user_text: str, llm: LLM) -> str:
    """Run one agent turn and return the reply text (does NOT send it)."""
    user = (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()
    loc = resolve_country(wa_id) or {}
    system = build_system_prompt(
        customer_name=(user.name if user else "") or "",
        country=loc.get("country") or "",
        country_iso=loc.get("country_iso") or "",
    )

    messages = await _history(db, wa_id)
    # The just-received message is already persisted by /message; only append it
    # if history didn't capture it (defensive) so the model always sees it last.
    if not messages or messages[-1]["role"] != "user" or user_text.strip() not in messages[-1]["content"]:
        messages.append({"role": "user", "content": user_text})

    ctx = ToolContext(db=db, redis=redis, wa_id=wa_id)

    for _ in range(settings.tier2_max_iterations):
        resp: LLMResponse = await llm.complete(system=system, messages=messages, tools=TOOLS)
        messages.append({"role": "assistant", "content": resp.assistant_content})

        if not resp.tool_calls:
            return resp.text or "One moment — let me check on that for you."

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

    # Ran out of iterations — return the last text if any, else a safe fallback.
    return resp.text or "Let me get a colleague to help you with this."


def build_llm() -> LLM:
    from app.agent.llm import AnthropicLLM
    return AnthropicLLM(
        api_key=settings.anthropic_api_key,
        model=settings.tier2_model,
        max_tokens=settings.tier2_max_tokens,
    )


# ── Background trigger (used by the /profile hook) ───────────────────────────
# Tier 2 runs the agent OFF the request path so /profile stays fast: it schedules
# a background task that runs the loop, sends the reply, and persists it. n8n's
# 'Should Run AI?' then sees should_run_ai=false and stays silent. Deduped per
# inbound message so a retried /profile never double-replies.

import asyncio  # noqa: E402

_bg_tasks: set = set()


async def _run_and_send(redis, wa_id: str, text: str) -> None:
    from app.database import AsyncSessionLocal
    from app.services import n8n_bridge as svc
    try:
        async with AsyncSessionLocal() as db:
            reply = await run_turn(db, redis, wa_id, text, build_llm())
        await svc._send_waba(wa_id, reply)
        async with AsyncSessionLocal() as db2:
            await svc.save_outbound_message(db2, redis, wa_id, reply)
        _log.info("tier2 replied to %s (%d chars)", wa_id, len(reply))
    except Exception:
        _log.exception("tier2 background turn failed for %s", wa_id)


async def schedule_reply(redis, wa_id: str, text: str, dedup_id: str | None) -> bool:
    """Fire the agent for this inbound once. Returns False if already handled."""
    if redis is not None and dedup_id:
        try:
            ok = await redis.set(f"agent:seen:{dedup_id}", "1", ex=600, nx=True)
            if not ok:
                return False
        except Exception:
            pass  # if the dedup store is down, better to reply than to go silent
    task = asyncio.create_task(_run_and_send(redis, wa_id, text))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return True
