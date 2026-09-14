from __future__ import annotations

from enum import Enum


class State(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    LOADING = "loading"
    ERROR = "error"
