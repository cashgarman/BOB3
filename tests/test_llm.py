from __future__ import annotations

import json
from unittest.mock import patch

from bob.llm import OllamaChat


def _run_round(
    chat: OllamaChat,
    payload_lines: list[dict],
    tools: list[dict] | None = None,
) -> tuple[list[str], str, list]:
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
        gen = chat._round("system", tools, None, spoken)
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
        tools=[{"type": "function"}],
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
        tools=[{"type": "function"}],
    )
    assert chunks == []
    assert content == "Two. That's it."
    assert not calls


def test_round_holds_back_monologue_while_tools_offered():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:8b", 4096, "You are Bob.", 12)
    monologue = (
        "Okay, the user is asking for the current time in Vernon, British Columbia. "
        "Let me think about how to handle this."
    )
    chunks, content, calls = _run_round_with_tools(
        chat,
        [{"message": {"content": monologue}, "done": True}],
    )
    assert chunks == []
    assert monologue in content
    assert not calls


def test_is_internal_monologue():
    from bob.llm import _is_internal_monologue

    assert _is_internal_monologue("Okay, the user is asking for the time.")
    assert _is_internal_monologue("x" * 521)
    assert not _is_internal_monologue("x" * 250)
    assert not _is_internal_monologue("It is 3:15 PM Pacific.")
    assert not _is_internal_monologue("")


def test_chat_skips_monologue_tool_round():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [{"type": "function", "function": {"name": "get_current_time", "parameters": {}}}]
    with patch("bob.llm.httpx.Client") as client:
        chunks = list(
            chat.chat(
                "What time is it?",
                tools=tools,
                on_tool=lambda *_: "Monday, September 14, 2026 at 3:15 PM Pacific Daylight Time",
                max_rounds=1,
            )
        )
        client.assert_not_called()
    assert chunks == ["It's 3:15 PM, Pacific time."]
    assert chat.history[-1]["content"] == "It's 3:15 PM, Pacific time."


def test_compose_internal_thought_includes_filtered_monologue():
    from bob.llm import _compose_internal_thought

    raw = (
        "Okay, the user is asking for the current time. Let me think about how to handle this. "
        'Bob should say "It\'s 1:03 PM, Cash."'
    )
    thought = _compose_internal_thought("", raw, "It's 1:03 PM, Cash.", "What time is it?")
    assert thought == "Planned the reply internally."


def test_chat_records_internal_thought_callback():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [{"type": "function", "function": {"name": "get_current_time", "parameters": {}}}]
    seen: list[str] = []
    with patch("bob.llm.httpx.Client") as client:
        list(
            chat.chat(
                "What time is it now?",
                tools=tools,
                on_tool=lambda *_: "Monday, September 14, 2026 at 1:03 PM Pacific Daylight Time",
                on_thought=seen.append,
                max_rounds=1,
            )
        )
        client.assert_not_called()
    assert seen
    assert "get_current_time" in seen[-1].lower()
    assert chat.last_internal_thought


def test_sanitize_spoken_reply_extracts_quoted_answer():
    from bob.llm import _sanitize_spoken_reply

    raw = (
        'Okay, the user is asking for the current time. Bob should say "It\'s 1:03 PM, Cash." '
        "after calling the tool."
    )
    assert _sanitize_spoken_reply(raw) == "It's 1:03 PM, Cash."


def test_sanitize_spoken_reply_uses_time_tool_fallback():
    from bob.llm import _sanitize_spoken_reply

    history = [
        {"role": "tool", "tool_name": "get_current_time", "content": "Monday, September 14, 2026 at 1:03 PM Pacific Daylight Time"}
    ]
    raw = "Okay, the user is asking again. From the known information, Bob should call get_current_time."
    assert _sanitize_spoken_reply(raw, history, "What time is it?") == "It's 1:03 PM, Pacific time."


