"""Download an Ollama model through the local HTTP API with byte progress."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

ProgressFn = Callable[[int | None, int | None, str], None]


class OllamaPullError(RuntimeError):
    """Raised when the Ollama daemon cannot pull a model."""


def list_local_models(host: str, timeout: float = 5.0) -> list[str]:
    url = host.rstrip("/") + "/api/tags"
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        items = response.json().get("models") or []
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model") or ""
        if name:
            names.append(str(name))
    return names


def has_model(host: str, model: str, timeout: float = 5.0) -> bool:
    needle = (model or "").strip().lower()
    if not needle:
        return False
    try:
        names = list_local_models(host, timeout=timeout)
    except Exception:
        return False
    for name in names:
        lower = name.lower()
        if lower == needle or lower.startswith(needle + ":") or needle.startswith(lower + ":"):
            return True
        if lower.split(":")[0] == needle.split(":")[0] and lower == needle:
            return True
        if lower == needle or name == model:
            return True
    return any(_same_model(name, model) for name in names)


def ping(host: str, timeout: float = 3.0) -> bool:
    try:
        list_local_models(host, timeout=timeout)
        return True
    except Exception:
        return False


def pull_model(
    host: str,
    model: str,
    on_progress: ProgressFn | None = None,
    *,
    timeout: float = 3600.0,
) -> None:
    """Stream POST /api/pull. on_progress(completed_bytes, total_bytes, status)."""
    name = (model or "").strip()
    if not name:
        raise OllamaPullError("No Ollama model name given.")
    if has_model(host, name):
        if on_progress:
            on_progress(1, 1, f"{name} already installed")
        return

    url = host.rstrip("/") + "/api/pull"
    completed: int | None = None
    total: int | None = None
    last_status = "pulling"
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
        with client.stream("POST", url, json={"name": name, "stream": True}) as response:
            if response.status_code >= 400:
                body = response.read().decode("utf-8", errors="replace")
                raise OllamaPullError(_error_text(body, name, response.status_code))
            for line in response.iter_lines():
                if not line:
                    continue
                event = _parse_event(line)
                if event is None:
                    continue
                err = event.get("error")
                if err:
                    raise OllamaPullError(str(err))
                status = str(event.get("status") or last_status)
                last_status = status
                if event.get("completed") is not None:
                    completed = int(event["completed"])
                if event.get("total") is not None:
                    total = int(event["total"])
                if on_progress:
                    on_progress(completed, total, status)
                if status.lower() in {"success", "complete"}:
                    break

    if not has_model(host, name, timeout=10.0):
        raise OllamaPullError(f"Ollama finished pulling '{name}' but the model is not listed yet.")
    if on_progress:
        on_progress(total or completed or 1, total or completed or 1, "success")


def _same_model(left: str, right: str) -> bool:
    a = (left or "").strip().lower()
    b = (right or "").strip().lower()
    if a == b:
        return True
    if a.split(":")[0] == b and ":" not in b:
        return True
    if b.split(":")[0] == a and ":" not in a:
        return True
    return False


def _parse_event(line: str) -> dict[str, Any] | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _error_text(body: str, model: str, status: int) -> str:
    try:
        payload = json.loads(body)
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            err = err.get("message")
        if err:
            return f"Ollama could not pull '{model}': {err}"
    except json.JSONDecodeError:
        pass
    text = (body or "").strip() or f"HTTP {status}"
    return f"Ollama could not pull '{model}': {text}"
