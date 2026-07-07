"""LLM client abstraction for the Tier 2 agent.

Per the repo guardrails, external services sit behind an interface with a fake so
the suite runs with no network/secrets. `AnthropicLLM` is the real Claude client;
`FakeLLM` replays a scripted sequence of turns so tests can drive a full
sell→confirm→order flow deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    # Raw assistant content blocks (Anthropic shape) to append to the running
    # message list, so a follow-up call sees its own prior tool_use blocks.
    assistant_content: list[dict]
    tool_calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    stop_reason: str = "end_turn"
    # {input_tokens, output_tokens, cache_read_tokens, cache_write_tokens}
    usage: dict = field(default_factory=dict)


class LLM(Protocol):
    async def complete(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse: ...


def _battr(block: Any, attr: str, default=None):
    """Read a field from a block that may be an Anthropic SDK object OR a dict.

    Must NOT use truthiness fallback: a tool_use block's `input` is often {} (a
    no-arg tool), and `{} or block.get(...)` would call .get on an SDK object,
    which has no .get — the exact crash this replaces.
    """
    if isinstance(block, dict):
        return block.get(attr, default)
    return getattr(block, attr, default)


def _blocks_to_response(content: list[Any]) -> LLMResponse:
    """Normalise Anthropic content blocks into an LLMResponse."""
    assistant_content: list[dict] = []
    tool_calls: list[ToolCall] = []
    text_parts: list[str] = []
    for block in content:
        btype = _battr(block, "type")
        if btype == "text":
            t = _battr(block, "text", "") or ""
            text_parts.append(t)
            assistant_content.append({"type": "text", "text": t})
        elif btype == "tool_use":
            _id = _battr(block, "id")
            name = _battr(block, "name")
            inp = _battr(block, "input", {})
            if not isinstance(inp, dict):
                inp = {}
            tool_calls.append(ToolCall(id=_id, name=name, input=inp))
            assistant_content.append({"type": "tool_use", "id": _id, "name": name, "input": inp})
    return LLMResponse(assistant_content=assistant_content, tool_calls=tool_calls,
                       text="".join(text_parts).strip())


_EPHEMERAL = {"type": "ephemeral"}


def _cached_system(system: str):
    """System as a single cached text block (render order tools→system→messages,
    so this one breakpoint caches BOTH the tool defs and the system prompt)."""
    if not system:
        return system
    return [{"type": "text", "text": system, "cache_control": _EPHEMERAL}]


def _cache_last_message(messages: list[dict]) -> list[dict]:
    """Return a shallow copy of messages with a cache breakpoint on the last
    block, so the whole conversation prefix is cached and read incrementally
    across the tool-call loop. Never mutates the caller's list/blocks."""
    if not messages:
        return messages
    out = list(messages)
    last = dict(out[-1])
    content = last.get("content")
    if isinstance(content, str):
        last["content"] = [{"type": "text", "text": content, "cache_control": _EPHEMERAL}]
    elif isinstance(content, list) and content:
        new_content = list(content)
        new_content[-1] = {**new_content[-1], "cache_control": _EPHEMERAL}
        last["content"] = new_content
    out[-1] = last
    return out


class AnthropicLLM:
    """Real Claude client (async), with prompt caching + usage capture."""

    def __init__(self, api_key: str, model: str, max_tokens: int = 1024, cache: bool = True):
        from anthropic import AsyncAnthropic
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._cache = cache

    async def complete(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        sys_param = _cached_system(system) if self._cache else system
        msgs = _cache_last_message(messages) if self._cache else messages
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=sys_param,
            messages=msgs,
            tools=tools,
        )
        r = _blocks_to_response(resp.content)
        r.stop_reason = resp.stop_reason or "end_turn"
        u = resp.usage
        r.usage = {
            "input_tokens": getattr(u, "input_tokens", 0) or 0,
            "output_tokens": getattr(u, "output_tokens", 0) or 0,
            "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }
        return r


class FakeLLM:
    """Replays scripted turns. Each script entry is either:
      - {"text": "..."}                              → final assistant reply
      - {"tools": [{"name":..., "input":{...}}, ...]} → tool calls (one round)
    A counter makes tool_use ids unique across the run.
    """

    def __init__(self, script: list[dict]):
        self._script = list(script)
        self._i = 0
        self._uid = 0

    async def complete(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        if self._i >= len(self._script):
            return LLMResponse(assistant_content=[{"type": "text", "text": ""}], text="")
        step = self._script[self._i]
        self._i += 1
        if "tools" in step:
            blocks, calls = [], []
            for t in step["tools"]:
                self._uid += 1
                tid = f"toolu_{self._uid}"
                blocks.append({"type": "tool_use", "id": tid, "name": t["name"], "input": t.get("input", {})})
                calls.append(ToolCall(id=tid, name=t["name"], input=t.get("input", {})))
            return LLMResponse(assistant_content=blocks, tool_calls=calls, stop_reason="tool_use")
        text = step.get("text", "")
        return LLMResponse(assistant_content=[{"type": "text", "text": text}], text=text)
