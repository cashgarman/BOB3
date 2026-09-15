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

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": monologue}}

    with patch("bob.tools.builtin.summarize.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = FakeResponse()
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
