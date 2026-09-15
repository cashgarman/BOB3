from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))

from bootstrap_models import STAGES, _download_kokoro, _is_retryable_error, _retry
from install_progress import format_bytes, write_progress


def test_format_bytes():
    assert format_bytes(512).endswith("B")
    assert "GB" in format_bytes(2 * 1024 * 1024 * 1024)


def test_write_progress(tmp_path, monkeypatch):
    path = tmp_path / "progress.json"
    monkeypatch.setenv("BOB_INSTALL_PROGRESS", str(path))
    write_progress(phase="pip", message="Installing", overall=0.5, stage=0.2, completed=10, total=20)
    text = path.read_text(encoding="utf-8")
    assert "Installing" in text
    assert "0.5" in text


def test_stage_list_covers_ollama_and_verify():
    assert STAGES[0] == "ollama"
    assert STAGES[1] == "llm"
    assert STAGES[-1] == "verify"
    assert len(STAGES) == 8


def test_retryable_hf_errors():
    assert _is_retryable_error(RuntimeError("Server disconnected without sending a response."))
    assert not _is_retryable_error(ValueError("bad model name"))


def test_retry_reraises_after_exhausted_attempts():
    calls = {"n": 0}

    def fail() -> None:
        calls["n"] += 1
        raise RuntimeError("Server disconnected without sending a response.")

    try:
        _retry("test", fail, attempts=2)
    except Exception as exc:
        assert "test failed" in str(exc)
    else:
        raise AssertionError("expected failure")
    assert calls["n"] == 2


def test_parakeet_ready_requires_vocab(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from bob.stt_parakeet import parakeet_model_ready

    dest = tmp_path / "parakeet"
    dest.mkdir()
    (dest / "config.json").write_text("{}", encoding="utf-8")
    assert not parakeet_model_ready(dest)
    (dest / "vocab.txt").write_text("a", encoding="utf-8")
    assert parakeet_model_ready(dest)


def test_bootstrap_skips_existing_kokoro(tmp_path, monkeypatch):
    dest = tmp_path / "kokoro"
    dest.mkdir()
    onnx = dest / "kokoro-v1.0.onnx"
    voices = dest / "voices-v1.0.bin"
    onnx.write_bytes(b"x" * 2_000_000)
    voices.write_bytes(b"x" * 2_000_000)
    called = []

    def fail_download(*args, **kwargs):
        called.append(1)
        raise AssertionError("should not download")

    monkeypatch.setattr("bootstrap_models.urllib.request.urlretrieve", fail_download)
    _download_kokoro(dest, lambda c, t, n: None)
    assert not called
