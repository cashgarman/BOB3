from __future__ import annotations

import logging
import queue
import threading
import time

from bob.audio import AudioHub, list_devices
from bob.chat_store import ChatStore
from bob.hotkeys import GlobalHotkey
from bob.llm import OllamaChat
from bob.memory.service import MemoryService
from bob.settings import DATA_DIR, MODELS_DIR, Settings, load_settings
from bob.state import State
from bob.startup import is_enabled as startup_is_enabled
from bob.startup import set_enabled as startup_set_enabled
from bob.stt import create_speech_to_text
from bob.stt_stream import StreamingTranscriber
from bob.tools import ToolRegistry
from bob.tts import TextToSpeech
from bob.tts_stream import SpeechStreamer
from bob.turn import SmartTurn, TurnGate
from bob.ui.memories import MemoriesWindow
from bob.ui.hud import TalkHud
from bob.ui.listen_toast import ListenToast
from bob.ui.overlay import Overlay
from bob.ui.settings_dialog import SettingsDialog
from bob.ui import theme as theming
from bob.ui.theme import Theme
from bob.ui.theme_dialog import ThemeDialog
from bob.ui.tray import Tray
from bob.util import gpu_memory_line, split_speakable
from bob.vad import Endpointer
from bob.latency import TurnTimer
from bob.voice_mood import DEFAULT_MOOD, strip_mood_tags, take_mood_tag, visible_reply
from bob.wakeword import WakeWordDetector

log = logging.getLogger(__name__)

RESTART_FIELDS = {"stt_model", "stt_compute_type", "sample_rate"}
# Transcript rows repainted on every streamed token; older history stays in
# chat.db but is not redrawn 50 times a second.
MAX_SHOWN_MESSAGES = 60
# Ignore hotkey/tray/toast toggles that land closer together than this.
TOGGLE_DEBOUNCE_SEC = 0.25
MODELS_CACHE_SEC = 20.0

_LOAD_TOAST = {
    "Ollama": "Checking Ollama…",
    "Speech recognition": "Loading speech recognition…",
    "Speech-to-text": "Loading speech-to-text…",
    "Whisper CUDA": "Loading Whisper (CUDA)…",
    "Kokoro TTS": "Loading Kokoro TTS…",
    "Turn detection": "Loading turn detector…",
    "Wake word": "Loading wake-word model…",
    "Memory": "Loading memory…",
    "Tools": "Loading tools…",
    "MCP servers": "Connecting MCP servers…",
    "Microphone": "Starting microphone…",
}


def _load_toast_text(msg: str) -> str:
    text = (msg or "").strip()
    if not text:
        return ""
    return _LOAD_TOAST.get(text, text)


