from __future__ import annotations

from collections.abc import Callable

from PIL import Image, ImageDraw
import pystray

from bob.ui.settings_dialog import COMPUTE, STT_MODELS, VOICES, WAKE_WORDS


def _icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(17, 19, 24, 255), outline=(52, 211, 153, 255), width=4)
    draw.ellipse((24, 22, 40, 42), fill=(52, 211, 153, 255))
    draw.rectangle((30, 40, 34, 52), fill=(52, 211, 153, 255))
    return img


class Tray:
    def __init__(self, app) -> None:
        self.app = app
        self.icon = pystray.Icon("bob", _icon_image(), "Bob", self._menu())

    def _settings(self):
        return self.app.settings

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
            bool_item("Show overlay", "show_overlay", self.app.set_overlay_visible),
            pystray.MenuItem("New conversation", lambda *_: self.app._new_chat()),
            pystray.MenuItem("Memories…", lambda *_: self.app.open_memories()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Voice",
                pystray.Menu(
                    pystray.MenuItem("Input device", pystray.Menu(*input_items)),
                    pystray.MenuItem("Output device", pystray.Menu(*output_items)),
                    pystray.MenuItem("TTS voice", pystray.Menu(*[radio("tts_voice", v) for v in VOICES])),
                    bool_item("Wake word enabled", "wake_word_enabled"),
                    pystray.MenuItem("Wake word", pystray.Menu(*[radio("wake_word", w) for w in WAKE_WORDS])),
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

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass
