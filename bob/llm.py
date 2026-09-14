from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator
from typing import Any

import httpx

log = logging.getLogger(__name__)

LARGE_MODEL_BYTES = 6 * 1024 * 1024 * 1024
# Streaming replies: never hang forever on a dead socket, but allow a slow
# first token while Ollama pages the model in.
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
TOOL_GUIDANCE = (
    "You can call tools. Use one only when it gives you something you cannot know on your own, "
    "such as the current time or the user's saved notes. Never read tool names, arguments, or JSON "
    "aloud: once a tool returns, just say the answer in a short spoken sentence."
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

    def preload(self) -> None:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.system_prompt}],
            "stream": False,
            "keep_alive": -1,
            "options": {"num_ctx": self.num_ctx, "num_predict": 1},
        }
        with httpx.Client(timeout=180.0) as client:
            r = client.post(f"{self.host}/api/chat", json=payload)
            r.raise_for_status()

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
        with httpx.Client(timeout=120.0) as client:
            r = client.post(f"{self.host}/api/chat", json=payload)
            r.raise_for_status()
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
        self.history.append({"role": "user", "content": user_text})
        self._trim()
        agentic = bool(tools) and on_tool is not None
        system = self._system_with_memory(memory_block, with_tools=agentic)
        tool_rounds = max(1, int(max_rounds)) if agentic else 0
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
        if tools:
            payload["tools"] = tools
        parts: list[str] = []
        calls: list[dict[str, Any]] = []
        speaking = False
        with httpx.Client(timeout=STREAM_TIMEOUT) as client:
            with client.stream("POST", f"{self.host}/api/chat", json=payload) as resp:
                resp.raise_for_status()
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
                            if spoken is not None:
                                spoken.append(chunk)
                            yield chunk
                    if data.get("done"):
                        break
        return "".join(parts), calls

    def _system_with_memory(self, memory_block: str, with_tools: bool = False) -> str:
        parts = [self.system_prompt.strip()]
        if with_tools:
            parts.append(TOOL_GUIDANCE)
        if self.session_summary.strip():
            parts.append(f"Session so far:\n{self.session_summary.strip()}")
        if memory_block.strip():
            parts.append(memory_block.strip())
        return "\n\n".join(parts)

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
