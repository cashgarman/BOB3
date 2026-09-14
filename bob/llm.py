from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

log = logging.getLogger(__name__)

LARGE_MODEL_BYTES = 6 * 1024 * 1024 * 1024


def _ollama_error(exc: Exception, model: str) -> str:
    """Turn httpx/Ollama failures into something a user can act on."""
    if isinstance(exc, httpx.HTTPStatusError):
        return _ollama_error_body(exc.response.text, model) or str(exc)
    if isinstance(exc, RuntimeError):
        text = str(exc)
        parsed = _ollama_error_body(text, model)
        if parsed:
            return parsed
    return str(exc)


def _ollama_error_body(raw: str, model: str) -> str | None:
    msg: str | None = None
    if raw.strip():
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = raw.strip()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
            elif isinstance(err, str):
                msg = err
        elif isinstance(body, str):
            msg = body
    if isinstance(msg, str) and msg.strip():
        text = msg.strip()
        if "not found" in text.lower():
            return (
                f"Ollama model '{model}' is not installed ({text}). "
                f"Run: ollama pull {model} — or pick another model in Bob's tray menu."
            )
        return text
    return None
# Streaming replies: never hang forever on a dead socket, but allow a slow
# first token while Ollama pages the model in.
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
TOOL_GUIDANCE = (
    "You can call tools. Use one only when it gives you something you cannot know on your own, "
    "such as the current time or the user's saved notes. "
    "When the user's feelings or the news call for it, call set_speech_mood first "
    "(calm, warm, upbeat, excited, serious, sad, sorry, whisper, hurried) and then answer; "
    "never say the mood name aloud. "
    "Never read tool names, arguments, or JSON aloud: once a tool returns, just say the answer "
    "in a short spoken sentence."
)


