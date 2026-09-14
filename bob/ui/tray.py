from __future__ import annotations

import threading
from collections.abc import Callable

from PIL import Image
import pystray

from bob.state import State
from bob.ui.settings_dialog import COMPUTE, STT_MODELS, VOICES, WAKE_WORDS
from bob.ui.theme import PRESET_KEYS, PRESETS
from bob.ui.tray_icon import (
    ACCENT,
    animation_frames,
    frame_interval_ms,
    render_icon,
    tray_title,
    uses_animation,
)
from bob.voice_mood import MOOD_NAMES


def _icon_image() -> Image.Image:
    from bob.win32_app import icon_path

    path = icon_path()
    if path.is_file():
        img = Image.open(path)
        img.load()
        return img.convert("RGBA")
    return render_icon(State.IDLE)


class Tray:
    def __init__(self, app) -> None:
        self.app = app
        self._state = State.LOADING
        self._detail = ""
        self._anim_frames: list[Image.Image] = animation_frames(State.LOADING)
        self._anim_index = 0
        self._anim_after_id: str | None = None
        self._lock = threading.Lock()
        self.icon = pystray.Icon(
            "bob",
            render_icon(State.LOADING, 0),
            tray_title(State.LOADING),
            self._menu(),
        )

    def _settings(self):
        return self.app.settings

    def _schedule(self, fn: Callable[[], None]) -> None:
        overlay = getattr(self.app, "overlay", None)
        if overlay is None:
            fn()
            return
        try:
            overlay.after(0, fn)
        except Exception:
            fn()

    def _cancel_animation_timer(self) -> None:
        overlay = getattr(self.app, "overlay", None)
        if overlay is None or self._anim_after_id is None:
            self._anim_after_id = None
            return
        try:
            overlay.after_cancel(self._anim_after_id)
        except Exception:
            pass
        self._anim_after_id = None

    def _apply_icon(self, image: Image.Image, title: str) -> None:
        try:
            self.icon.title = title
            self.icon.icon = image
        except Exception:
            pass

    def _animation_tick(self) -> None:
        with self._lock:
            if not uses_animation(self._state):
                self._anim_after_id = None
                return
            self._anim_index = (self._anim_index + 1) % max(1, len(self._anim_frames))
            image = self._anim_frames[self._anim_index]
            title = tray_title(self._state, self._detail)
            state = self._state
            interval = frame_interval_ms(state)

        self._apply_icon(image, title)

        overlay = getattr(self.app, "overlay", None)
        if overlay is None or not uses_animation(state):
            return

        def schedule_next() -> None:
            with self._lock:
                if self._state is not state or not uses_animation(self._state):
                    self._anim_after_id = None
                    return
                self._anim_after_id = overlay.after(interval, self._animation_tick)

        self._schedule(schedule_next)

    def set_state(self, state: State, detail: str = "") -> None:
        with self._lock:
            self._state = state
            self._detail = detail or ""
            self._cancel_animation_timer()
            title = tray_title(state, self._detail)

            if uses_animation(state):
                self._anim_frames = animation_frames(state)
                self._anim_index = 0
                image = self._anim_frames[0]
                interval = frame_interval_ms(state)
            else:
                self._anim_frames = []
                self._anim_index = 0
                image = render_icon(state)

        def apply() -> None:
            self._apply_icon(image, title)
            if uses_animation(state):
                overlay = getattr(self.app, "overlay", None)
                if overlay is not None:
                    with self._lock:
                        self._anim_after_id = overlay.after(interval, self._animation_tick)

        self._schedule(apply)

    def _chat_items(self) -> list[pystray.MenuItem]:
        items: list[pystray.MenuItem] = []
        try:
            current = int(getattr(self.app, "_session_id", 0) or 0)
            for row in self.app.chat.list_sessions(8):
                title = (row.get("title") or "Untitled").strip() or "Untitled"
                if len(title) > 42:
                    title = title[:41] + "…"
                count = int(row.get("count") or 0)
                shown = f"{title}  ({count})" if count else title
                sid = int(row["id"])
                items.append(
                    pystray.MenuItem(
                        shown,
                        lambda *_, session=sid: self.app.load_session(session),
                        checked=lambda _, session=sid: current == session,
                    )
                )
        except Exception:
            pass
        if not items:
            items.append(pystray.MenuItem("No saved chats", None, enabled=False))
        return items

    def _menu(self) -> pystray.Menu:
        s = self._settings()

        def radio(field: str, value, label: str | None = None):
            shown = label or str(value)
            return pystray.MenuItem(
                shown,
                lambda *_ , f=field, v=value: self.app.apply_setting(f, v),
                checked=lambda _, f=field, v=value: str(getattr(self._settings(), f)) == str(v),
            )

        def bool_item(title: str, field: str, apply: Callable | None = None):
            def click(*_):
                new = not bool(getattr(self._settings(), field))
                if apply:
                    apply(new)
                else:
                    self.app.apply_setting(field, new)

            return pystray.MenuItem(
                title,
                click,
                checked=lambda _, f=field: bool(getattr(self._settings(), f)),
            )

        llm_items = []
        try:
            for name, large in self.app._tray_models():
                label = f"{name}  (too big for 10GB)" if large else name
                llm_items.append(radio("llm_model", name, label))
        except Exception:
            llm_items.append(pystray.MenuItem("No Ollama models", None, enabled=False))
        if not llm_items:
            llm_items.append(pystray.MenuItem("No Ollama models", None, enabled=False))

        input_items = [radio("input_device", "", "System default")]
        output_items = [radio("output_device", "", "System default")]
        try:
            from bob.audio import list_devices

            for name in list_devices("input")[:16]:
                input_items.append(radio("input_device", name))
            for name in list_devices("output")[:16]:
                output_items.append(radio("output_device", name))
        except Exception:
            pass

        return pystray.Menu(
            pystray.MenuItem("Open Bob", lambda *_: self.app.open_main_ui(), default=True),
            pystray.MenuItem("Toggle listen", lambda *_: self.app.toggle_listen()),
            pystray.MenuItem("Stop talking", lambda *_: self.app.stop_speaking()),
            bool_item("Show overlay", "show_overlay", self.app.set_overlay_visible),
            pystray.MenuItem("New conversation", lambda *_: self.app._new_chat()),
            pystray.MenuItem("Conversations", pystray.Menu(*self._chat_items())),
            pystray.MenuItem("Memories…", lambda *_: self.app.open_memories()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Voice",
                pystray.Menu(
                    pystray.MenuItem("Input device", pystray.Menu(*input_items)),
                    pystray.MenuItem("Output device", pystray.Menu(*output_items)),
                    pystray.MenuItem("TTS voice", pystray.Menu(*[radio("tts_voice", v) for v in VOICES])),
                    pystray.MenuItem(
                        "Speech mood",
                        pystray.Menu(*[radio("tts_mood", m) for m in MOOD_NAMES]),
                    ),
                    pystray.MenuItem(
                        "TTS speed",
                        pystray.Menu(
                            radio("tts_speed", 0.8, "0.8×"),
                            radio("tts_speed", 1.0, "1.0×"),
                            radio("tts_speed", 1.2, "1.2×"),
                            radio("tts_speed", 1.4, "1.4×"),
                        ),
                    ),
                    bool_item("Wake word enabled", "wake_word_enabled"),
                    pystray.MenuItem("Wake word", pystray.Menu(*[radio("wake_word", w) for w in WAKE_WORDS])),
                    bool_item("Auto-endpoint", "auto_endpoint"),
                    bool_item("Voice barge-in", "barge_in"),
                    pystray.MenuItem("Hotkey…", lambda *_: self.app.open_settings()),
                ),
            ),
            pystray.MenuItem(
                "Models",
                pystray.Menu(
                    pystray.MenuItem("LLM", pystray.Menu(*llm_items)),
                    pystray.MenuItem("STT model", pystray.Menu(*[radio("stt_model", m) for m in STT_MODELS])),
                    pystray.MenuItem("STT compute", pystray.Menu(*[radio("stt_compute_type", c) for c in COMPUTE])),
                    pystray.MenuItem(
                        "Context",
                        pystray.Menu(
                            radio("llm_num_ctx", 2048, "2048"),
                            radio("llm_num_ctx", 4096, "4096"),
                            radio("llm_num_ctx", 8192, "8192"),
                        ),
                    ),
                    pystray.MenuItem("Reconnect Ollama", lambda *_: self.app.reconnect_ollama()),
                ),
            ),
            pystray.MenuItem(
                "Memory",
                pystray.Menu(
                    bool_item("Autosave", "memory_autosave"),
                    pystray.MenuItem(
                        "Max facts",
                        pystray.Menu(
                            radio("memory_max_inject", 4, "4"),
                            radio("memory_max_inject", 8, "8"),
                            radio("memory_max_inject", 12, "12"),
                        ),
                    ),
                    pystray.MenuItem("Memories…", lambda *_: self.app.open_memories()),
                ),
            ),
            pystray.MenuItem(
                "Startup",
                pystray.Menu(bool_item("Start with Windows", "start_with_windows", self.app.set_start_with_windows)),
            ),
            pystray.MenuItem(
                "Appearance",
                pystray.Menu(
                    *[radio("theme", key, PRESETS[key].title) for key in PRESET_KEYS],
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Customize…", lambda *_: self.app.open_theme()),
                ),
            ),
            pystray.MenuItem("All settings…", lambda *_: self.app.open_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda *_: self.app.quit()),
        )

    def refresh(self) -> None:
        try:
            self.icon.menu = self._menu()
            self.icon.update_menu()
        except Exception:
            pass

    def run_detached(self) -> None:
        self.icon.run_detached()

    def notify(self, message: str, title: str = "Bob") -> None:
        """Show an OS balloon/toast from the tray icon."""
        if not getattr(self.icon, "HAS_NOTIFICATION", False):
            return
        text = (message or "").strip()
        if not text:
            return
        try:
            self.icon.notify(text[:250], (title or "Bob")[:60])
        except Exception:
            pass

    def stop(self) -> None:
        self._cancel_animation_timer()
        try:
            self.icon.stop()
        except Exception:
            pass


__all__ = ["Tray", "_icon_image", "ACCENT"]
