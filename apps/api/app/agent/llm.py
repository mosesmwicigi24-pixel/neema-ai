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


class AnthropicLLM:
    """Real Claude client (async)."""

    def __init__(self, api_key: str, model: str, max_tokens: int = 1024):
        from anthropic import AsyncAnthropic
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def complete(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        r = _blocks_to_response(resp.content)
        r.stop_reason = resp.stop_reason or "end_turn"
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
