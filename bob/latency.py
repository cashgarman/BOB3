from __future__ import annotations

import logging
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

MARK_ORDER = ("endpoint", "stt", "llm_ttft", "tts_pcm", "audio_out")


class TurnTimer:
    """One speech turn: milliseconds from endpoint to first audio out."""

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.marks: dict[str, float] = {"endpoint": 0.0}
        self.extra: dict[str, str] = {}
        self._logged = False

    def mark(self, name: str) -> None:
        if name in self.marks:
            return
        self.marks[name] = (time.perf_counter() - self.t0) * 1000.0

    def note(self, key: str, value) -> None:
        if value is None or value == "":
            return
        self.extra[key] = str(value)

    def line(self) -> str:
        parts = [f"{name}={self.marks[name]:.0f}ms" for name in MARK_ORDER if name in self.marks]
        extra = [f"{key}={value}" for key, value in self.extra.items()]
        return "turn " + " ".join(parts + extra)

    def log(self) -> None:
        if self._logged:
            return
        self._logged = True
        log.info("%s", self.line())

    def callback(self, name: str) -> Callable[[], None]:
        def _cb() -> None:
            self.mark(name)
            if name == "audio_out":
                self.log()

        return _cb