def test_sanitize_spoken_reply_skips_time_fallback_for_non_time_question():
    from bob.llm import _sanitize_spoken_reply

    history = [
        {"role": "tool", "tool_name": "get_current_time", "content": "Monday, September 14, 2026 at 6:31 PM Pacific Daylight Time"}
    ]
    raw = (
        "Okay, let me try to figure out what the user needs. They asked what's 10 times 42. "
        "From the known information, Bob should call get_current_time."
    )
    assert _sanitize_spoken_reply(raw, history, "What's 10 times 42?") == ""


def test_round_sanitizes_final_monologue():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    monologue = (
        'Okay, the user is asking for the current time. Bob should say "It\'s 1:03 PM, Cash."'
    )
    chunks, content, calls = _run_round(
        chat,
        [{"message": {"content": monologue}, "done": True}],
    )
    assert chunks == ["It's 1:03 PM, Cash."]
    assert content == "It's 1:03 PM, Cash."
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
    assert "/no_think" not in str(payload["messages"][-1]["content"]).lower()
    assert chat.history[-1]["content"] == "Hello"


def test_is_useless_reply_detects_echo():
    from bob.llm import _is_useless_reply

    assert _is_useless_reply("What time is it now? /no_think", "What time is it now?")
    assert not _is_useless_reply("It's 1:03 PM.", "What time is it now?")


def test_sanitize_spoken_reply_rejects_echo():
    from bob.llm import _sanitize_spoken_reply

    assert _sanitize_spoken_reply("What time is it now? /no_think", user_text="What time is it now?") == ""


def test_chat_time_question_uses_clock_directly():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [{"type": "function", "function": {"name": "get_current_time", "parameters": {}}}]
    with patch("bob.llm.httpx.Client") as client:
        chunks = list(
            chat.chat(
                "What time is it now?",
                tools=tools,
                on_tool=lambda *_: "Monday, September 14, 2026 at 1:03 PM Pacific Daylight Time",
                max_rounds=1,
            )
        )
        client.assert_not_called()
    assert chunks == ["It's 1:03 PM, Pacific time."]
    assert chat.history[-1]["content"] == "It's 1:03 PM, Pacific time."


def test_try_direct_answer_math():
    from bob.llm import _try_direct_answer

    assert _try_direct_answer("What's 10 times 42?") == "420"
    assert _try_direct_answer("What is 2 plus 2?") == "4"


def test_try_direct_answer_feeling():
    from bob.llm import _try_direct_answer

    assert _try_direct_answer("How are you feeling?") == "I'm doing well and ready to help."


def test_needs_agentic_tools():
    from bob.llm import needs_agentic_tools

    assert not needs_agentic_tools("What's your favorite color?")
    assert not needs_agentic_tools("What's the biggest country in the world?")
    assert needs_agentic_tools("What time is it now?")
    assert needs_agentic_tools("Search the web for pizza")


def test_looks_like_spoken_answer_rejects_instruction_echo():
    from bob.llm import _looks_like_spoken_answer

    assert not _looks_like_spoken_answer("No extra commentary.", "What's your favorite color?")
    assert not _looks_like_spoken_answer("Keep answers concise.", "What's your favorite color?")
    assert not _looks_like_spoken_answer(
        "I shouldn't repeat or mention background notes unless asked.",
        "How far is the moon?",
    )
    assert not _looks_like_spoken_answer(
        "But I must phrase it naturally and concisely.",
        "What's the biggest country in the world?",
    )
    assert not _looks_like_spoken_answer(
        "I need to respond as BOB, a local voice assistant, with one short natural sentence.",
        "How far is the moon?",
    )
    assert not _looks_like_spoken_answer(
        "First, I recall the average distance is about 384,400 kilometers.",
        "How far is the moon?",
    )
    assert not _looks_like_spoken_answer("It covers", "What's the biggest country?")
    assert _looks_like_spoken_answer(
        "The moon is about 384,400 kilometers away on average.",
        "How far is the moon?",
    )
    assert _looks_like_spoken_answer(
        "I don't have a favorite color—I'm a voice assistant! But I can help you pick the perfect color for your next creative project.",
        "What's your favorite color?",
    )
    assert not _looks_like_spoken_answer(
        "Since they want me to pretend I have a favorite color without overthinking, I'll pick one that's universally acceptable.",
        "What's your favorite color?",
    )
    assert not _looks_like_spoken_answer(
        'Better not add anything like "on average" or "varies".',
        "What's the distance from the moon to the earth?",
    )
    assert not _looks_like_spoken_answer(
        "They've been strict about short spoken sentences before.",
        "What's the biggest country in the world?",
    )
    assert not _looks_like_spoken_answer(
        "Best to pick the most universally accepted answer without caveats.",
        "What's the largest fruit there is?",
    )


