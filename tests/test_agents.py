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


def test_regex_gate_rejects_empty_draft():
    """The gate node is now only a structural check; semantic rejection is the judge's job."""
    runtime = TurnRuntime(llm=OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12))
    token = set_runtime(runtime)
    try:
        out = regex_gate_node(
            {
                "user_text": "What time is it?",
                "draft": "",
                "spoken": "",
            }
        )
    finally:
        reset_runtime(token)
    assert out["gate_ok"] is False


def test_speaker_node_retries_then_falls_back_when_judge_rejects_twice(monkeypatch):
    """Regression test for this conversation's exact bad replies.

    Both generation attempts are judged unsafe, so the speaker node must
    fall back to a safe canned reply instead of ever speaking either draft.
    """
    from bob.agents.nodes.speaker import speaker_node

    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    bad_replies = iter(
        [
            "We are in the middle of a conversation. I've been working on your code all night.",
            "Since I am an AI, but in this role I am BOB (a character), I should be consistent with the persona.",
        ]
    )
    monkeypatch.setattr(chat, "_generate_spoken_answer", lambda *a, **k: next(bad_replies))
    monkeypatch.setattr(chat, "_judge_reply", lambda question, reply: (False, "narrates its own reasoning"))

    runtime = TurnRuntime(llm=chat)
    token = set_runtime(runtime)
    try:
        out = speaker_node(
            {
                "user_text": "I'm really tired. I've been working on your code all night.",
                "memory_block": "",
            }
        )
    finally:
        reset_runtime(token)
    assert out["judge_ok"] is False
    assert out["used_fallback"] is True
    assert out["gate_ok"] is True
    assert out["spoken"] not in {
        "We are in the middle of a conversation. I've been working on your code all night.",
        "Since I am an AI, but in this role I am BOB (a character), I should be consistent with the persona.",
    }
    assert chat.history[-1]["content"] == out["spoken"]


def test_speaker_node_uses_judge_approved_draft():
    from bob.agents.nodes.speaker import speaker_node

    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    with patch.object(chat, "_generate_spoken_answer", return_value="That sounds exhausting — thanks for pushing through."):
        with patch.object(chat, "_judge_reply", return_value=(True, "")) as judge:
            runtime = TurnRuntime(llm=chat)
            token = set_runtime(runtime)
            try:
                out = speaker_node({"user_text": "I've been working on your code all night.", "memory_block": ""})
            finally:
                reset_runtime(token)
    judge.assert_called_once()
    assert out["judge_ok"] is True
    assert out["used_fallback"] is False
    assert out["spoken"] == "That sounds exhausting — thanks for pushing through."
    assert chat.history[-1]["content"] == "That sounds exhausting — thanks for pushing through."


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

    with patch("bob.llm.httpx.Client") as client:
        chunks = list(
            stream_turn(
                chat,
                "What do you think about your system prompt?",
                tools=tools,
                on_tool=on_tool,
                max_rounds=1,
            )
        )
        client.assert_not_called()
    assert chunks
    assert chunks[0].startswith("I think")


def test_choose_route_prompt_edit_followup():
    history = [
        {
            "role": "user",
            "content": "How do you feel about your current system prompt? Is there anything you would change?",
        },
        {
            "role": "assistant",
            "content": (
                "I think it's clear about keeping answers short and natural for voice. "
                "If I changed one thing, I'd trim the background-notes warning slightly."
            ),
        },
    ]
    assert choose_route(
        "Go ahead and make those changes.",
        thinks=True,
        has_tools=True,
        tools_unsupported=False,
        history=history,
    ) == ("tools", "prompts")


def test_stream_turn_prompt_edit_followup():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    chat.history = [
        {
            "role": "user",
            "content": "How do you feel about your current system prompt? Is there anything you would change?",
        },
        {
            "role": "assistant",
            "content": (
                "I think it's clear about keeping answers short and natural for voice. "
                "If I changed one thing, I'd trim the background-notes warning slightly."
            ),
        },
    ]
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

    with patch("bob.llm.httpx.Client") as client:
        chunks = list(
            stream_turn(
                chat,
                "Go ahead and make those changes.",
                tools=tools,
                on_tool=on_tool,
                max_rounds=1,
            )
        )
        client.assert_not_called()
    assert writes
    assert "Background notes are for your use only" in writes[0]
    assert chunks == ["Done — I trimmed the background-notes rule in my system prompt."]


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
    """The deterministic direct-answer shortcut needs no LLM call to produce the reply.

    It still gets routed through the validator's judge once (an existing
    `_is_useless_reply` echo heuristic flags this specific phrasing as an
    echo of the user's location), so the judge call is mocked to approve it.
    """
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    with patch.object(OllamaChat, "_judge_reply", return_value=(True, "")):
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
