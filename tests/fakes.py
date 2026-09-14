from __future__ import annotations

from types import SimpleNamespace

from bob.settings import Settings


class FakeMemory:
    """In-memory stand-in for MemoryService used by the memories window and tools."""

    def __init__(self, rows: list[dict] | None = None, ready: bool = True) -> None:
        self.rows = [dict(row) for row in (rows or [])]
        self.ready = ready
        self.toggled: list[tuple[str, bool]] = []
        self.edited: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.forgot = 0

    def list_memories(self) -> list[dict]:
        return list(self.rows)

    def set_enabled(self, memory_id: str, enabled: bool) -> None:
        self.toggled.append((str(memory_id), bool(enabled)))
        for row in self.rows:
            if str(row.get("id")) == str(memory_id):
                row["enabled"] = bool(enabled)

    def edit(self, memory_id: str, text: str) -> None:
        self.edited.append((str(memory_id), text))
        for row in self.rows:
            if str(row.get("id")) == str(memory_id):
                row["text"] = text

    def delete(self, memory_id: str) -> None:
        self.deleted.append(str(memory_id))
        self.rows = [row for row in self.rows if str(row.get("id")) != str(memory_id)]

    def forget_all(self) -> None:
        self.forgot += 1
        self.rows = []

    def retrieve(self, query: str, limit: int = 8) -> str:
        needle = (query or "").lower()
        hits = [str(row.get("text") or "") for row in self.rows if needle in str(row.get("text") or "").lower()]
        return "\n".join(hits[: max(1, int(limit))]) if hits else ""


class FakeChat:
    def __init__(self, sessions: list[dict] | None = None) -> None:
        self._sessions = list(sessions or [])

    def list_sessions(self, limit: int = 8) -> list[dict]:
        return self._sessions[: int(limit)]


class FakeApp:
    """Minimal assistant surface for constructing and clicking the tray menu."""

    def __init__(self, sessions: list[dict] | None = None, models: list[tuple[str, bool]] | None = None) -> None:
        self.settings = Settings()
        self.calls: list[tuple] = []
        self._session_id = 0
        self.chat = FakeChat(sessions)
        self._models = models if models is not None else [("qwen2.5:latest", False), ("huge-model", True)]

    def apply_setting(self, field: str, value) -> None:
        if field == "theme":
            self.settings.theme = value
            self.settings.theme_overrides = {}
        else:
            setattr(self.settings, field, value)
        self.calls.append(("apply_setting", field, value))

    def set_overlay_visible(self, visible: bool) -> None:
        self.settings.show_overlay = bool(visible)
        self.calls.append(("set_overlay_visible", visible))

    def set_start_with_windows(self, enabled: bool) -> None:
        self.settings.start_with_windows = bool(enabled)
        self.calls.append(("set_start_with_windows", enabled))

    def open_main_ui(self) -> None:
        self.calls.append(("open_main_ui",))

    def toggle_listen(self) -> None:
        self.calls.append(("toggle_listen",))

    def stop_speaking(self) -> None:
        self.calls.append(("stop_speaking",))

    def _new_chat(self) -> None:
        self.calls.append(("new_chat",))

    def open_memories(self) -> None:
        self.calls.append(("open_memories",))

    def open_settings(self) -> None:
        self.calls.append(("open_settings",))

    def open_theme(self) -> None:
        self.calls.append(("open_theme",))

    def reconnect_ollama(self) -> None:
        self.calls.append(("reconnect_ollama",))

    def load_session(self, session_id: int) -> None:
        self._session_id = int(session_id)
        self.calls.append(("load_session", session_id))

    def quit(self) -> None:
        self.calls.append(("quit",))

    def _tray_models(self) -> list[tuple[str, bool]]:
        return list(self._models)


class FakeHotkey:
    def __init__(self, spec: str, callback) -> None:
        self.spec = spec
        self.callback = callback
        self.error = None
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


class ImmediateRecorder:
    """HotkeyRecorder stand-in: tests fire the capture callback themselves."""

    def __init__(self) -> None:
        self.callback = None
        self.stopped = False

    def start(self, callback) -> None:
        self.callback = callback

    def stop(self) -> None:
        self.stopped = True


def sample_memories() -> list[dict]:
    return [
        {"id": "a1", "text": "Likes green tea", "enabled": True, "updated": 1_700_000_000, "created": 1_700_000_000},
        {"id": "b2", "text": "Lives in Portland", "enabled": False, "updated": "bad", "created": 0},
        {"id": "c3", "text": "Has a cat named Pixel", "enabled": True, "updated": 1_700_000_100},
    ]
