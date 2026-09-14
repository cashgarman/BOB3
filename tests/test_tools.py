from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from bob.tools.base import ToolContext, ToolError, clip_result, parse_arguments, sanitize_name
from bob.tools.registry import ToolRegistry, declared_tools, tool
from bob.tools.schema import spec_from_function
from tests.fakes import FakeMemory


def test_sanitize_parse_clip():
    assert sanitize_name("Bad Name!") == "Bad_Name"
    assert parse_arguments('{"a": 1}') == {"a": 1}
    assert parse_arguments("not-json") == {}
    assert parse_arguments({"x": 2}) == {"x": 2}
    assert clip_result(None) == "done"
    assert clip_result({"a": 1}) == '{"a": 1}'
    long = "x" * 9000
    assert clip_result(long).endswith("… (truncated)")


def test_spec_from_function_and_context_injection(tmp_path: Path):
    def greet(name: str, excited: bool = False, *, ctx: ToolContext) -> str:
        """Greet someone.

        Args:
            name: Who to greet.
            excited: Whether to shout.
        """
        ctx.status("greeting")
        text = f"Hello, {name}"
        return text.upper() if excited else text

    spec = spec_from_function(greet)
    assert spec.name == "greet"
    assert "name" in spec.parameters["properties"]
    assert "ctx" not in spec.parameters["properties"]
    assert "name" in spec.parameters["required"]

    statuses = []
    ctx = ToolContext(data_dir=tmp_path, status=statuses.append)
    assert spec.run({"name": "Bob", "excited": True}, ctx) == "HELLO, BOB"
    assert statuses == ["greeting"]


def test_tool_registry_load_builtins_and_invoke(tmp_path: Path):
    reg = ToolRegistry(tmp_path, settings=None, memory=FakeMemory([{"id": "1", "text": "likes tea"}]))
    names = reg.load()
    assert "get_current_time" in names
    assert "conversation_log" in names
    assert "notes_read" in names
    assert "set_speech_mood" in names
    assert "memory_search" in names

    ctx = reg.context()
    clock = reg.invoke("get_current_time", {}, ctx=ctx)
    assert "at" in clock.lower() or ":" in clock

    notes = reg.invoke("notes_write", {"text": "buy milk", "append": False}, ctx=ctx)
    assert "Notes" in notes or "notes" in notes.lower()
    assert (tmp_path / "notes.md").read_text(encoding="utf-8").strip() == "buy milk"
    assert "buy milk" in reg.invoke("notes_read", {}, ctx=ctx)

    mood = reg.invoke("set_speech_mood", {"mood": "excited"}, ctx=ctx)
    assert "excited" in mood.lower()
    assert ctx.mood == "excited"
    assert "Available voice moods" in reg.invoke("list_speech_moods", {}, ctx=ctx)

    with patch("webbrowser.open", return_value=True):
        opened = reg.invoke("open_url", {"url": "https://example.com/path"}, ctx=ctx)
    assert "example.com" in opened
    assert "Error" in reg.invoke("open_url", {"url": "ftp://bad"}, ctx=ctx)
    assert "Error" in reg.invoke("missing_tool", {}, ctx=ctx)
    reg.close()


def test_conversation_log_tool(tmp_path: Path):
    from bob.chat_store import ChatStore

    store = ChatStore(tmp_path / "chat.db")
    sid = store.current_session()
    store.add_message(sid, "user", "What is the weather today?")
    store.add_message(sid, "assistant", "Sunny.")

    reg = ToolRegistry(tmp_path)
    reg.load()
    ctx = reg.context(chat=store, session_id=sid)
    out = reg.invoke("conversation_log", {"limit": 5}, ctx=ctx)
    assert "What is the weather today?" in out
    assert "User:" in out
    assert "Bob:" in out
    store.close()
    reg.close()


def test_tool_registry_plugin_and_memory_search(tmp_path: Path):
    plugin = tmp_path / "tools" / "hello_plugin.py"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(
        "from bob.tools import tool\n"
        "@tool\n"
        "def plugin_ping() -> str:\n"
        '    """Ping from plugin."""\n'
        '    return "plugin-pong"\n',
        encoding="utf-8",
    )
    memory = FakeMemory([{"id": "1", "text": "favorite color is green"}])
    reg = ToolRegistry(tmp_path, memory=memory)
    reg.load()
    assert "plugin_ping" in reg.names()
    assert reg.invoke("plugin_ping", {}) == "plugin-pong"
    found = reg.invoke("memory_search", {"query": "color", "limit": 3})
    assert "green" in found
    offline = ToolRegistry(tmp_path, memory=FakeMemory(ready=False))
    offline.load()
    assert "Error" in offline.invoke("memory_search", {"query": "x"})
    reg.close()
    offline.close()


def test_tool_decorator_declared(tmp_path: Path):
    @tool
    def local_only() -> str:
        """Local tool for registry declaration."""
        return "ok"

    names = {spec.name for spec in declared_tools()}
    assert "local_only" in names


def test_tool_context_set_mood():
    seen = []
    ctx = ToolContext(_on_mood=seen.append)
    assert ctx.set_mood("calm") == "calm"
    assert seen == ["calm"]
    with pytest.raises(ToolError):
        ctx.set_mood("not-real")