class Assistant:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.settings.start_with_windows = startup_is_enabled()
        self.state = State.LOADING
        self._stop = threading.Event()
        # Cancel token for the *current* turn. _begin_listen() sets it and then
        # swaps in a fresh Event, so a pipeline thread that is still winding
        # down keeps seeing its own cancelled token instead of the new turn's.
        self._cancel = threading.Event()
        self._last_toggle = 0.0
        self._models_cache: tuple[float, list[tuple[str, bool]]] = (0.0, [])
        self._state_lock = threading.Lock()
        self._pipeline_thread: threading.Thread | None = None
        self._chunk_q: queue.Queue = queue.Queue(maxsize=64)
        self._endpoint_armed = False
        self._barge_armed = False
        self.overlay: Overlay | None = None
        self.hud: TalkHud | None = None
        self.toast: ListenToast | None = None
        self.tray: Tray | None = None
        self.hotkey: GlobalHotkey | None = None
        self._memories_win = None
        self._settings_win = None
        self._theme_win = None
        self.memory = MemoryService(DATA_DIR / "memory")
        self.tools = ToolRegistry(DATA_DIR, settings=self.settings, memory=self.memory)
        self.chat = ChatStore(DATA_DIR / "chat.db")
        self._session_id = self.chat.current_session()
        self._turns = [{"role": m.role, "content": m.content} for m in self.chat.list_messages(self._session_id)]
        self._pending_user = ""
        self._pending_reply = ""
        self.audio = AudioHub(
            sample_rate=self.settings.sample_rate,
            input_device=self.settings.input_device or None,
            output_device=self.settings.output_device or None,
            wasapi_exclusive=self.settings.wasapi_exclusive,
        )
        self.stt = create_speech_to_text(
            self.settings.stt_model,
            self.settings.stt_compute_type,
            MODELS_DIR,
        )
        self.tts = TextToSpeech(MODELS_DIR / "kokoro", self.settings.tts_voice, self.settings.tts_speed)
        self.stt_stream = StreamingTranscriber(
            self.stt,
            sample_rate=self.settings.sample_rate,
            commit_silence_ms=self.settings.stt_commit_silence_ms,
            partial_interval_ms=self.settings.stt_partial_interval_ms,
            vad_threshold=self.settings.vad_threshold,
            on_partial=self._on_partial,
        )
        self.speech = SpeechStreamer(self.tts, self.audio)
        self.speech.set_mood(self.settings.tts_mood)
        self._listen_endpointer = Endpointer(
            sample_rate=self.settings.sample_rate,
            threshold=self.settings.vad_threshold,
            min_silence_ms=self.settings.endpoint_silence_ms,
        )
        self._barge_endpointer = Endpointer(
            sample_rate=self.settings.sample_rate,
            threshold=self.settings.vad_threshold,
            min_silence_ms=200,
            min_speech_ms=self.settings.barge_in_speech_ms,
        )
        self.llm = OllamaChat(
            self.settings.ollama_host,
            self.settings.llm_model,
            self.settings.llm_num_ctx,
            self.settings.system_prompt,
            self.settings.max_history_turns,
        )
        self._restore_llm_history()
        self.wake = WakeWordDetector(
            self.settings.wake_word,
            self.settings.wake_threshold,
            self.settings.sample_rate,
            MODELS_DIR / "wakeword",
            on_detect=self._on_wake,
        )
        self.wake.enabled = self.settings.wake_word_enabled

    def run(self) -> None:
        theming.set_current(theming.resolve_theme(self.settings))
        self.overlay = Overlay(
            self.settings.hotkey,
            self.toggle_listen,
            self.quit,
            on_submit=self.submit_text,
            on_settings=self.open_settings,
        )
        self.overlay.on_hide = lambda: self.set_overlay_visible(False, persist=True)
        self.hud = TalkHud(self.overlay, self.settings.hotkey)
        self.toast = ListenToast(self.overlay, on_click=self.toggle_listen)
        self._refresh_talk()
        if not self.settings.show_overlay:
            self.overlay.hide()
        self._start_tray()
        self.overlay.after(80, self._boot)
        self.overlay.after(50, self._poll_level)
        self.overlay.mainloop()

    def _boot(self) -> None:
        threading.Thread(target=self._boot_worker, name="boot", daemon=True).start()

    def _boot_worker(self) -> None:
        def status(msg: str) -> None:
            self._ui(lambda: self.overlay.set_state(State.LOADING, msg))
            self._toast_load(msg)

        try:
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            status("Ollama")
            ollama_ok = True
            try:
                self.llm.ping()
            except Exception as exc:
                # Not fatal: everything else can come up, and the model is
                # (re)loaded from the tray or on the first turn.
                ollama_ok = False
                log.warning("Ollama unreachable at %s: %s", self.llm.host, exc)
                self._toast_load(
                    f"Ollama is not reachable at {self.llm.host}. Start it, then reconnect from the tray.",
                    title="Bob",
                )
                self._ui(
                    lambda: self.overlay.set_reply(
                        f"Ollama is not reachable at {self.llm.host}. Start it, then use "
                        "Models → Reconnect Ollama in the tray."
                    )
                )
            status("Speech recognition")
            try:
                self.stt.load()
            except Exception as exc:
                from bob.stt_parakeet import is_parakeet

                if not is_parakeet(self.settings.stt_model):
                    raise
                log.warning("Parakeet failed (%s); falling back to Whisper large-v3-turbo", exc)
                self._toast_load(
                    "Parakeet unavailable — using Whisper instead.",
                    title="Bob",
                )
                from bob.stt import SpeechToText

                self.stt = SpeechToText(
                    "large-v3-turbo",
                    self.settings.stt_compute_type,
                    MODELS_DIR / "whisper",
                )
                self.stt_stream.stt = self.stt
                self.stt.load()
            log.info(
                "STT %s on %s (%s)",
                self.stt.model_name,
                self.stt.device,
                self.stt.compute_type,
            )
            status("Kokoro TTS")
            self.tts.load(on_status=status)
            status("Wake word")
            self.wake.load()
            if self.wake.error:
                log.warning("Wake word: %s", self.wake.error)
            status("Memory")
            try:
                self.memory.load()
            except Exception as exc:
                log.exception("Memory failed to load")
                self._ui(lambda: self.overlay.set_reply(f"Memory offline: {exc}"))
            status("Tools")
            self._load_tools(status)
            status("Microphone")
            self.audio.start(on_chunk=self._enqueue_chunk)
            self.stt_stream.start()
            self.speech.start()
            threading.Thread(target=self._chunk_loop, name="chunks", daemon=True).start()
            self._restart_hotkey()
            if self.hotkey and self.hotkey.error:
                log.warning("Hotkey: %s", self.hotkey.error)
            if ollama_ok:
                status(f"Loading {self.settings.llm_model}")
                try:
                    self.llm.preload()
                except Exception as exc:
                    log.warning("Model preload failed: %s", exc)
                    self._toast_load(f"Model load failed: {exc}", title="Bob")
                    self._ui(lambda: self.overlay.set_reply(f"Model load failed: {exc}"))
            detail = self._ready_detail()
            self._set_state(State.IDLE, detail)
            self._ui(lambda: self.overlay.set_meta(detail))
            if self.tray:
                self._ui(self.tray.refresh)
            self._toast_load(f"Ready — {detail}", title="Bob")
            log.info("Ready: %s", detail)
        except Exception as exc:
            log.exception("Boot failed")
            self._toast_load(str(exc), title="Bob failed to start")
            self._set_state(State.ERROR, str(exc)[:80])
            self._ui(lambda: self.overlay.set_reply(str(exc)))

    def _toast_load(self, msg: str, title: str = "Bob is loading") -> None:
        text = _load_toast_text(msg)
        if not text:
            return
        last = getattr(self, "_last_load_toast", None)
        if last == (title, text):
            return
        self._last_load_toast = (title, text)
        from bob.os_toast import show as os_toast

        os_toast(text, title, replace=True)

    def _ready_detail(self) -> str:
        bits = [
            self.settings.hotkey.upper(),
            self.stt.model_name,
            self.settings.llm_model,
        ]
        if self.hotkey and self.hotkey.error:
            bits.append(self.hotkey.error)
        if self.wake.error:
            bits.append("wake word off")
        elif self.wake.enabled:
            bits.append(self.settings.wake_word)
        count = len(self.tools.names()) if self.settings.tools_enabled else 0
        if count:
            bits.append(f"{count} tools")
        return "  ·  ".join(bits)

    def _load_tools(self, status=None) -> None:
        if not self.settings.tools_enabled:
            self.tools.close_mcp()
            return
        try:
            self.tools.load()
            servers = [srv for srv in self.settings.mcp_servers or [] if isinstance(srv, dict)]
            if servers:
                if status:
                    status("MCP servers")
                self.tools.load_mcp(servers, timeout=float(self.settings.tool_timeout_sec))
        except Exception as exc:
            self.tools.errors.append(str(exc))
        if self.tools.errors:
            note = "Tools: " + "; ".join(self.tools.errors[:3])
            self._ui(lambda: self.overlay.set_reply(note))

    def _reload_tools(self) -> None:
        threading.Thread(target=self._load_tools, name="tools", daemon=True).start()

    def _start_tray(self) -> None:
        try:
            self.tray = Tray(self)
            self.tray.run_detached()
        except Exception:
            self.set_overlay_visible(True, persist=False)

    def _tray_models(self) -> list[tuple[str, bool]]:
        """Ollama model list for menus. Cached so rebuilding the tray menu on the
        UI thread does not block on the network every time a setting changes."""
        stamp, cached = self._models_cache
        if cached and time.monotonic() - stamp < MODELS_CACHE_SEC:
            return cached
        out = []
        try:
            for item in self.llm.list_models():
                name = item.get("name") or item.get("model") or ""
                if not name:
                    continue
                large = int(item.get("size") or 0) > 6 * 1024 * 1024 * 1024
                out.append((name, large))
        except Exception as exc:
            log.debug("list_models failed: %s", exc)
            return cached
        self._models_cache = (time.monotonic(), out)
        return out

    def apply_setting(self, field: str, value) -> None:
        if field in RESTART_FIELDS and str(getattr(self.settings, field)) != str(value):
            self.settings.update(**{field: value})
            self._ui(lambda: self.overlay.set_reply("Saved. Restart Bob to apply this setting."))
            if self.tray:
                self.tray.refresh()
            return
        if field == "theme":
            self.settings.update(theme=value, theme_overrides={})
        else:
            self.settings.update(**{field: value})
        self._apply_live(field, value)
        if self.tray:
            self.tray.refresh()

    def apply_settings_dict(self, values: dict) -> None:
        if "auto_endpoint" in values:
            if values["auto_endpoint"]:
                ms = int(values.get("endpoint_silence_ms") or self.settings.endpoint_silence_ms)
                values["max_silence_sec"] = ms / 1000.0
            else:
                values["max_silence_sec"] = 0.0
        restart = any(str(getattr(self.settings, k, None)) != str(v) for k, v in values.items() if k in RESTART_FIELDS)
        devices_changed = any(
            str(getattr(self.settings, k, "") or "") != str(values.get(k, "") or "")
            for k in ("input_device", "output_device")
            if k in values
        )
        model_changed = str(values.get("llm_model", self.settings.llm_model)) != self.settings.llm_model
        old_theme = self.settings.theme
        self.settings.update(**values)
        if "theme" in values and str(values["theme"]) != str(old_theme) and "theme_overrides" not in values:
            self.settings.update(theme_overrides={})
        if "theme" in values or "theme_overrides" in values:
            self.apply_theme(theming.resolve_theme(self.settings))
        self.llm.host = self.settings.ollama_host.rstrip("/")
        self.llm.model = self.settings.llm_model
        self.llm.num_ctx = self.settings.llm_num_ctx
        self.llm.system_prompt = self.settings.system_prompt
        self.llm.max_turns = self.settings.max_history_turns
        self.tts.voice = self.settings.tts_voice
        from bob.tts import clamp_speed

        self.tts.speed = clamp_speed(self.settings.tts_speed)
        self.speech.set_mood(self.settings.tts_mood)
        self.wake.enabled = self.settings.wake_word_enabled
        self.wake.threshold = self.settings.wake_threshold
        if self.settings.wake_word != self.wake.model_name:
            self._reload_wake_word(self.settings.wake_word)
        self._configure_streaming()
        self.set_overlay_visible(self.settings.show_overlay, persist=False)
        self.set_start_with_windows(self.settings.start_with_windows)
        if not self.settings.tools_enabled:
            self.tools.close_mcp()
        elif not self.tools.names():
            self._reload_tools()
        self._restart_hotkey()
        if devices_changed:
            # Reopening the mic mid-turn drops the listen buffer, so only do it
            # when a device actually changed.
            self._restart_audio()
        if model_changed:
            threading.Thread(target=self._preload_safe, name="preload", daemon=True).start()
        self._ui(lambda: self.overlay.set_meta(self._ready_detail()))
        if restart:
            self._ui(lambda: self.overlay.set_reply("Some settings need a Bob restart (STT / sample rate)."))
        if self.tray:
            self.tray.refresh()

    def _apply_live(self, field: str, value) -> None:
        if field == "llm_model":
            self.llm.model = value
            threading.Thread(target=self._preload_safe, name="preload", daemon=True).start()
        elif field == "llm_num_ctx":
            self.llm.num_ctx = int(value)
        elif field == "system_prompt":
            self.llm.system_prompt = str(value)
        elif field == "max_history_turns":
            self.llm.max_turns = int(value)
        elif field == "ollama_host":
            self.llm.host = str(value).rstrip("/")
        elif field == "tts_voice":
            self.tts.voice = str(value)
        elif field == "tts_speed":
            from bob.tts import clamp_speed

            self.tts.speed = clamp_speed(value)
        elif field == "tts_mood":
            self.speech.set_mood(value)
        elif field == "wake_word_enabled":
            self.wake.enabled = bool(value)
        elif field == "wake_threshold":
            self.wake.threshold = float(value)
        elif field == "wake_word":
            self._reload_wake_word(str(value))
        elif field == "hotkey":
            self._restart_hotkey()
            if self.hud:
                self.hud.set_hotkey(str(value))
            if self.overlay:
                self.overlay.set_meta(self._ready_detail())
        elif field in {"input_device", "output_device"}:
            self._restart_audio()
        elif field == "show_overlay":
            self.set_overlay_visible(bool(value), persist=False)
        elif field == "start_with_windows":
            self.set_start_with_windows(bool(value))
        elif field == "tools_enabled":
            self._reload_tools()
        elif field in {"theme", "theme_overrides"}:
            self.apply_theme(theming.resolve_theme(self.settings))
            self._sync_settings_theme_var()
        elif field in {
            "auto_endpoint",
            "endpoint_silence_ms",
            "barge_in",
            "barge_in_speech_ms",
            "stt_partial_interval_ms",
            "stt_commit_silence_ms",
            "vad_threshold",
        }:
            if field == "auto_endpoint":
                self.settings.max_silence_sec = (
                    self.settings.endpoint_silence_ms / 1000.0 if value else 0.0
                )
                self.settings.save()
            self._configure_streaming()
        self._ui(lambda: self.overlay.set_meta(self._ready_detail()))

    def set_overlay_visible(self, visible: bool, persist: bool = True) -> None:
        self.settings.show_overlay = bool(visible)
        if persist:
            self.settings.save()
        if not self.overlay:
            return

        def apply():
            if visible:
                self.overlay.show()
                if self.hud:
                    self.hud.hide()
            else:
                self.overlay.withdraw()

        self._ui(apply)
        if self.tray:
            self.tray.refresh()

    def open_main_ui(self) -> None:
        self.set_overlay_visible(True, persist=True)

    def set_start_with_windows(self, enabled: bool) -> None:
        actual = startup_set_enabled(bool(enabled))
        self.settings.start_with_windows = actual
        self.settings.save()
        if self.tray:
            self.tray.refresh()

    def open_settings(self) -> None:
        def show():
            if self._settings_win is not None:
                try:
                    self._settings_win.focus()
                    return
                except Exception:
                    self._settings_win = None
            models = [name for name, _ in self._tray_models()]
            self._settings_win = SettingsDialog(
                self.overlay,
                self.settings,
                self.apply_settings_dict,
                models,
                list_devices("input"),
                list_devices("output"),
                on_recording=self._set_hotkey_recording,
                on_hotkey_changed=lambda spec: self.apply_setting("hotkey", spec),
                on_open_theme=self.open_theme,
                on_close=lambda: setattr(self, "_settings_win", None),
            )

        self._ui(show)

    def open_theme(self) -> None:
        def show():
            if self._theme_win is not None:
                try:
                    if self._theme_win.winfo_exists():
                        self._theme_win.focus()
                        self._theme_win.lift()
                        return
                except Exception:
                    self._theme_win = None
            if self.overlay is None:
                return
            self._theme_win = ThemeDialog(
                self.overlay,
                self.settings,
                on_preview=self.apply_theme,
                on_save=self.save_theme,
                on_close=self._theme_closed,
            )

        self._ui(show)

    def _theme_closed(self) -> None:
        self._theme_win = None

    def save_theme(self, values: dict) -> None:
        theme_key = values.get("theme", self.settings.theme)
        overrides = theming.clean_overrides(values.get("theme_overrides"))
        self.settings.update(theme=theme_key, theme_overrides=overrides)
        self.apply_theme(theming.resolve_theme(self.settings))
        self._sync_settings_theme_var()
        if self.tray:
            self.tray.refresh()

    def apply_theme(self, theme: Theme) -> None:
        """Make *theme* current and restyle every open window. Does not persist."""

        def apply() -> None:
            theming.set_current(theme)
            for win in (
                self.overlay,
                self.hud,
                self.toast,
                self._settings_win,
                self._memories_win,
            ):
                if win is None:
                    continue
                try:
                    if not win.winfo_exists():
                        continue
                except Exception:
                    continue
                restyle = getattr(win, "apply_theme", None)
                if restyle:
                    try:
                        restyle(theme)
                    except Exception:
                        log.debug("Theme restyle failed", exc_info=True)

        if self.overlay is None:
            theming.set_current(theme)
            return
        try:
            if threading.current_thread() is threading.main_thread():
                apply()
            else:
                self._ui(apply)
        except Exception:
            self._ui(apply)

    def _sync_settings_theme_var(self) -> None:
        win = self._settings_win
        if win is None:
            return
        var = getattr(win, "vars", {}).get("theme")
        if var is None:
            return
        try:
            from bob.ui.theme import preset

            var.set(preset(self.settings.theme).title)
        except Exception:
            pass

    def open_memories(self) -> None:
        def show():
            if self._memories_win is not None:
                try:
                    self._memories_win.focus()
                    self._memories_win.refresh()
                    return
                except Exception:
                    self._memories_win = None
            self._memories_win = MemoriesWindow(
                self.overlay,
                rows_provider=self.memory.list_memories,
                on_toggle=self.memory.set_enabled,
                on_edit=self.memory.edit,
                on_delete=self.memory.delete,
                on_forget_all=self.memory.forget_all,
                autosave=self.settings.memory_autosave,
                on_autosave=lambda on: self.apply_setting("memory_autosave", on),
            )

        self._ui(show)

    def _set_hotkey_recording(self, active: bool) -> None:
        if active:
            if self.hotkey:
                self.hotkey.stop()
                self.hotkey = None
            return
        if self.hotkey is None:
            self._restart_hotkey()

    def _restart_hotkey(self) -> None:
        if self.hotkey:
            self.hotkey.stop()
        self.hotkey = GlobalHotkey(self.settings.hotkey, self.toggle_listen)
        self.hotkey.start()

    def _restart_audio(self) -> None:
        listening = self.audio.is_listening
        try:
            self.audio.stop()
        except Exception:
            log.exception("Stopping audio failed")
        self.audio.input_device = self.settings.input_device or None
        self.audio.output_device = self.settings.output_device or None
        self.audio.sample_rate = self.settings.sample_rate
        try:
            self.audio.start(on_chunk=self._enqueue_chunk)
        except Exception as exc:
            # Runs from tray / settings callbacks; an unhandled error here used
            # to leave Bob with no microphone and no message.
            log.exception("Audio restart failed")
            self._ui(lambda: self.overlay.set_reply(f"Audio device error: {exc}"))
            return
        if self.audio.input_device is None and self.settings.input_device:
            # AudioHub fell back to the default device because the saved one is gone.
            self.settings.update(input_device="")
            self._ui(lambda: self.overlay.set_reply("Saved microphone not found; using the system default."))
        if self.audio.output_device is None and self.settings.output_device:
            self.settings.update(output_device="")
        if listening:
            self.audio.start_listening()

    def _reload_wake_word(self, name: str) -> None:
        def work() -> None:
            self.wake.set_model(name)
            if self.wake.error:
                log.warning("Wake word reload failed: %s", self.wake.error)
                self._ui(lambda: self.overlay.set_reply(f"Wake word: {self.wake.error}"))
            self._ui(lambda: self.overlay.set_meta(self._ready_detail()))

        threading.Thread(target=work, name="wakeword-reload", daemon=True).start()

    def stop_speaking(self) -> None:
        """Cut Bob off and go idle without starting a new listen (tray action)."""

        def apply() -> None:
            if self.state not in {State.SPEAKING, State.THINKING}:
                return
            self._cancel_current_turn()
            self._barge_armed = False
            self.audio.set_capture_muted(False)
            self._set_state(State.IDLE, self._ready_detail())
            self._restore_idle_ui()

        self._ui(apply)

    def _cancel_current_turn(self) -> None:
        """Cancel the running pipeline and hand out a fresh token for the next one."""
        self._cancel.set()
        self._cancel = threading.Event()
        self.speech.cancel()

    def _configure_streaming(self) -> None:
        s = self.settings
        self.stt_stream.configure(
            commit_silence_ms=s.stt_commit_silence_ms,
            partial_interval_ms=s.stt_partial_interval_ms,
            vad_threshold=s.vad_threshold,
            sample_rate=s.sample_rate,
        )
        self._listen_endpointer.configure(threshold=s.vad_threshold, min_silence_ms=s.endpoint_silence_ms)
        self._barge_endpointer.configure(threshold=s.vad_threshold)
        self._barge_endpointer.min_speech_ms = int(s.barge_in_speech_ms)

    def _preload_safe(self) -> None:
        try:
            self._toast_load(f"Loading {self.llm.model}…")
            self._ui(lambda: self.overlay.set_meta(f"Loading {self.llm.model} …"))
            self.llm.preload()
            self._models_cache = (0.0, [])
            self._ui(lambda: self.overlay.set_meta(self._ready_detail()))
            if self.tray:
                self._ui(self.tray.refresh)
            self._toast_load(f"{self.llm.model} is ready", title="Bob")
        except Exception as exc:
            log.warning("Model preload failed: %s", exc)
            self._toast_load(f"Model load failed: {exc}", title="Bob")
            self._ui(lambda: self.overlay.set_reply(f"Model load failed: {exc}"))
            self._ui(lambda: self.overlay.set_meta(self._ready_detail()))

    def reconnect_ollama(self) -> None:
        threading.Thread(target=self._preload_safe, name="preload", daemon=True).start()

    def _restore_llm_history(self) -> None:
        max_msgs = max(2, int(self.settings.max_history_turns) * 2)
        self.llm.history = [
            {"role": turn["role"], "content": turn["content"]}
            for turn in self._turns[-max_msgs:]
            if turn.get("role") in {"user", "assistant"}
        ]

    def load_session(self, session_id: int) -> None:
        """Switch the live transcript and LLM history to a saved chat."""

        def apply() -> None:
            if self.state in {State.LISTENING, State.THINKING, State.SPEAKING}:
                self._cancel_current_turn()
                self.stt_stream.cancel()
                self.audio.stop_listening()
                self._barge_armed = False
                self.audio.set_capture_muted(False)
                self._set_state(State.IDLE, self._ready_detail())
                self._restore_idle_ui()
            self._session_id = int(session_id)
            self._turns = [
                {"role": m.role, "content": m.content} for m in self.chat.list_messages(self._session_id)
            ]
            self._pending_user = ""
            self._pending_reply = ""
            self.llm.reset()
            self._restore_llm_history()
            self._refresh_talk()
            if self.tray:
                self.tray.refresh()

        self._ui(apply)

    def _new_chat(self) -> None:
        self.llm.reset()
        self._session_id = self.chat.new_session()
        self._turns = []
        self._pending_user = ""
        self._pending_reply = "New conversation."
        self._refresh_talk()
        if self.tray:
            self.tray.refresh()

    def _enqueue_chunk(self, chunk) -> None:
        if self._stop.is_set():
            return
        try:
            self._chunk_q.put_nowait(chunk)
        except queue.Full:
            try:
                self._chunk_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._chunk_q.put_nowait(chunk)
            except queue.Full:
                pass

    def _chunk_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._chunk_q.get(timeout=0.1)
            except queue.Empty:
                continue
            self._handle_chunk(chunk)

    def _handle_chunk(self, chunk) -> None:
        state = self.state
        if state == State.IDLE and self.wake.enabled and not self.wake.error:
            self.wake.feed(chunk)
        if state == State.SPEAKING and self.settings.barge_in and self._barge_armed:
            ep = self._barge_endpointer.feed(chunk)
            if ep.in_speech and ep.speech_ms >= float(self.settings.barge_in_speech_ms):
                self._barge_armed = False
                seed = self._barge_endpointer.take_speech_seed()
                self._ui(lambda s=seed: self._barge_in(s))
            return
        if state != State.LISTENING:
            return
        self.stt_stream.push(chunk)
        ep = self._listen_endpointer.feed(chunk)
        if (
            self.settings.auto_endpoint
            and self._endpoint_armed
            and ep.heard_speech
            and ep.turn_speech_ms >= float(self._listen_endpointer.min_speech_ms)
            and ep.silence_ms >= float(self.settings.endpoint_silence_ms)
        ):
            partial = self.stt_stream.current_text.strip()
            if not partial:
                return
            self._endpoint_armed = False
            self._ui(self._finish_listen)

    def _on_wake(self) -> None:
        if self.state == State.IDLE:
            self._ui(self._begin_listen)

    def toggle_listen(self) -> None:
        self._ui(self._toggle_from_ui)

    def _toggle_from_ui(self) -> None:
        now = time.monotonic()
        if now - self._last_toggle < TOGGLE_DEBOUNCE_SEC:
            return
        self._last_toggle = now
        state = self.state
        if state == State.LOADING:
            return
        if state == State.ERROR:
            if getattr(self.stt, "_model", None) is None:
                return
            self._set_state(State.IDLE, self._ready_detail())
            self._restore_idle_ui()
            state = self.state
        if state in {State.SPEAKING, State.THINKING}:
            self._begin_listen()
            return
        if state == State.LISTENING:
            self._finish_listen()
            return
        self._begin_listen()

    def _overlay_viewable(self) -> bool:
        return bool(self.overlay and self.overlay.is_viewable())

    def _present_talk(self, phase: str) -> None:
        def apply() -> None:
            iconic = False
            try:
                iconic = bool(self.overlay) and self.overlay.state() == "iconic"
            except Exception:
                iconic = False
            # Iconified Tk roots also hide Toplevels on Windows, so restore the overlay.
            if self._overlay_viewable() or iconic:
                self.overlay.set_phase(phase)
                self.overlay.present()
                if self.hud:
                    self.hud.hide()
                return
            if self.hud:
                self.hud.set_phase(phase)
                self.hud.present()
                self.hud.set_hotkey(self.settings.hotkey)

        self._ui(apply)

    def _talk_set_user(self, text: str) -> None:
        self._pending_user = text or ""
        self._refresh_talk()

    def _talk_set_reply(self, text: str) -> None:
        self._pending_reply = text or ""
        self._refresh_talk()

    def _refresh_talk(self) -> None:
        messages = list(self._turns[-MAX_SHOWN_MESSAGES:])
        pending_user = self._pending_user
        pending_reply = self._pending_reply

        def apply() -> None:
            if self.overlay:
                self.overlay.set_transcript(messages, pending_user, pending_reply)
            if self.hud:
                self.hud.set_transcript(messages, pending_user, pending_reply)

        if self.overlay is None:
            return
        try:
            if threading.current_thread() is threading.main_thread():
                apply()
            else:
                self._ui(apply)
        except Exception:
            self._ui(apply)

    def _commit_turn(self, role: str, content: str) -> None:
        text = (content or "").strip()
        if not text:
            return
        self._turns.append({"role": role, "content": text})
        try:
            self.chat.add_message(self._session_id, role, text)
        except Exception:
            log.exception("Failed to persist chat message")
        if role == "user":
            self._pending_user = ""
        else:
            self._pending_reply = ""
        self._refresh_talk()

    def _restore_idle_ui(self) -> None:
        if self._overlay_viewable():
            self.overlay.set_phase("idle")

    def _begin_listen(self, seed=None) -> None:
        self._cancel_current_turn()
        self.stt_stream.cancel()
        self.audio.set_capture_muted(False)
        self._listen_endpointer.reset()
        self._barge_endpointer.reset()
        self._endpoint_armed = True
        self._barge_armed = False
        self.audio.start_listening(seed)
        self.stt_stream.start_turn(seed)
        if seed is not None and getattr(seed, "size", 0):
            self._listen_endpointer.feed(seed)
        self._present_talk("listen")
        self._talk_set_user("")
        self._talk_set_reply("")
        hint = "pause to send" if self.settings.auto_endpoint else f"{self.settings.hotkey.upper()} to send"
        self._set_state(State.LISTENING, hint)

    def _barge_in(self, seed) -> None:
        if self.state not in {State.SPEAKING, State.THINKING}:
            return
        self._begin_listen(seed=seed)

    def _finish_listen(self) -> None:
        if self.state != State.LISTENING:
            return
        self._endpoint_armed = False
        self.audio.stop_listening()
        self._present_talk("reply")
        self._talk_set_reply("…")
        self._set_state(State.THINKING, "transcribing")
        self._start_pipeline(self._cancel)

    def submit_text(self, text: str) -> None:
        """Send a typed message through the same LLM → TTS path as speech."""
        text = (text or "").strip()
        if not text:
            return

        def apply() -> None:
            if self.state == State.LOADING:
                return
            if self.state == State.ERROR:
                if getattr(self.stt, "_model", None) is None:
                    return
                self._set_state(State.IDLE, self._ready_detail())
            if self.state == State.LISTENING:
                self._endpoint_armed = False
                self.audio.stop_listening()
                self.stt_stream.cancel()
            self._cancel_current_turn()
            self._barge_armed = False
            self.audio.set_capture_muted(False)
            self._present_talk("reply")
            self._talk_set_user(text)
            self._talk_set_reply("…")
            self._set_state(State.THINKING, "ollama")
            self._start_pipeline(self._cancel, typed_text=text)

        self._ui(apply)

    def _start_pipeline(self, cancel: threading.Event, typed_text: str | None = None) -> None:
        self._pipeline_thread = threading.Thread(
            target=self._pipeline,
            args=(cancel, typed_text),
            name="pipeline",
            daemon=True,
        )
        self._pipeline_thread.start()

    def _on_partial(self, text: str) -> None:
        if self.state != State.LISTENING:
            return
        if text:
            self._talk_set_user(text + " …")
        else:
            self._talk_set_user("")

    def _start_speech(self) -> int:
        epoch = self.speech.begin()
        if not self.settings.barge_in:
            self.audio.set_capture_muted(True)
        else:
            self.audio.set_capture_muted(False)
            self._barge_endpointer.reset()
            self._barge_armed = True
        self._set_state(State.SPEAKING, "" if self.speech.mood == DEFAULT_MOOD else self.speech.mood)
        return epoch

    def _reset_turn_mood(self) -> None:
        self.speech.set_mood(getattr(self.settings, "tts_mood", DEFAULT_MOOD))

    def _apply_turn_mood(self, mood: str) -> str:
        chosen = self.speech.set_mood(mood)
        if self.state == State.SPEAKING:
            self._set_state(State.SPEAKING, "" if chosen == DEFAULT_MOOD else chosen)
        elif self.state == State.THINKING:
            self._set_state(State.THINKING, f"mood: {chosen}")
        return chosen

    def _pipeline(self, cancel: threading.Event | None = None, typed_text: str | None = None) -> None:
        assistant_text = ""
        user_text = ""
        epoch = 0
        started = False
        token = cancel or self._cancel
        self._reset_turn_mood()
        try:
            if typed_text:
                user_text = typed_text.strip()
            else:
                user_text = self.stt_stream.finalize()
            if token.is_set():
                return
            too_short = (not typed_text) and self.stt_stream.total_samples < self.settings.sample_rate * 0.25
            if too_short and not user_text.strip():
                self._talk_set_user("(too short)")
                self._set_state(State.IDLE, self._ready_detail())
                self._ui(self._restore_idle_ui)
                return
            if not user_text.strip():
                self._talk_set_user("(no speech detected)")
                self._set_state(State.IDLE, self._ready_detail())
                self._ui(self._restore_idle_ui)
                return
            self._commit_turn("user", user_text)
            self._set_state(State.THINKING, "ollama")
            memory_block = ""
            try:
                memory_block = self.memory.retrieve(user_text, limit=int(self.settings.memory_max_inject))
            except Exception:
                memory_block = ""
            pending = ""
            full = ""
            for chunk in self.llm.chat(
                user_text,
                memory_block=memory_block,
                tools=self._tool_schemas(),
                on_tool=lambda name, arguments, t=token: self._run_tool(name, arguments, cancel=t),
                cancel=token,
                max_rounds=int(self.settings.max_tool_rounds),
            ):
                if token.is_set():
                    if started:
                        self.speech.cancel()
                    return
                full += chunk
                pending += chunk
                tagged, pending, waiting = take_mood_tag(pending)
                if tagged:
                    self._apply_turn_mood(tagged)
                self._talk_set_reply(visible_reply(full))
                if waiting:
                    continue
                pieces, pending = split_speakable(pending, first=not started)
                for piece in pieces:
                    if token.is_set():
                        self.speech.cancel()
                        return
                    spoken = strip_mood_tags(piece)
                    if not spoken:
                        continue
                    if not started:
                        epoch = self._start_speech()
                        started = True
                    self.speech.feed(spoken)
            leftover = strip_mood_tags(pending)
            if leftover and not token.is_set():
                if not started:
                    epoch = self._start_speech()
                    started = True
                self.speech.feed(leftover)
            if token.is_set():
                if started:
                    self.speech.cancel()
                return
            if started:
                self.speech.finish()
            assistant_text = strip_mood_tags(full)
            if assistant_text:
                self._commit_turn("assistant", assistant_text)
            if started:
                self.speech.wait(epoch)
        except Exception as exc:
            self._talk_set_reply(f"Error: {exc}")
            if started:
                self.speech.cancel()
        finally:
            self._barge_armed = False
            self.audio.set_capture_muted(False)
            self._reset_turn_mood()
            if not token.is_set() and self.state != State.LISTENING:
                self._set_state(State.IDLE, self._ready_detail())
                self._ui(self._restore_idle_ui)
            if assistant_text and user_text and self.settings.memory_autosave:
                threading.Thread(
                    target=self._ingest_memory,
                    args=(user_text, assistant_text),
                    name="memory-ingest",
                    daemon=True,
                ).start()

    def _tool_schemas(self) -> list[dict] | None:
        if not self.settings.tools_enabled:
            return None
        return self.tools.schemas() or None

    def _run_tool(self, name: str, arguments, cancel: threading.Event | None = None) -> str:
        token = cancel or self._cancel
        self._set_state(State.THINKING, f"tool: {name}")
        ctx = self.tools.context(
            cancel=token,
            status=lambda msg: self._set_state(State.THINKING, msg),
            mood=self.speech.mood,
            on_mood=self._apply_turn_mood,
        )
        result = self.tools.invoke(name, arguments, ctx=ctx, timeout=float(self.settings.tool_timeout_sec))
        self._set_state(State.THINKING, "ollama")
        return result

    def _ingest_memory(self, user_text: str, assistant_text: str) -> None:
        try:
            self.memory.ingest(user_text, assistant_text, self.llm.generate)
        except Exception:
            log.exception("Memory ingest failed")

    def _poll_level(self) -> None:
        if self.overlay is None:
            return
        boost = min(1.0, self.audio.level * 8.0)
        self.overlay.set_level(boost)
        if self.hud and self.hud.is_open():
            self.hud.set_level(boost)
        if self.toast and self.toast.is_open():
            self.toast.set_waveform(self.audio.waveform_bars())
        if not self._stop.is_set():
            self.overlay.after(50, self._poll_level)

    def _set_state(self, state: State, detail: str = "") -> None:
        with self._state_lock:
            self.state = state

        def apply() -> None:
            if self.overlay:
                self.overlay.set_state(state, detail)
            if self.hud and self.hud.is_open():
                self.hud.set_state(state, detail)
            if self.toast:
                if state in {State.LISTENING, State.THINKING, State.SPEAKING}:
                    self.toast.set_state(state, detail)
                else:
                    self.toast.hide()

        self._ui(apply)

    def _ui(self, fn) -> None:
        if self.overlay is None:
            return
        try:
            self.overlay.ui(fn)
        except Exception:
            pass

    def quit(self) -> None:
        self._stop.set()
        self._cancel.set()
        self.stt_stream.stop()
        self.speech.stop()
        self.audio.stop_playback()
        self._ui(self._shutdown_ui)

    def _shutdown_ui(self) -> None:
        if self.hotkey:
            self.hotkey.stop()
        self.audio.stop()
        if self.tray:
            self.tray.stop()
        if self.toast:
            self.toast.hide()
        try:
            self.tools.close()
        except Exception:
            pass
        try:
            self.chat.close()
        except Exception:
            pass
        if self.overlay:
            self.overlay.destroy()