def test_pick_spoken_answer_rejects_planning_sentences():
    from bob.llm import _pick_spoken_answer

    monologue = (
        "Okay, the user is asking about the biggest country in the world. "
        "They've been strict about short spoken sentences before. "
        "Russia is the largest country by area."
    )
    assert _pick_spoken_answer(monologue, "What's the biggest country in the world?") == ""
    assert (
        _pick_spoken_answer(
            'Hmm, Bob should say "I like blue."',
            "What's your favorite color?",
        )
        == "I like blue."
    )
    assert not _pick_spoken_answer(
        "Keep answers concise. Background notes are for your use only.",
        "What's your favorite color?",
    )


def test_answer_messages_are_question_only():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    chat.history.append({"role": "user", "content": "What's your favorite color?"})
    chat.history.append({"role": "assistant", "content": "They've been strict about short spoken sentences before."})
    messages = chat._answer_messages("What's the biggest country in the world?")
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[-1]["content"] == "What's the biggest country in the world?"
    assert "/no_think" not in messages[-1]["content"]


def test_looks_complete_answer():
    from bob.llm import _looks_complete_answer

    assert _looks_complete_answer("420")
    assert _looks_complete_answer("Russia is the largest country by area.")
    assert not _looks_complete_answer("It covers")
    assert not _looks_complete_answer("I recall that BO")


def test_recover_reply_rejects_instruction_echo():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)

    class FakeClient:
        def post(self, *args, **kwargs):
            response = type("Resp", (), {})()
            response.raise_for_status = lambda: None
            response.json = lambda: {
                "message": {
                    "content": (
                        'Hmm, the user wants my favorite color. No extra commentary. '
                        'Bob should say "I like blue."'
                    )
                }
            }
            return response

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        reply = chat._recover_reply("What's your favorite color?")
    assert reply == "I like blue."


def test_recover_reply_rejects_incomplete_fragment():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)

    class FakeClient:
        def post(self, *args, **kwargs):
            response = type("Resp", (), {})()
            response.raise_for_status = lambda: None
            response.json = lambda: {
                "message": {
                    "content": (
                        "Hmm, the user is asking about the biggest country. "
                        "It covers Russia being the largest country by land area."
                    )
                }
            }
            return response

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        reply = chat._recover_reply("What's the biggest country in the world?")
    assert reply == "Sorry, I didn't get that."


def test_chat_general_question_skips_tool_rounds():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [{"type": "function", "function": {"name": "get_current_time", "parameters": {}}}]
    calls = {"stream": 0, "post": 0}

    class FakeClient:
        def stream(self, *args, **kwargs):
            calls["stream"] += 1
            raise AssertionError("thinking-model general Q&A should not stream")

        def post(self, *args, **kwargs):
            calls["post"] += 1
            calls["payload"] = kwargs.get("json") or (args[1] if len(args) > 1 else None)
            response = type("Resp", (), {})()
            response.raise_for_status = lambda: None
            response.json = lambda: {
                "message": {
                    "thinking": "The user asked a trivia question.",
                    "content": "Russia is the largest country by area.",
                }
            }
            return response

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        chunks = list(
            chat.chat(
                "What's the biggest country in the world?",
                tools=tools,
                on_tool=lambda *_: "unused",
                max_rounds=4,
            )
        )
    assert chunks == ["Russia is the largest country by area."]
    assert calls["stream"] == 0
    assert calls["post"] == 1
    payload = calls["payload"]
    assert payload["think"] is True
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]
    assert payload["messages"][-1]["content"] == "What's the biggest country in the world?"


