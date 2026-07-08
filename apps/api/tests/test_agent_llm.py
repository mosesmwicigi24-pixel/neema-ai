"""FakeLLM + the agent loop contract (pure — no DB, no network).

Verifies the tool-call cycle the runtime depends on: the model emits tool_use
blocks, the harness feeds tool_result blocks back, and the loop terminates on a
final text turn.
"""
import asyncio
import json

import types

from app.agent.llm import (
    FakeLLM, LLMResponse, _blocks_to_response, _cached_system, _cache_last_message,
)


def test_cached_system_wraps_with_breakpoint():
    out = _cached_system("You are Neema.")
    assert out == [{"type": "text", "text": "You are Neema.",
                    "cache_control": {"type": "ephemeral"}}]
    assert _cached_system("") == ""  # empty stays empty (no breakpoint)


def test_cache_last_message_string_content():
    msgs = [{"role": "user", "content": "hi"}]
    out = _cache_last_message(msgs)
    assert out[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert msgs[-1]["content"] == "hi"  # original not mutated


def test_cache_last_message_block_content_not_mutated():
    original = [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]
    msgs = [{"role": "user", "content": original}]
    out = _cache_last_message(msgs)
    assert out[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in original[-1]  # caller's block untouched


def test_blocks_to_response_handles_sdk_objects_with_empty_input():
    # Real Anthropic blocks are objects (no .get); a no-arg tool has input={}.
    # This reproduces the live 'ToolUseBlock has no attribute get' crash.
    text_block = types.SimpleNamespace(type="text", text="On it.")
    tool_block = types.SimpleNamespace(type="tool_use", id="toolu_1", name="get_cart", input={})
    r = _blocks_to_response([text_block, tool_block])
    assert r.text == "On it."
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].name == "get_cart"
    assert r.tool_calls[0].input == {}
    assert r.assistant_content[1] == {"type": "tool_use", "id": "toolu_1", "name": "get_cart", "input": {}}


def test_fakellm_replays_tools_then_text():
    llm = FakeLLM([
        {"tools": [{"name": "search_catalog", "input": {"query": "cassock"}}]},
        {"tools": [{"name": "update_cart", "input": {"action": "add", "product": "Cassock", "quantity": 3}}]},
        {"text": "Added 3 cassocks. Shall I place the order?"},
    ])

    async def drive():
        # Round 1 — a tool call
        r1 = await llm.complete(system="s", messages=[{"role": "user", "content": "3 cassocks"}], tools=[])
        assert r1.tool_calls and r1.tool_calls[0].name == "search_catalog"
        assert r1.tool_calls[0].input == {"query": "cassock"}
        assert r1.assistant_content[0]["type"] == "tool_use"
        # Round 2 — another tool call
        r2 = await llm.complete(system="s", messages=[], tools=[])
        assert r2.tool_calls[0].name == "update_cart"
        # Round 3 — final text, no tools
        r3 = await llm.complete(system="s", messages=[], tools=[])
        assert not r3.tool_calls
        assert "place the order" in r3.text
        return r1, r2, r3

    asyncio.run(drive())


def test_fakellm_unique_tool_ids():
    llm = FakeLLM([{"tools": [{"name": "a", "input": {}}, {"name": "b", "input": {}}]}])

    async def drive():
        r = await llm.complete(system="", messages=[], tools=[])
        ids = [c.id for c in r.tool_calls]
        assert len(ids) == len(set(ids)) == 2
        return r

    asyncio.run(drive())


def test_generic_loop_terminates_on_text():
    """Mirror runtime.run_turn's loop shape over FakeLLM with a stub tool runner."""
    llm = FakeLLM([
        {"tools": [{"name": "search_catalog", "input": {"query": "oil"}}]},
        {"text": "We have Eliad Anointing Oil at KES 5,000."},
    ])

    async def fake_run_tool(name, args):
        return {"count": 1, "currency": "KES", "results": [{"name": "Eliad Anointing Oil", "price": 5000, "currency": "KES"}]}

    async def loop():
        messages = [{"role": "user", "content": "do you have anointing oil?"}]
        for _ in range(8):
            resp = await llm.complete(system="", messages=messages, tools=[])
            messages.append({"role": "assistant", "content": resp.assistant_content})
            if not resp.tool_calls:
                return resp.text
            results = [{
                "type": "tool_result", "tool_use_id": c.id,
                "content": json.dumps(await fake_run_tool(c.name, c.input)),
            } for c in resp.tool_calls]
            messages.append({"role": "user", "content": results})
        return None

    out = asyncio.run(loop())
    assert "Eliad" in out