def run_check() -> int:
    settings = load_settings()
    print(f"config: {settings.llm_model} / {settings.stt_model} / {settings.tts_voice}")
    print(f"gpu:    {gpu_memory_line()}")
    llm = OllamaChat(
        settings.ollama_host,
        settings.llm_model,
        settings.llm_num_ctx,
        settings.system_prompt,
        settings.max_history_turns,
    )
    try:
        llm.ping()
        print(f"ollama: {settings.ollama_host} ok")
        models = llm.list_models()
        print(f"models: {len(models)} local")
    except Exception as exc:
        print(f"ollama: FAILED ({exc})")
        return 1
    stt = SpeechToText(settings.stt_model, settings.stt_compute_type, MODELS_DIR / "whisper")
    print("whisper: loading ...")
    stt.load()
    print(f"whisper: {stt.model_name} on {stt.device} ({stt.compute_type})")
    tts = TextToSpeech(MODELS_DIR / "kokoro", settings.tts_voice, settings.tts_speed)
    print("kokoro:  loading ...")
    tts.load(on_status=print)
    samples, sr = tts.synthesize("Bob is ready.")
    print(f"kokoro:  {len(samples)} samples @ {sr} Hz")
    import asyncio
    import numpy as np
    from bob.vad import speech_regions

    t0 = time.perf_counter()
    first_chunk_s = None

    async def _first_chunk() -> None:
        nonlocal first_chunk_s
        async for _samples, _sr in tts.synthesize_stream("Sure, I can help with that right away."):
            first_chunk_s = time.perf_counter() - t0
            break

    asyncio.run(_first_chunk())
    if first_chunk_s is not None:
        print(f"kokoro:  first stream chunk {first_chunk_s * 1000:.0f} ms")
    print(f"stt:     partial interval {settings.stt_partial_interval_ms} ms")
    t0 = time.perf_counter()
    stt.transcribe(np.zeros(int(settings.sample_rate * 1.0), dtype=np.float32), settings.sample_rate)
    print(f"whisper: 1s decode {(time.perf_counter() - t0) * 1000:.0f} ms")
    t0 = time.perf_counter()
    speech_regions(np.zeros(settings.sample_rate, dtype=np.float32), sample_rate=settings.sample_rate)
    print(f"vad:     {(time.perf_counter() - t0) * 1000:.0f} ms / 1s audio")
    wake = WakeWordDetector(
        settings.wake_word,
        settings.wake_threshold,
        settings.sample_rate,
        MODELS_DIR / "wakeword",
        on_detect=lambda: None,
    )
    wake.load()
    if wake.error:
        print(f"wake:    {wake.error}")
    else:
        print(f"wake:    {settings.wake_word} ready")
    print("memory:  loading ...")
    memory = MemoryService(DATA_DIR / "memory")
    try:
        memory.load()
        print("memory:  ready")
    except Exception as exc:
        print(f"memory:  FAILED ({exc})")
        return 1
    if settings.tools_enabled:
        print("tools:   loading ...")
        tools = ToolRegistry(DATA_DIR, settings=settings, memory=memory)
        names = tools.load()
        names += tools.load_mcp(settings.mcp_servers, timeout=float(settings.tool_timeout_sec))
        print(f"tools:   {len(names)} ready ({', '.join(sorted(names))})")
        for err in tools.errors:
            print(f"tools:   WARN {err}")
        tools.close()
    else:
        print("tools:   disabled")
    print(f"gpu:    {gpu_memory_line()}")
    print("check:  ok")
    return 0
