from __future__ import annotations

from unittest.mock import patch

from bob.agents.graph import build_turn_graph, stream_turn
from bob.agents.nodes.orchestrator import choose_route
from bob.agents.nodes.validator import regex_gate_node
from bob.agents.state import TurnRuntime, set_runtime, reset_runtime
from bob.agents.tool_adapter import registry_to_langchain_tools, spec_to_langchain_tool
from bob.llm import OllamaChat
from bob.tools.base import ToolSpec
from bob.tools.registry import ToolRegistry


def test_choose_route_fast_paths():
    assert choose_route("What time is it now?", thinks=True, has_tools=True, tools_unsupported=False) == (
        "direct",
        "time",
    )
    assert choose_route("What's 2 plus 2?", thinks=True, has_tools=True, tools_unsupported=False) == (
        "direct",
        "shortcut",
    )
    assert choose_route(
        "What's the biggest country in the world?",
        thinks=True,
        has_tools=True,
        tools_unsupported=False,
    ) == ("speak", "chitchat")
    assert choose_route("Search the web for pizza", thinks=True, has_tools=True, tools_unsupported=False) == (
        "tools",
        "web",
    )
    assert choose_route("What season is it?", thinks=True, has_tools=True, tools_unsupported=False) == (
        "tools",
        "calendar",
    )
    assert choose_route("What season of the year is it?", thinks=True, has_tools=True, tools_unsupported=False) == (
        "tools",
        "calendar",
    )
    assert choose_route(
        "I'm in Vernon, British Columbia, Canada.",
        thinks=True,
        has_tools=True,
        tools_unsupported=False,
    ) == ("direct", "shortcut")
    assert choose_route("Count back from 10.", thinks=True, has_tools=True, tools_unsupported=False) == (
        "direct",
        "shortcut",
    )
    assert choose_route("Are you censored?", thinks=False, has_tools=True, tools_unsupported=False) == (
        "tools",
        "react",
    )


def test_regex_gate_rejects_monologue():
    runtime = TurnRuntime(llm=OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12))
    token = set_runtime(runtime)
    try:
        out = regex_gate_node(
            {
                "user_text": "What time is it?",
                "draft": "Okay, the user is asking for the current time. Let me think.",
                "spoken": "Okay, the user is asking for the current time. Let me think.",
            }
        )
    finally:
        reset_runtime(token)
    assert out["gate_ok"] is False


def test_turn_graph_compiles():
    graph = build_turn_graph()
    assert graph is not None


def test_stream_turn_direct_clock():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [{"type": "function", "function": {"name": "get_current_time", "parameters": {}}}]
    with patch("bob.llm.httpx.Client") as client:
        chunks = list(
            stream_turn(
                chat,
                "What time is it now?",
                tools=tools,
                on_tool=lambda *_: "Monday, September 14, 2026 at 1:03 PM Pacific Daylight Time",
                max_rounds=1,
            )
        )
        client.assert_not_called()
    assert chunks == ["It's 1:03 PM, Pacific time."]


def test_stream_turn_calendar_speaks_season():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [{"type": "function", "function": {"name": "get_current_time", "parameters": {}}}]
    with patch("bob.llm.httpx.Client") as client:
        chunks = list(
            stream_turn(
                chat,
                "What season is it?",
                tools=tools,
                on_tool=lambda *_: "Monday, September 14, 2026 at 10:50 PM Pacific Daylight Time",
                max_rounds=1,
            )
        )
        client.assert_not_called()
    assert chunks == ["It's autumn."]


def test_stream_turn_location_ack():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    with patch("bob.llm.httpx.Client") as client:
        chunks = list(
            stream_turn(
                chat,
                "I'm in Vernon, British Columbia, Canada.",
                max_rounds=1,
            )
        )
        client.assert_not_called()
    assert chunks == ["Got it, you're in Vernon, British Columbia, Canada."]


def test_tool_adapter_wraps_registry(tmp_path):
    registry = ToolRegistry(tmp_path)

    def run(args, ctx):
        return "pong"

    spec = ToolSpec(name="ping", description="Ping", parameters={"type": "object", "properties": {}}, run=run)
    registry.add(spec)
    wrapped = spec_to_langchain_tool(spec, lambda name, arguments: registry.invoke(name, arguments))
    assert wrapped.name == "ping"
    assert wrapped.invoke({"arguments": {}}) == "pong"
    tools = registry_to_langchain_tools(registry)
    assert [tool.name for tool in tools] == ["ping"]
