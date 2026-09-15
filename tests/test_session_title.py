from __future__ import annotations

from unittest.mock import patch

from bob.session_title import fallback_session_title, generate_session_title, sanitize_session_title


def test_sanitize_session_title_strips_quotes_and_prefix():
    assert sanitize_session_title('  "BBC News Headlines"  ') == "BBC News Headlines"
    assert sanitize_session_title("Title: Morning briefing") == "Morning briefing"
    assert sanitize_session_title("Output only the title please") == ""


def test_fallback_session_title_truncates():
    title = fallback_session_title("x" * 120)
    assert len(title) == 80
    assert title.startswith("x")


def test_generate_session_title_uses_llm_and_fallback():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '"Kitchen sink repair"'}}

    class FakeClient:
        def post(self, *args, **kwargs):
            return FakeResponse()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("bob.session_title.httpx.Client", return_value=FakeClient()):
        title = generate_session_title("http://127.0.0.1:11434", "qwen3:4b", "fix my sink", "Try a wrench.")
    assert title == "Kitchen sink repair"

    class BoomClient:
        def __enter__(self):
            raise RuntimeError("offline")

        def __exit__(self, *args):
            return False

    with patch("bob.session_title.httpx.Client", return_value=BoomClient()):
        title = generate_session_title("http://127.0.0.1:11434", "qwen3:4b", "fix my sink", "Try a wrench.")
    assert title == "fix my sink"
