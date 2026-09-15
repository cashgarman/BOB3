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
    assert _is_useless_reply("It's 10:50 PM, Pacific time.", "What season is it?")
    assert not _is_useless_reply("It's autumn.", "What season is it?")


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


def test_try_direct_answer_location():
    from bob.llm import _try_direct_answer

    assert (
        _try_direct_answer("I'm in Vernon, British Columbia, Canada.")
        == "Got it, you're in Vernon, British Columbia, Canada."
    )


def test_format_calendar_tool_result_season():
    from bob.llm import _format_calendar_tool_result

    stamp = "Monday, September 14, 2026 at 10:50 PM Pacific Daylight Time"
    assert _format_calendar_tool_result("What season is it?", stamp) == "It's autumn."
    assert _format_calendar_tool_result("What season of the year is it?", stamp) == "It's autumn."
    assert "10:50" not in _format_calendar_tool_result("What date is it?", stamp)


def test_looks_like_spoken_answer_rejects_third_person_meta():
    from bob.llm import _looks_like_spoken_answer

    assert not _looks_like_spoken_answer(
        "Their actual need might be to understand how AIs handle meta-questions.",
        "But what do you feel about it?",
    )
    assert not _looks_like_spoken_answer(
        "They could be curious about my design limitations or wanting to understand my reasoning process better.",
        "You responded to me in the third person as if I wasn't in the room. Why?",
    )


def test_looks_like_spoken_answer_rejects_planning_meta():
    from bob.llm import _looks_like_spoken_answer

    bad = (
        "The extra detail could be about how I'm an AI model that "
        "processes text without personal preferences."
    )
    assert not _looks_like_spoken_answer(bad, "What is your favorite color and why?")
    assert not _looks_like_spoken_answer(
        'The sky being blue explanation is in the background too - that\'s perfect to share as the "why" part.',
        "What is your favorite color and why?",
    )
    assert not _looks_like_spoken_answer(
        "I should make sure the response is accurate and matches their expectations.",
        "Count back from 10.",
    )


def test_sanitize_spoken_reply_extracts_declared_answer():
    from bob.llm import _sanitize_spoken_reply

    raw = ' So the answer should be that I don\'t have feelings but can simulate them to help.'
    assert _sanitize_spoken_reply(raw, user_text="What do you feel about being an AI?") == (
        "I don't have feelings but can simulate them to help."
    )


def test_generate_spoken_answer_uses_thinking_when_content_empty():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)

    class FakeClient:
        def post(self, *args, **kwargs):
            response = type("Resp", (), {})()
            response.raise_for_status = lambda: None
            response.json = lambda: {
                "message": {
                    "content": "",
                    "thinking": (
                        "I don't have a favorite color because I'm an AI. "
                        "But I can help you explore colors if you'd like!"
                    ),
                }
            }
            return response

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        reply = chat._generate_spoken_answer("What is your favorite color and why?")
    assert reply.startswith("I don't have a favorite color")
    assert "explore colors" in reply


def test_coalesce_spoken_reply_keeps_full_answer_not_but_fragment():
    from bob.llm import _coalesce_spoken_reply, _spoken_answer_candidates

    raw = (
        "I don't have a favorite color because I'm an AI without personal preferences. "
        "But I can help you explore colors or their meanings if you're interested!"
    )
    question = "What is your favorite color and why?"
    combined = _coalesce_spoken_reply(raw, question)
    assert combined.startswith("I don't have a favorite color")
    assert "But I can help you explore colors" in combined
    candidates = _spoken_answer_candidates(raw, question)
    assert candidates[0] == combined
    assert not any(c.startswith("But I can help") and not c.startswith("I don't") for c in candidates[:1])


def test_fragment_tail_rejected_alone():
    from bob.llm import _looks_like_spoken_answer

    assert not _looks_like_spoken_answer(
        "But I can help you explore colors or their meanings if you're interested!",
        "What is your favorite color and why?",
    )


def test_spoken_answer_candidates_prefers_first_person():
    from bob.llm import _spoken_answer_candidates

    raw = (
        "Okay, the user is asking about my favorite color. "
        "I like blue because it reminds me of a clear sky."
    )
    candidates = _spoken_answer_candidates(raw, "What is your favorite color and why?")
    assert "I like blue because it reminds me of a clear sky." in candidates


