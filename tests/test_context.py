from __future__ import annotations

from unittest.mock import patch

from bob.context import (
    compact_history,
    compact_tool_content,
    compress_session_transcript,
    fallback_compress_summary,
    pairs_from_messages,
    should_compress,
    transcript_lines,
)


def test_compact_web_search_keeps_titles_only():
    raw = "\n".join(
        [
            "1. Drone strike hits city — long body text about the event (https://bbc.com/a)",
            "2. Immigration center probe — another long body (https://bbc.com/b)",
        ]
    )
    compact = compact_tool_content("web_search", raw)
    assert "Drone strike hits city" in compact
    assert "Immigration center probe" in compact
    assert "long body text" not in compact
    assert len(compact) <= 320


def test_compact_history_only_shrinks_old_tool_messages():
    history = [
        {"role": "user", "content": "search news"},
        {"role": "tool", "tool_name": "web_search", "content": "1. Alpha — " + ("x" * 500)},
        {"role": "assistant", "content": "Here is the news."},
        {"role": "user", "content": "more please"},
        {"role": "tool", "tool_name": "web_search", "content": "1. Beta — " + ("y" * 500)},
    ]
    compacted = compact_history(history, keep_recent_tools=1)
    assert "Web search (compressed)" in compacted[1]["content"]
    assert len(compacted[1]["content"]) <= 320
    assert len(compacted[4]["content"]) > 320


def test_should_compress_uses_usage_and_char_fallback():
    history = [{"role": "user", "content": "x" * 5000}]
    assert should_compress(0.5, 0.4, history, 4096)
    assert not should_compress(0.2, 0.4, [{"role": "user", "content": "hi"}], 4096)
    assert should_compress(None, 0.4, history, 4096)


def test_fallback_compress_summary_keeps_tail():
    prior = "Earlier topic: weather."
    lines = ["User: hello", "BOB: hi there"]
    summary = fallback_compress_summary(prior, lines)
    assert "weather" in summary
    assert "hello" in summary


def test_compress_session_transcript_uses_ollama():
    with patch("bob.tools.builtin.summarize._post_ollama", return_value="- BBC headlines discussed"):
        summary = compress_session_transcript(
            "http://127.0.0.1:11434",
            "qwen3:4b",
            "Prior note",
            ["User: search BBC", "BOB: shared headlines"],
        )
    assert summary == "- BBC headlines discussed"


def test_pairs_from_messages_extracts_user_assistant():
    messages = [
        {"role": "user", "content": "Search BBC"},
        {"role": "tool", "tool_name": "web_search", "content": "1. Headline"},
        {"role": "assistant", "content": "Top story is X."},
        {"role": "user", "content": "More bullets"},
        {"role": "assistant", "content": "- one\n- two"},
    ]
    pairs = pairs_from_messages(messages)
    assert len(pairs) == 2
    assert pairs[0][0] == "Search BBC"
    assert pairs[0][1] == "Top story is X."
    assert "web_search" in pairs[0][2]


def test_transcript_lines_compacts_tool_entries():
    messages = [
        {"role": "tool", "tool_name": "web_search", "content": "1. Title — " + ("body " * 80)},
    ]
    lines = transcript_lines(messages)
    assert len(lines) == 1
    assert "Web search (compressed)" in lines[0]