class OllamaChat:
    def __init__(self, host: str, model: str, num_ctx: int, system_prompt: str, max_turns: int) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.history: list[dict[str, Any]] = []
        self.session_summary = ""
        self._summary_lock = threading.Lock()
        self.last_prompt_eval_count: int | None = None
        self.last_prompt_eval_ms: float | None = None
        self.last_eval_count: int | None = None
        self.last_eval_ms: float | None = None
        self.last_ttft_ms: float | None = None

    def ping(self) -> None:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{self.host}/api/tags")
            r.raise_for_status()

    def list_models(self) -> list[dict]:
        # Called while building the tray menu, so keep the worst case short.
        with httpx.Client(timeout=3.0) as client:
            r = client.get(f"{self.host}/api/tags")
            r.raise_for_status()
            return list(r.json().get("models") or [])

    def is_large_model(self, name: str) -> bool:
        for item in self.list_models():
            model_name = item.get("name") or item.get("model") or ""
            if model_name == name or model_name.startswith(name):
                return int(item.get("size") or 0) > LARGE_MODEL_BYTES
        return False

    def snapshot(self) -> tuple[list[dict[str, Any]], str]:
        return [dict(msg) for msg in self.history], self.session_summary

    def restore(self, history: list[dict[str, Any]], summary: str) -> None:
        self.history = [dict(msg) for msg in history]
        self.session_summary = summary

    def _thinks(self) -> bool:
        return "qwen3" in (self.model or "").lower()

    def _apply_think(self, payload: dict[str, Any]) -> None:
        if self._thinks():
            payload["think"] = False

    def _system(self, with_tools: bool = False) -> str:
        parts = [self.system_prompt.strip()]
        if with_tools:
            parts.append(TOOL_GUIDANCE)
        return "\n\n".join(p for p in parts if p)

    def _user_with_context(self, user_text: str, memory_block: str = "") -> str:
        parts: list[str] = []
        if self.session_summary.strip():
            parts.append(f"Session so far:\n{self.session_summary.strip()}")
        if (memory_block or "").strip():
            parts.append(memory_block.strip())
        parts.append(user_text or " ")
        return "\n\n".join(parts)

    def preload(self, tools: list[dict[str, Any]] | None = None) -> None:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": self._system(with_tools=bool(tools))}],
            "stream": False,
            "keep_alive": -1,
            "options": {"num_ctx": self.num_ctx, "num_predict": 1},
        }
        self._apply_think(payload)
        if tools:
            payload["tools"] = tools
        with httpx.Client(timeout=180.0) as client:
            r = client.post(f"{self.host}/api/chat", json=payload)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(_ollama_error(exc, self.model)) from exc

    def reset(self) -> None:
        self.history.clear()
        self.session_summary = ""

    def generate(self, instruction: str, user_text: str, num_predict: int = 256) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": user_text or " "},
            ],
            "stream": False,
            "keep_alive": -1,
            # Same num_ctx as chat(): a different value makes Ollama tear down
            # and reload the model (seconds of latency plus VRAM churn) on
            # every memory-extraction or summary call.
            "options": {"num_ctx": self.num_ctx, "num_predict": num_predict, "temperature": 0.2},
        }
        self._apply_think(payload)
        with httpx.Client(timeout=120.0) as client:
            r = client.post(f"{self.host}/api/chat", json=payload)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(_ollama_error(exc, self.model)) from exc
            return ((r.json().get("message") or {}).get("content") or "").strip()

    def chat(
        self,
        user_text: str,
        memory_block: str = "",
        tools: list[dict[str, Any]] | None = None,
        on_tool: Callable[[str, Any], str] | None = None,
        cancel: threading.Event | None = None,
        max_rounds: int = 1,
    ) -> Iterator[str]:
        """Stream a spoken reply, running any tool the model asks for first."""
        spoken_user = user_text
        self.history.append({"role": "user", "content": self._user_with_context(user_text, memory_block)})
        self._trim()
        agentic = bool(tools) and on_tool is not None
        system = self._system(with_tools=agentic)
        tool_rounds = max(1, int(max_rounds)) if agentic else 0
        try:
            for index in range(tool_rounds + 1):
                if cancel is not None and cancel.is_set():
                    return
                # The last pass drops the tools so the model has to answer in words.
                offered = tools if index < tool_rounds else None
                spoken: list[str] = []
                try:
                    content, calls = yield from self._round(system, offered, cancel, spoken)
                except GeneratorExit:
                    # Caller stopped consuming (barge-in / hotkey). Keep what was
                    # already said so the next turn knows what Bob got through.
                    partial = "".join(spoken).strip()
                    if partial:
                        self.history.append({"role": "assistant", "content": partial})
                    raise
                if content.strip() or calls:
                    message: dict[str, Any] = {"role": "assistant", "content": content}
                    if calls:
                        message["tool_calls"] = calls
                    self.history.append(message)
                if not calls:
                    break
                for call in calls:
                    if cancel is not None and cancel.is_set():
                        return
                    function = call.get("function") or {}
                    name = str(function.get("name") or "").strip()
                    if not name:
                        continue
                    try:
                        result = on_tool(name, function.get("arguments"))
                    except Exception as exc:
                        result = f"Error: tool '{name}' failed: {exc}"
                    self.history.append({"role": "tool", "tool_name": name, "content": result})
            self._trim()
        finally:
            self._rewrite_last_user(spoken_user)

    def _rewrite_last_user(self, spoken: str) -> None:
        """Keep history as the words the user said so memory is not duplicated next turn."""
        for msg in reversed(self.history):
            if msg.get("role") == "user":
                msg["content"] = spoken
                return

    def _record_eval(self, data: dict[str, Any]) -> None:
        count = data.get("prompt_eval_count")
        dur = data.get("prompt_eval_duration")
        self.last_prompt_eval_count = int(count) if count is not None else None
        self.last_prompt_eval_ms = (float(dur) / 1e6) if dur is not None else None
        ntok = data.get("eval_count")
        edur = data.get("eval_duration")
        self.last_eval_count = int(ntok) if ntok is not None else None
        self.last_eval_ms = (float(edur) / 1e6) if edur is not None else None

    def _round(
        self,
        system: str,
        tools: list[dict[str, Any]] | None,
        cancel: threading.Event | None,
        spoken: list[str] | None = None,
    ) -> Iterator[str]:
        """Stream one request. Returns (content, tool_calls) to the caller.

        Every chunk handed to the caller is also appended to `spoken` so an
        interrupted reply can still be recorded.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *self.history],
            "stream": True,
            "keep_alive": -1,
            "options": {
                "num_ctx": self.num_ctx,
                "temperature": 0.7,
            },
        }
        self._apply_think(payload)
        if tools:
            payload["tools"] = tools
        parts: list[str] = []
        calls: list[dict[str, Any]] = []
        speaking = False
        first_token = True
        t0 = time.perf_counter()
        with httpx.Client(timeout=STREAM_TIMEOUT) as client:
            with client.stream("POST", f"{self.host}/api/chat", json=payload) as resp:
                if resp.is_error:
                    detail = resp.read().decode("utf-8", errors="replace")
                    parsed = _ollama_error_body(detail, self.model)
                    raise RuntimeError(parsed or f"Ollama HTTP {resp.status_code}")
                for line in resp.iter_lines():
                    if cancel is not None and cancel.is_set():
                        break
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("error"):
                        raise RuntimeError(str(data["error"]))
                    message = data.get("message") or {}
                    requested = message.get("tool_calls") or []
                    if requested:
                        calls.extend(requested)
                    chunk = message.get("content") or ""
                    if chunk:
                        parts.append(chunk)
                        # Text before a tool call is a preamble, not the answer.
                        if speaking or not calls:
                            speaking = True
                            if first_token:
                                self.last_ttft_ms = (time.perf_counter() - t0) * 1000.0
                                first_token = False
                            if spoken is not None:
                                spoken.append(chunk)
                            yield chunk
                    if data.get("done"):
                        self._record_eval(data)
                        break
        return "".join(parts), calls

    def _trim(self) -> None:
        max_msgs = max(2, self.max_turns * 2)
        if len(self.history) <= max_msgs:
            return
        keep = self.history[-max_msgs:]
        # A tool result without the assistant turn that asked for it confuses Ollama.
        while keep and keep[0].get("role") == "tool":
            keep.pop(0)
        self.history, overflow = keep, self.history[: len(self.history) - len(keep)]
        self._fold_summary(overflow)

    def _fold_summary(self, overflow: list[dict[str, Any]]) -> None:
        """Fold trimmed history into the rolling summary on a background thread.

        This used to run synchronously inside chat(), so once the history hit
        max_turns every single reply waited on an extra LLM round-trip.
        """
        lines = [_transcript_line(msg) for msg in overflow]
        lines = [line for line in lines if line]
        if not lines:
            return
        threading.Thread(target=self._fold_worker, args=(lines,), name="summary", daemon=True).start()

    def _fold_worker(self, lines: list[str]) -> None:
        # Serialize folds so each one builds on the previous summary.
        with self._summary_lock:
            blob = "\n".join(([self.session_summary] if self.session_summary else []) + lines)[:4000]
            try:
                summary = self.generate(
                    "Summarize this conversation for later turns in 2-3 short spoken sentences. "
                    "Keep names, preferences, and unfinished tasks. No markdown.",
                    blob,
                    num_predict=120,
                )
                if summary:
                    self.session_summary = summary
            except Exception as exc:
                log.warning("Session summary failed: %s", exc)
                self.session_summary = blob[-600:]


def _transcript_line(msg: dict[str, Any]) -> str:
    role = msg.get("role")
    content = str(msg.get("content") or "").strip()
    if role == "user":
        return f"User: {content}"
    if role == "tool":
        return f"Tool {msg.get('tool_name') or 'result'}: {content}"
    used = [str((call.get("function") or {}).get("name") or "") for call in msg.get("tool_calls") or []]
    used = [name for name in used if name]
    if content and used:
        return f"Bob: {content} (used {', '.join(used)})"
    if used:
        return f"Bob used {', '.join(used)}"
    return f"Bob: {content}"
