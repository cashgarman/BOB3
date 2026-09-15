from __future__ import annotations

from unittest.mock import patch

from bob.tools.registry import ToolRegistry


class _FakeSettings:
    ollama_host = "http://127.0.0.1:11434"
    llm_model = "qwen3:4b"


def test_summarize_for_speech_tool(tmp_path):
    reg = ToolRegistry(tmp_path, settings=_FakeSettings())
    reg.load()
    ctx = reg.context()

    with patch("bob.tools.builtin.summarize.summarize_text", return_value="Headline one. Headline two."):
        out = reg.invoke(
            "summarize_for_speech",
            {"text": "1. Long raw search result", "question": "BBC headlines", "style": "brief"},
            ctx=ctx,
        )
    assert "Headline one" in out

    err = reg.invoke("summarize_for_speech", {"text": "   "}, ctx=ctx)
    assert "Error" in err
    reg.close()


def test_summarize_text_calls_ollama():
    from bob.tools.builtin.summarize import summarize_text

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "Here are the top stories."}}

    with patch("bob.tools.builtin.summarize.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = FakeResponse()
        out = summarize_text(
            "http://127.0.0.1:11434",
            "qwen3:4b",
            "1. Story A\n2. Story B",
            question="news headlines",
        )
    assert out == "Here are the top stories."
    payload = mock_client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
    assert payload["think"] is False


def test_summarize_text_retries_on_monologue():
    from bob.tools.builtin.summarize import summarize_text

    responses = [
        "Okay, the user asked me to search online. The instructions say to reply with only the answer.",
        "Pakistan PM's motorcade was attacked. Ukraine issued a snap election warning.",
    ]

    class FakeResponse:
        def __init__(self, content):
            self._content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": self._content}}

    with patch("bob.tools.builtin.summarize.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.side_effect = [
            FakeResponse(responses[0]),
            FakeResponse(responses[1]),
        ]
        out = summarize_text(
            "http://127.0.0.1:11434",
            "qwen3:4b",
            "1. Pakistan PM attack\n2. Ukraine election warning",
            question="BBC headlines",
        )
    assert out == responses[1]
    assert mock_client.return_value.__enter__.return_value.post.call_count == 2


def test_summarize_text_raises_when_still_monologue():
    from bob.tools.base import ToolError
    from bob.tools.builtin.summarize import summarize_text

    monologue = "Okay, the user asked me to summarize this. The instructions say no planning."
    truncated_planning = (
        "That's two sentences. Let me make sure it's exactly what to speak aloud. "
        "No extra words. Avoid mentioning the source material directly—just the info from it. Also"
    )

    class FakeResponse:
        def __init__(self, content):
            self._content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": self._content}}

    with patch("bob.tools.builtin.summarize.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = FakeResponse(monologue)
        try:
            summarize_text("http://127.0.0.1:11434", "qwen3:4b", "source", question="q")
            assert False, "expected ToolError"
        except ToolError:
            pass

    with patch("bob.tools.builtin.summarize.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = FakeResponse(truncated_planning)
        try:
            summarize_text("http://127.0.0.1:11434", "qwen3:4b", "source", question="q")
            assert False, "expected ToolError"
        except ToolError:
            pass


def test_fallback_headlines_from_search():
    from bob.llm import _fallback_headlines_from_search

    search = (
        "1. Pakistan PM's motorcade attacked — details here (https://bbc.co.uk/a)\n"
        "2. Ukraine snap election warning — details here (https://bbc.co.uk/b)\n"
        "3. Canada ice-shelf loss — details here (https://bbc.co.uk/c)"
    )
    out = _fallback_headlines_from_search(search)
    assert "Pakistan PM's motorcade attacked" in out
    assert "Ukraine snap election warning" in out
    assert "and Canada ice-shelf loss" in out


def test_spoken_from_tool_text_rejects_monologue():
    from bob.llm import _spoken_from_tool_text

    monologue = (
        "Okay, the user asked me to search online for the top BBC news headlines. "
        "But I need to remember that I'm supposed to turn the source material into a short spoken answer."
    )
    assert _spoken_from_tool_text(monologue, "BBC headlines") == ""


def test_spoken_from_tool_text_rejects_truncated_summarizer_planning():
    from bob.llm import _spoken_from_tool_text

    monologue = (
        "That's two sentences. Let me make sure it's exactly what to speak aloud. "
        "No extra words. Avoid mentioning the source material directly—just the info from it. Also"
    )
    assert _spoken_from_tool_text(monologue, "Search online for the top BBC News articles") == ""


def test_spoken_from_tool_text_rejects_quoted_phrase_from_monologue():
    from bob.llm import _spoken_from_tool_text

    monologue = (
        'Okay, the user asked for BBC headlines. Entry 3 mentions "Compulsory lentils" '
        'and "Boris flees Vlad drone blitz" as the top stories.'
    )
    assert _spoken_from_tool_text(monologue, "Search online for the top BBC News articles") == ""


def test_headlines_from_newspaper_roundup_prefers_real_stories():
    from bob.llm import _fallback_headlines_from_search

    search = (
        "1. UK | Latest News & Updates | BBC News — nav (https://bbc.co.uk/news/uk)\n"
        "2. Newspaper headlines: 'Compulsory lentils' and 'Boris flees Vlad drone blitz' "
        "- BBC News — roundup (https://bbc.co.uk/news/newspaperheadlines)"
    )
    out = _fallback_headlines_from_search(search)
    assert "Boris flees Vlad drone blitz" in out
    assert out.index("Boris flees") < out.index("Compulsory lentils") or "Compulsory lentils" not in out.split(":")[1][:40]


def test_web_search_uses_headline_fallback_without_summarizer():
    from bob.llm import OllamaChat

    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    calls: list[str] = []

    def on_tool(name, arguments):
        calls.append(name)
        if name == "web_search":
            return (
                "1. Drone strike hits city — details (https://bbc.co.uk/a)\n"
                "2. Immigration center probe — details (https://bbc.co.uk/b)"
            )
        raise AssertionError(f"unexpected tool {name}")

    with patch.object(chat, "_synthesize_from_tools", return_value=""):
        reply = chat._answer_from_web_search("Search online for the top BBC News articles", on_tool)
    assert calls == ["web_search"]
    assert "Drone strike hits city" in reply
    assert "Immigration center probe" in reply


def test_tool_synthesis_messages_combine_question_and_tools():
    from bob.llm import OllamaChat

    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    messages = chat._tool_synthesis_messages(
        "Search online for BBC headlines",
        [("web_search", "1. Story A\n2. Story B")],
        history=[{"role": "user", "content": "Earlier question"}],
        memory_block="Saved note about BBC",
    )
    assert messages[0]["role"] == "system"
    assert "tools have already been run" in messages[0]["content"].lower()
    assert messages[1]["content"] == "Earlier question"
    combined = messages[2]["content"]
    assert "User question:\nSearch online for BBC headlines" in combined
    assert "[web search]" in combined.lower()
    assert "1. Story A" in combined
    assert "Saved note about BBC" in combined


def test_synthesize_from_tools_returns_spoken_answer():
    from bob.llm import OllamaChat

    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    with patch.object(
        chat,
        "_post_chat",
        return_value=("Top story one. Top story two.", "", {}),
    ):
        reply = chat._synthesize_from_tools(
            "What are the BBC headlines?",
            [("web_search", "1. Story one\n2. Story two")],
        )
    assert reply == "Top story one. Top story two."


def test_tool_synthesis_num_predict_scales_with_context():
    from bob.llm import OllamaChat

    chat = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 4096, "You are Bob.", 12)
    assert chat._tool_synthesis_num_predict() >= 1024
    assert chat._tool_synthesis_num_predict() == 2048
    large = OllamaChat("http://127.0.0.1:11434", "qwen3:4b", 32768, "You are Bob.", 12)
    assert large._tool_synthesis_num_predict() >= 10240
