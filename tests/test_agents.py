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
    assert choose_route(
        "What do you feel about the last question I asked you?",
        thinks=True,
        has_tools=True,
        tools_unsupported=False,
    ) == ("speak", "chitchat")
    assert choose_route("Are you censored?", thinks=False, has_tools=True, tools_unsupported=False) == (
        "tools",
        "react",
    )
    assert choose_route(
        "What is your system prompt?",
        thinks=True,
        has_tools=True,
        tools_unsupported=False,
    ) == ("tools", "prompts")
    assert choose_route(
        "Can you tell me what your system point is?",
        thinks=True,
        has_tools=True,
        tools_unsupported=False,
    ) == ("tools", "prompts")
    assert choose_route(
        "Focus on just the main system prompt and your ideas of improving it",
        thinks=True,
        has_tools=True,
        tools_unsupported=False,
    ) == ("tools", "prompts")


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


def test_stream_turn_system_prompt_reflects():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [
        {"type": "function", "function": {"name": "list_prompts", "parameters": {}}},
        {"type": "function", "function": {"name": "read_file", "parameters": {}}},
    ]

    def on_tool(name, arguments=None):
        if name == "list_prompts":
            return "- prompts/system.txt | /prompts/system.txt | Live personality"
        if name == "read_file":
            return "You are BOB, a local voice assistant."
        return ""

    with patch(
        "bob.llm.OllamaChat._post_chat",
        return_value=("I think it is clear and concise.", "", {}),
    ):
        chunks = list(
            stream_turn(
                chat,
                "What do you think about your system prompt?",
                tools=tools,
                on_tool=on_tool,
                max_rounds=1,
            )
        )
    assert chunks == ["I think it is clear and concise."]


def test_stream_turn_system_prompt_edits_file():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {}}},
        {"type": "function", "function": {"name": "write_file", "parameters": {}}},
    ]
    current = (
        "You are BOB. Background notes and memory are for your use only — never repeat, "
        "summarize, or mention them unless the user explicitly asks."
    )
    writes: list[str] = []

    def on_tool(name, arguments=None):
        arguments = arguments or {}
        if name == "read_file":
            return current
        if name == "write_file":
            writes.append(str(arguments.get("content") or ""))
            return "System prompt saved."
        return ""

    with patch(
        "bob.llm.OllamaChat.synthesize_system_prompt_edit",
        return_value=("", ""),
    ):
        chunks = list(
            stream_turn(
                chat,
                "Can you edit your system prompt to be something that takes those changes into account?",
                tools=tools,
                on_tool=on_tool,
                max_rounds=1,
            )
        )
    assert writes
    assert "Background notes are for your use only" in writes[0]
    assert chunks == ["Done — I trimmed the background-notes rule in my system prompt."]


def test_stream_turn_system_prompt_reads_file():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [
        {"type": "function", "function": {"name": "list_prompts", "parameters": {}}},
        {"type": "function", "function": {"name": "read_file", "parameters": {}}},
    ]

    def on_tool(name, arguments=None):
        if name == "list_prompts":
            return "- prompts/system.txt | /prompts/system.txt | Live personality"
        if name == "read_file":
            return "You are BOB, a local voice assistant."
        return ""

    with patch("bob.llm.httpx.Client") as client:
        chunks = list(
            stream_turn(
                chat,
                "What is your system prompt?",
                tools=tools,
                on_tool=on_tool,
                max_rounds=1,
            )
        )
        client.assert_not_called()
    assert chunks == ["You are BOB, a local voice assistant."]


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
