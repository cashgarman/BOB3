from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bob.voice_mood import DEFAULT_MOOD, parse_mood

MAX_RESULT_CHARS = 8000
_NAME_OK = re.compile(r"[^A-Za-z0-9_-]")


class ToolError(Exception):
    """Raised by a tool when its arguments or environment are unusable."""


def _silent(_message: str) -> None:
    return None


@dataclass
class ToolContext:
    """Everything a tool may need from Bob. Never shown to the model."""

    cancel: threading.Event = field(default_factory=threading.Event)
    settings: Any = None
    memory: Any = None
    data_dir: Path = Path("data")
    status: Callable[[str], None] = _silent
    _mood: str = DEFAULT_MOOD
    _on_mood: Callable[[str], None] = _silent

    @property
    def cancelled(self) -> bool:
        return self.cancel.is_set()

    @property
    def mood(self) -> str:
        """Canonical mood that will colour this turn's spoken reply."""
        return self._mood

    def set_mood(self, mood: str) -> str:
        """Change how Bob speaks the rest of this turn. Unknown names raise ToolError."""
        name = parse_mood(mood)
        if name is None:
            from bob.voice_mood import MOOD_NAMES

            raise ToolError(f"unknown mood {mood!r}. Use one of: {', '.join(MOOD_NAMES)}")
        self._mood = name
        self._on_mood(name)
        return name


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[dict[str, Any], ToolContext], Any]
    source: str = "sdk"

    @property
    def is_mcp(self) -> bool:
        return self.source.startswith("mcp")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


def sanitize_name(name: str) -> str:
    """Ollama tool names allow letters, digits, underscore and dash only."""
    cleaned = _NAME_OK.sub("_", str(name or "").strip())
    return cleaned.strip("_") or "tool"


def parse_arguments(raw: Any) -> dict[str, Any]:
    """Models sometimes hand back a JSON string instead of an object."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def clip_result(value: Any) -> str:
    if value is None:
        text = "done"
    elif isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = str(value)
    text = text.strip() or "done"
    if len(text) > MAX_RESULT_CHARS:
        return text[:MAX_RESULT_CHARS] + " … (truncated)"
    return text