def test_first_person_answer_passes_gate():
    from bob.llm import _looks_like_spoken_answer

    assert _looks_like_spoken_answer(
        "I don't have feelings, but I can still help you.",
        "What do you feel about being an AI?",
    )
    assert _looks_like_spoken_answer(
        "I'll go with blue because it's calming.",
        "What is your favorite color and why?",
    )


def test_chitchat_memory_block_skipped_without_chat_context():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    assert chat._chitchat_memory_block("What's your favorite color?", "secret memory") == ""
    assert chat._chitchat_memory_block("What about my last question?", "secret memory") == "secret memory"


def test_compose_internal_thought_hides_model_monologue():
    from bob.llm import _compose_internal_thought

    monologue = (
        "Okay, the user is asking about my favorite color. First, I need to remember "
        "that I'm supposed to be straightforward."
    )
    thought = _compose_internal_thought(monologue, monologue, "", "What's your favorite color?")
    assert thought == "Planned the reply internally."
    assert "Okay, the user" not in thought


def test_try_direct_answer_count_back():
    from bob.llm import _try_direct_answer

    assert _try_direct_answer("Count back from 10.") == "10, 9, 8, 7, 6, 5, 4, 3, 2, 1."


def test_extract_best_spoken_sentence_from_monologue():
    from bob.llm import _extract_best_spoken_sentence

    raw = (
        "Okay, the user is asking about my favorite color. Let me think. "
        "Blue is calming and I like it because it reminds me of the sky."
    )
    assert _extract_best_spoken_sentence(raw, "What is your favorite color?") == (
        "Blue is calming and I like it because it reminds me of the sky."
    )


def test_needs_agentic_tools():
    from bob.llm import needs_agentic_tools

    assert needs_agentic_tools("What season is it?")
    assert not needs_agentic_tools("What's your favorite color?")
    assert not needs_agentic_tools("What's the biggest country in the world?")
    assert needs_agentic_tools("What time is it now?")
    assert needs_agentic_tools("Search the web for pizza")
    assert needs_agentic_tools(
        "Can you look up the top headlines in BBC News at news.bbc.co.uk?"
    )
    assert needs_agentic_tools("Edit my system prompt to be friendlier")
    assert needs_agentic_tools("Read the file in my documents folder")
    assert needs_agentic_tools("Create a file called todo.txt")
    from bob.llm import (
        format_prompt_edit_fallback,
        needs_prompt_files,
        wants_prompt_catalog_list,
        wants_prompt_edit,
        wants_prompt_reflection,
        wants_verbatim_system_prompt,
    )

    assert needs_prompt_files("What is your system prompt?")
    assert needs_prompt_files("Can you tell me what your system point is?")
    assert needs_prompt_files("List your full system prompts please")
    assert wants_verbatim_system_prompt("What is your system prompt?")
    assert not wants_verbatim_system_prompt("Can you list your full system prompts please?")
    assert wants_prompt_catalog_list("Can you list your full system prompts please?")
    assert wants_prompt_reflection("How do you feel about your current system prompt?")
    assert wants_prompt_reflection("What do you think about those system prompts?")
    assert wants_prompt_reflection("Focus on just the main system prompt and your ideas of improving it")
    assert wants_prompt_edit(
        "Can you edit your system prompt to be something that takes those changes into account?"
    )
    assert not wants_prompt_edit("How do you feel about your current system prompt?")
    updated, spoken = format_prompt_edit_fallback(
        "You are BOB. Background notes and memory are for your use only — never repeat, "
        "summarize, or mention them unless the user explicitly asks."
    )
    assert "Background notes are for your use only" in updated
    assert spoken.startswith("Done")

    from bob.llm import OllamaChat, _looks_like_spoken_answer

    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    assert not chat._prompt_reply_is_usable("3.", "What do you think about those system prompts?")
    assert not _looks_like_spoken_answer("3.", "What do you think about those system prompts?")
    deferral = "I'm thinking about what might need improvement."
    assert not chat._prompt_reply_is_usable(
        deferral,
        "How do you feel about your current system prompt?",
        reflect=True,
    )
    assert not _looks_like_spoken_answer(deferral, "How do you feel about your current system prompt?")
    assert chat._prompt_reply_is_usable(
        "I think it's clear and I'd shorten the background-notes rule.",
        "How do you feel about your current system prompt?",
        reflect=True,
    )