def test_chat_force_final_for_agentic_question():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]
    monologue = "Okay, the user wants a web search." + (" x" * 200)
    streams = [
        [{"message": {"content": monologue}, "done": True}],
        [{"message": {"content": "Russia is the largest country by area."}, "done": True}],
    ]

    class FakeStream:
        is_error = False

        def __init__(self, lines):
            self._lines = lines

        def read(self):
            return b""

        def iter_lines(self):
            for line in self._lines:
                yield json.dumps(line)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeClient:
        def __init__(self):
            self._i = 0

        def stream(self, *args, **kwargs):
            payload = streams[min(self._i, len(streams) - 1)]
            self._i += 1
            return FakeStream(payload)

        def post(self, *args, **kwargs):
            response = type("Resp", (), {})()
            response.raise_for_status = lambda: None
            response.json = lambda: {"message": {"content": "Sorry, I didn't get that."}}
            return response

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        chunks = list(
            chat.chat(
                "Search the web for the biggest country",
                tools=tools,
                on_tool=lambda *_: "unused",
                max_rounds=4,
            )
        )
    assert chunks == ["Russia is the largest country by area."]


def test_chat_recovers_from_monologue_tool_round():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    tools = [{"type": "function", "function": {"name": "get_current_time", "parameters": {}}}]
    monologue = "Okay, the user is asking what's 10 times 42. Let me think about the tools." + (" x" * 200)

    class FakeStream:
        is_error = False

        def read(self):
            return b""

        def iter_lines(self):
            yield json.dumps({"message": {"content": monologue}, "done": True})

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
        chunks = list(
            chat.chat(
                "What's 10 times 42?",
                tools=tools,
                on_tool=lambda *_: "unused",
                max_rounds=4,
            )
        )
    assert chunks == ["420"]


def test_chat_recovers_from_echo():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)

    class FakeStream:
        is_error = False

        def read(self):
            return b""

        def iter_lines(self):
            yield json.dumps({"message": {"content": "How are you feeling?"}, "done": True})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeClient:
        def stream(self, *args, **kwargs):
            return FakeStream()

        def post(self, *args, **kwargs):
            response = type("Resp", (), {})()
            response.raise_for_status = lambda: None
            response.json = lambda: {"message": {"content": "I'm doing well, thanks for asking."}}
            return response

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        chunks = list(chat.chat("How are you feeling?", tools=None, on_tool=None))
    assert chunks == ["I'm doing well and ready to help."]
    assert chat.history[-1]["content"] == "I'm doing well and ready to help."


def test_round_holds_streamed_think_tags():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:8b", 4096, "You are Bob.", 12)
    chunks, content, calls = _run_round(
        chat,
        [
            {"message": {"content": "<think>"}, "done": False},
            {"message": {"content": "Okay, the user is asking if I can hear them."}, "done": False},
            {"message": {"content": "</think>\nYes, Cash. Ready to help."}, "done": True},
        ],
    )
    assert "".join(chunks).strip() == "Yes, Cash. Ready to help."
    assert content == "Yes, Cash. Ready to help."
    assert not calls


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
    assert chunks == ["Hello"]
    assert content == "Hello"
    assert spoken == ["Hello"]
    assert not calls


def test_chat_keeps_partial_history_on_close():
    import threading

    chat = OllamaChat("http://127.0.0.1:11434", "dolphin3:latest", 4096, "You are Bob.", 12)
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
