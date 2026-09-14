from __future__ import annotations

import json
from unittest.mock import patch

from bob.llm import OllamaChat


def _run_round(chat: OllamaChat, payload_lines: list[dict]) -> tuple[list[str], str, list]:
    class FakeStream:
        is_error = False

        def read(self):
            return b""

        def iter_lines(self):
            for item in payload_lines:
                yield json.dumps(item)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeClient:
        def stream(self, *args, **kwargs):
            return FakeStream()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    spoken: list[str] = []
    chunks: list[str] = []
    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        gen = chat._round("system", [{"type": "function"}], None, spoken)
        while True:
            try:
                chunks.append(next(gen))
            except StopIteration as exc:
                return chunks, exc.value[0], exc.value[1]


def test_round_holds_back_text_when_tools_requested():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:8b", 4096, "You are Bob.", 12)
    chunks, content, calls = _run_round(
        chat,
        [
            {
                "message": {
                    "content": "Let me check that for you.",
                    "tool_calls": [{"function": {"name": "conversation_log", "arguments": "{}"}}],
                },
                "done": True,
            }
        ],
    )
    assert chunks == []
    assert "Let me check" in content
    assert calls


def test_round_holds_back_deferral_when_tools_offered():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:8b", 4096, "You are Bob.", 12)
    chunks, content, calls = _run_round_with_tools(
        chat,
        [{"message": {"content": "Let me check the conversation log for you."}, "done": True}],
    )
    assert chunks == []
    assert "Let me check" in content
    assert not calls


def _run_round_with_tools(chat: OllamaChat, payload_lines: list[dict]) -> tuple[list[str], str, list]:
    class FakeStream:
        is_error = False

        def read(self):
            return b""

        def iter_lines(self):
            for item in payload_lines:
                yield json.dumps(item)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeClient:
        def stream(self, *args, **kwargs):
            return FakeStream()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    spoken: list[str] = []
    chunks: list[str] = []
    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        gen = chat._round("system", [{"type": "function"}], None, spoken)
        while True:
            try:
                chunks.append(next(gen))
            except StopIteration as exc:
                return chunks, exc.value[0], exc.value[1]


def test_needs_conversation_log():
    from bob.llm import needs_conversation_log

    assert needs_conversation_log("What time was my first question in this conversation?")
    assert not needs_conversation_log("What is the weather today?")


def test_round_streams_non_preamble_while_tools_offered():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:8b", 4096, "You are Bob.", 12)
    chunks, content, calls = _run_round(
        chat,
        [
            {"message": {"content": "Two. "}, "done": False},
            {"message": {"content": "That's it."}, "done": True},
        ],
    )
    assert chunks == ["Two. ", "That's it."]
    assert content == "Two. That's it."
    assert not calls


def test_round_ignores_thinking_field():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:8b", 4096, "You are Bob.", 12)
    chunks, content, calls = _run_round(
        chat,
        [
            {"message": {"thinking": "long chain of thought", "content": ""}, "done": False},
            {"message": {"content": "Yes."}, "done": True},
        ],
    )
    assert chunks == ["Yes."]
    assert content == "Yes."
    assert not calls


def test_qwen3_payload_disables_think():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    captured: dict = {}

    class FakeStream:
        is_error = False

        def read(self):
            return b""

        def iter_lines(self):
            yield json.dumps({"message": {"content": "Hi."}, "done": True})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeClient:
        def stream(self, method, url, json=None):
            captured["payload"] = json
            return FakeStream()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    spoken: list[str] = []
    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        chat.history.append({"role": "user", "content": "Hello"})
        gen = chat._round("system", None, None, spoken)
        list(gen)
    payload = captured["payload"]
    assert payload["think"] is False
    assert payload["reasoning_effort"] == "none"
    assert str(payload["messages"][-1]["content"]).endswith("/no_think")
    assert chat.history[-1]["content"] == "Hello"


def test_round_yields_text_when_no_tools():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:8b", 4096, "You are Bob.", 12)
    chunks, content, calls = _run_round(
        chat,
        [{"message": {"content": "Hello there."}, "done": True}],
    )
    assert chunks == ["Hello there."]
    assert content == "Hello there."
    assert not calls


def test_round_yields_partial_on_cancel():
    import threading

    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:8b", 4096, "You are Bob.", 12)
    cancel = threading.Event()

    class FakeStream:
        is_error = False

        def read(self):
            return b""

        def iter_lines(self):
            yield json.dumps({"message": {"content": "Hello "}, "done": False})
            cancel.set()
            yield json.dumps({"message": {"content": "world."}, "done": True})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeClient:
        def stream(self, *args, **kwargs):
            return FakeStream()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    spoken: list[str] = []
    chunks: list[str] = []
    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        gen = chat._round("system", None, cancel, spoken)
        while True:
            try:
                chunks.append(next(gen))
            except StopIteration as exc:
                content, calls = exc.value
                break
    assert chunks == ["Hello "]
    assert content == "Hello "
    assert spoken == ["Hello "]
    assert not calls


def test_chat_keeps_partial_history_on_close():
    import threading

    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:8b", 4096, "You are Bob.", 12)
    cancel = threading.Event()

    class FakeStream:
        is_error = False

        def read(self):
            return b""

        def iter_lines(self):
            yield json.dumps({"message": {"content": "Partial answer"}, "done": True})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeClient:
        def stream(self, *args, **kwargs):
            return FakeStream()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        gen = chat.chat("Weather?", cancel=cancel)
        chunk = next(gen)
        assert chunk == "Partial answer"
        cancel.set()
        gen.close()
    assert chat.history[-2]["role"] == "user"
    assert chat.history[-2]["content"] == "Weather?"
    assert chat.history[-1]["role"] == "assistant"
    assert chat.history[-1]["content"] == "Partial answer"


def test_chat_falls_back_when_model_rejects_tools():
    chat = OllamaChat("http://127.0.0.1:11434", "dolphin3:latest", 4096, "You are Bob.", 12)
    tools = [{"type": "function", "function": {"name": "clock_now", "parameters": {}}}]
    calls = {"n": 0}

    class FakeStream:
        is_error = False

        def read(self):
            return b""

        def iter_lines(self):
            calls["n"] += 1
            if calls["n"] == 1:
                yield json.dumps(
                    {"error": "registry.ollama.ai/library/dolphin3:latest does not support tools"}
                )
                return
            yield json.dumps({"message": {"content": "I am not censored."}, "done": True})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeClient:
        def stream(self, *args, **kwargs):
            return FakeStream()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        chunks = list(chat.chat("Are you censored?", tools=tools, on_tool=lambda *_: "ok"))
        chunks2 = list(chat.chat("Thanks", tools=tools, on_tool=lambda *_: "ok"))
    assert chunks == ["I am not censored."]
    assert chat._tools_unsupported is True
    assert chunks2 == ["I am not censored."]
    assert calls["n"] == 3