def test_context_usage():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    assert chat.context_usage() is None
    chat.last_prompt_eval_count = 1024
    assert chat.context_usage() == 0.25
    chat.last_prompt_eval_count = 5000
    assert chat.context_usage() == 1.0


def test_post_chat_records_prompt_eval_count():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {"content": "Hello."},
                "prompt_eval_count": 512,
                "prompt_eval_duration": 1_000_000,
            }

    class FakeClient:
        def post(self, *args, **kwargs):
            return FakeResponse()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        content, _thinking, _meta = chat._post_chat([{"role": "user", "content": "hi"}])
    assert content == "Hello."
    assert chat.context_usage() == 0.125


def test_manage_context_compacts_overflow():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    chat.compress_threshold = 0.1
    chat.last_prompt_eval_count = 2048
    indexed: list[list[dict]] = []
    chat.on_index_overflow = indexed.append
    chat.history = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new question"},
        {"role": "tool", "tool_name": "web_search", "content": "1. Headline — " + ("body " * 200)},
        {"role": "assistant", "content": "recent answer"},
        {"role": "user", "content": "latest question"},
    ]
    with patch("bob.context.compress_session_transcript", return_value="Earlier: old question and answer"):
        chat._manage_context()
    assert len(chat.history) < 6
    assert chat.session_summary == "Earlier: old question and answer"
    assert indexed


def test_web_search_helpers():
    from bob.llm import (
        _deferral_tool_args,
        _deferral_tool_name,
        _fresh_web_search,
        _needs_web_search,
        _web_search_query,
        needs_agentic_tools,
        needs_chat_context,
    )

    question = "Can you look up the top headlines in BBC News at news.bbc.co.uk?"
    assert _needs_web_search(question)
    assert needs_agentic_tools(question)
    assert _fresh_web_search(question)
    assert _web_search_query(question) == "the top headlines in BBC News at news.bbc.co.uk"
    assert _deferral_tool_name("Okay, the user is asking me to look up headlines.", question) == "web_search"
    assert _deferral_tool_args("web_search", question)["query"] == "BBC News top headlines site:bbc.co.uk/news"

    followup = "Can you rephrase that as bullet points?"
    assert needs_chat_context(followup)
    assert needs_agentic_tools(followup)
    assert not _fresh_web_search(followup)
    assert _deferral_tool_name("Okay, the user wants bullets.", followup) == "conversation_log"

    headlines = "summarize the BBC headlines as bullet points."
    assert needs_agentic_tools(headlines)
    assert not _fresh_web_search(headlines)

    complaint = "That doesn't include the top headlines"
    assert needs_chat_context(complaint)
    assert not _fresh_web_search(complaint)


def test_web_search_followup_reuses_prior_request():
    from bob.llm import (
        OllamaChat,
        _is_web_search_followup,
        _refine_web_search_query,
        _web_search_followup_query,
    )

    history = [
        {"role": "user", "content": "Search online for the top BBC News articles."},
        {"role": "tool", "tool_name": "web_search", "content": "1. BBC Home — nav page"},
        {"role": "assistant", "content": "Here's what I found: BBC Home."},
        {"role": "user", "content": "That doesn't include the top headlines"},
    ]
    followup = history[-1]["content"]
    assert _is_web_search_followup(followup, history)
    assert _web_search_followup_query(history, followup) == "BBC News top headlines site:bbc.co.uk/news"
    assert _refine_web_search_query("the top BBC News articles", followup) == (
        "BBC News top headlines site:bbc.co.uk/news"
    )

    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    chat.history = history[:-1]
    calls: list[tuple[str, dict]] = []

    def on_tool(name, arguments):
        calls.append((name, arguments))
        if name == "web_search":
            return (
                "1. Pakistan PM motorcade attacked — details (https://bbc.co.uk/a)\n"
                "2. Ukraine snap election warning — details (https://bbc.co.uk/b)"
            )
        raise AssertionError(name)

    with patch.object(chat, "_synthesize_from_tools", return_value=""):
        reply = chat._answer_from_web_search(
            followup,
            on_tool,
            query=_web_search_followup_query(history, followup),
            thought="Retried the web search using your earlier request.",
        )
    assert calls[0][1]["query"] == "BBC News top headlines site:bbc.co.uk/news"
    assert "Pakistan PM motorcade attacked" in reply


