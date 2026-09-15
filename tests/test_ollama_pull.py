from __future__ import annotations

import json

import httpx
import pytest

from bob.ollama_pull import OllamaPullError, has_model, pull_model


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, lines=None):
        self.status_code = status_code
        self._payload = payload or {}
        self._lines = lines or []
        self._body = json.dumps(payload) if payload is not None else ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._payload

    def read(self):
        return self._body.encode("utf-8")

    def iter_lines(self):
        yield from self._lines

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeClient:
    def __init__(self, get_response, stream_response=None):
        self._get = get_response
        self._stream = stream_response or get_response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        return self._get

    def stream(self, method, url, json=None):
        return self._stream


def test_has_model_matches_tags(monkeypatch):
    tags = _FakeResponse(payload={"models": [{"name": "qwen3:4b"}]})
    monkeypatch.setattr("bob.ollama_pull.httpx.Client", lambda **kwargs: _FakeClient(tags))
    assert has_model("http://127.0.0.1:11434", "qwen3:4b")
    assert not has_model("http://127.0.0.1:11434", "llama3.1")


def test_pull_skips_when_present(monkeypatch):
    tags = _FakeResponse(payload={"models": [{"name": "qwen3:4b"}]})
    monkeypatch.setattr("bob.ollama_pull.httpx.Client", lambda **kwargs: _FakeClient(tags))
    seen = []
    pull_model("http://127.0.0.1:11434", "qwen3:4b", on_progress=lambda c, t, s: seen.append((c, t, s)))
    assert seen
    assert "already" in seen[-1][2]


def test_pull_streams_bytes(monkeypatch):
    empty = _FakeResponse(payload={"models": []})
    present = _FakeResponse(payload={"models": [{"name": "qwen3:4b"}]})
    stream = _FakeResponse(
        lines=[
            json.dumps({"status": "downloading", "completed": 50, "total": 100}),
            json.dumps({"status": "success"}),
        ]
    )
    calls = {"n": 0}

    def client(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeClient(empty)
        if calls["n"] == 2:
            return _FakeClient(empty, stream)
        return _FakeClient(present)

    monkeypatch.setattr("bob.ollama_pull.httpx.Client", client)
    progress = []
    pull_model("http://127.0.0.1:11434", "qwen3:4b", on_progress=lambda c, t, s: progress.append((c, t, s)))
    assert any(item[0] == 50 and item[1] == 100 for item in progress)


def test_pull_raises_on_error_event(monkeypatch):
    empty = _FakeResponse(payload={"models": []})
    stream = _FakeResponse(lines=[json.dumps({"error": "disk full"})])
    calls = {"n": 0}

    def client(**kwargs):
        calls["n"] += 1
        return _FakeClient(empty, stream)

    monkeypatch.setattr("bob.ollama_pull.httpx.Client", client)
    with pytest.raises(OllamaPullError, match="disk full"):
        pull_model("http://127.0.0.1:11434", "qwen3:4b")