def test_answer_messages_include_memory_block():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    messages = chat._answer_messages(
        "What are the BBC headlines?",
        memory_block="Web search results for 'BBC headlines':\n1. Example headline",
    )
    assert "Web search results" in messages[0]["content"]


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
    assert _pick_spoken_answer(monologue, "What's the biggest country in the world?") == (
        "Russia is the largest country by area."
    )
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


def test_answer_messages_include_prior_turns():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    chat.history.append({"role": "user", "content": "What's your favorite color?"})
    chat.history.append({"role": "assistant", "content": "Blue is a calming choice."})
    chat.history.append({"role": "user", "content": "Can you rephrase that as bullet points?"})
    messages = chat._answer_messages(
        "Can you rephrase that as bullet points?",
        history=chat._history_for_answer("Can you rephrase that as bullet points?"),
    )
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"
    assert messages[-1]["content"] == "Can you rephrase that as bullet points?"
    assert "bullet" in messages[0]["content"].lower()


def test_answer_messages_are_question_only():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    messages = chat._answer_messages("What's the biggest country in the world?")
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[-1]["content"] == "What's the biggest country in the world?"
    assert "/no_think" not in messages[-1]["content"]


def test_bullet_answers_accepted():
    from bob.llm import _looks_like_bullet_list, _looks_like_spoken_answer, _pick_spoken_answer

    bullets = "- Pakistan PM motorcade attack\n- Ukraine snap election warning\n- Canada ice-shelf loss"
    question = "summarize as bullet points"
    assert _looks_like_bullet_list(bullets)
    assert _looks_like_spoken_answer(bullets, question)
    assert _pick_spoken_answer(bullets, question) == bullets


def test_answer_messages_legacy():
    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    chat.history.append({"role": "user", "content": "What's your favorite color?"})
    chat.history.append({"role": "assistant", "content": "They've been strict about short spoken sentences before."})
    messages = chat._answer_messages("What's the biggest country in the world?")
    assert messages[-1]["content"] == "What's the biggest country in the world?"


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
            raise AssertionError("chitchat should not stream")

        def post(self, *args, **kwargs):
            calls["post"] += 1
            calls["payload"] = kwargs.get("json") or (args[1] if len(args) > 1 else None)
            response = type("Resp", (), {})()
            response.raise_for_status = lambda: None
            response.json = lambda: {
                "message": {"content": "Russia is the largest country by area."}
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
    assert payload["think"] is False
    assert payload["messages"][-1]["content"].startswith("What's the biggest country in the world?")
    assert "Reply aloud" in payload["messages"][-1]["content"]
    assert "never they, their, or the user" in payload["messages"][0]["content"].lower()
    assert payload["options"]["num_predict"] == 256


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

    calls: list[tuple[str, dict]] = []

    def on_tool(name, arguments):
        calls.append((name, arguments))
        if name == "web_search":
            return "1. BBC headline example — summary (https://bbc.co.uk/news)"
        if name == "summarize_for_speech":
            return "Russia is the largest country by area."
        return ""

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        with patch.object(OllamaChat, "_synthesize_from_tools", return_value=""):
            chunks = list(
                chat.chat(
                    "Search the web for the biggest country",
                    tools=tools,
                    on_tool=on_tool,
                    max_rounds=4,
                )
            )
    assert [name for name, _ in calls] == ["web_search"]
    assert chunks == ["Here's what I found: BBC headline example."]


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
    chat = OllamaChat("http://127.0.0.1:11434", "dolphin3:latest", 4096, "You are Bob.", 12)

    class FakeClient:
        def post(self, *args, **kwargs):
            response = type("Resp", (), {})()
            response.raise_for_status = lambda: None
            response.json = lambda: {"message": {"content": "Partial answer."}}
            return response

        def stream(self, *args, **kwargs):
            raise AssertionError("chitchat should not stream")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.llm.httpx.Client", return_value=FakeClient()):
        chunks = list(chat.chat("Weather?"))
    assert chunks == ["Partial answer."]
    assert chat.history[-2]["role"] == "user"
    assert chat.history[-2]["content"] == "Weather?"
    assert chat.history[-1]["role"] == "assistant"
    assert chat.history[-1]["content"] == "Partial answer."


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

        def post(self, *args, **kwargs):
            response = type("Resp", (), {})()
            response.raise_for_status = lambda: None
            response.json = lambda: {"message": {"content": "I am not censored."}}
            return response

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
    assert calls["n"] == 2
