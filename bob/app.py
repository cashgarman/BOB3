from __future__ import annotations

import queue
import threading
import time

from bob.audio import AudioHub, list_devices, rms
from bob.chat_store import ChatStore
from bob.hotkeys import GlobalHotkey
from bob.llm import OllamaChat
from bob.memory.service import MemoryService
from bob.settings import DATA_DIR, MODELS_DIR, Settings, load_settings
from bob.state import State
from bob.startup import is_enabled as startup_is_enabled
from bob.startup import set_enabled as startup_set_enabled
from bob.stt import SpeechToText
from bob.tools import ToolRegistry
from bob.tts import TextToSpeech
from bob.ui.memories import MemoriesWindow
from bob.ui.hud import TalkHud
from bob.ui.listen_toast import ListenToast
from bob.ui.overlay import Overlay
from bob.ui.settings_dialog import SettingsDialog
from bob.ui.tray import Tray
from bob.util import gpu_memory_line, split_sentences
from bob.wakeword import WakeWordDetector

RESTART_FIELDS = {"stt_model", "stt_compute_type", "sample_rate"}


class Assistant:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.settings.start_with_windows = startup_is_enabled()
        self.state = State.LOADING
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._state_lock = threading.Lock()
        self._stt_lock = threading.Lock()
        self._pipeline_thread: threading.Thread | None = None
        self._chunk_q: queue.Queue = queue.Queue(maxsize=64)
        self._last_voice = time.monotonic()
        self._heard_speech = False
        self.overlay: Overlay | None = None
        self.hud: TalkHud | None = None
        self.toast: ListenToast | None = None
        self.tray: Tray | None = None
        self.hotkey: GlobalHotkey | None = None
        self._memories_win = None
        self._settings_win = None
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
        )
        self.stt = SpeechToText(
            self.settings.stt_model,
            self.settings.stt_compute_type,
            MODELS_DIR / "whisper",
        )
        self.tts = TextToSpeech(MODELS_DIR / "kokoro", self.settings.tts_voice)
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
        self.overlay = Overlay(self.settings.hotkey, self.toggle_listen, self.quit)
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

        try:
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            status("Ollama")
            self.llm.ping()
            status("Whisper CUDA")
            self.stt.load()
            status("Kokoro TTS")
            self.tts.load(on_status=status)
            status("Wake word")
            self.wake.load()
            status("Memory")
            try:
                self.memory.load()
            except Exception as exc:
                self._ui(lambda: self.overlay.set_reply(f"Memory offline: {exc}"))
            status("Tools")
            self._load_tools(status)
            status("Microphone")
            self.audio.start(on_chunk=self._enqueue_chunk)
            threading.Thread(target=self._chunk_loop, name="chunks", daemon=True).start()
            self._restart_hotkey()
            status(f"Loading {self.settings.llm_model}")
            self.llm.preload()
            detail = self._ready_detail()
            self._set_state(State.IDLE, detail)
            self._ui(lambda: self.overlay.set_meta(detail))
            if self.tray:
                self._ui(self.tray.refresh)
            threading.Thread(target=self._caption_loop, name="captions", daemon=True).start()
        except Exception as exc:
            self._set_state(State.ERROR, str(exc)[:80])
            self._ui(lambda: self.overlay.set_reply(str(exc)))

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
        out = []
        for item in self.llm.list_models():
            name = item.get("name") or item.get("model") or ""
            if not name:
                continue
            large = int(item.get("size") or 0) > 6 * 1024 * 1024 * 1024
            out.append((name, large))
        return out

    def apply_setting(self, field: str, value) -> None:
        if field in RESTART_FIELDS and str(getattr(self.settings, field)) != str(value):
            self.settings.update(**{field: value})
            self._ui(lambda: self.overlay.set_reply("Saved. Restart Bob to apply this setting."))
            if self.tray:
                self.tray.refresh()
            return
        self.settings.update(**{field: value})
        self._apply_live(field, value)
        if self.tray:
            self.tray.refresh()

    def apply_settings_dict(self, values: dict) -> None:
        restart = any(str(getattr(self.settings, k, None)) != str(v) for k, v in values.items() if k in RESTART_FIELDS)
        self.settings.update(**values)
        self.llm.host = self.settings.ollama_host.rstrip("/")
        self.llm.model = self.settings.llm_model
        self.llm.num_ctx = self.settings.llm_num_ctx
        self.llm.system_prompt = self.settings.system_prompt
        self.llm.max_turns = self.settings.max_history_turns
        self.tts.voice = self.settings.tts_voice
        self.wake.enabled = self.settings.wake_word_enabled
        self.wake.threshold = self.settings.wake_threshold
        if self.settings.wake_word != self.wake.model_name:
            self.wake.model_name = self.settings.wake_word
        self.set_overlay_visible(self.settings.show_overlay, persist=False)
        self.set_start_with_windows(self.settings.start_with_windows)
        if not self.settings.tools_enabled:
            self.tools.close_mcp()
        elif not self.tools.names():
            self._reload_tools()
        self._restart_hotkey()
        self._restart_audio()
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
        elif field == "wake_word_enabled":
            self.wake.enabled = bool(value)
        elif field == "wake_threshold":
            self.wake.threshold = float(value)
        elif field == "wake_word":
            self.wake.model_name = str(value)
        elif field == "hotkey":
            self._restart_hotkey()
        elif field in {"input_device", "output_device"}:
            self._restart_audio()
        elif field == "show_overlay":
            self.set_overlay_visible(bool(value), persist=False)
        elif field == "start_with_windows":
            self.set_start_with_windows(bool(value))
        elif field == "tools_enabled":
            self._reload_tools()
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
            )

        self._ui(show)

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
        self.audio.stop()
        self.audio.input_device = self.settings.input_device or None
        self.audio.output_device = self.settings.output_device or None
        self.audio.sample_rate = self.settings.sample_rate
        self.audio.start(on_chunk=self._enqueue_chunk)
        if listening:
            self.audio.start_listening()

    def _preload_safe(self) -> None:
        try:
            self.llm.preload()
        except Exception as exc:
            self._ui(lambda: self.overlay.set_reply(f"Model load failed: {exc}"))

    def _restore_llm_history(self) -> None:
        max_msgs = max(2, int(self.settings.max_history_turns) * 2)
        self.llm.history = [
            {"role": turn["role"], "content": turn["content"]}
            for turn in self._turns[-max_msgs:]
            if turn.get("role") in {"user", "assistant"}
        ]

    def _new_chat(self) -> None:
        self.llm.reset()
        self._session_id = self.chat.new_session()
        self._turns = []
        self._pending_user = ""
        self._pending_reply = "New conversation."
        self._refresh_talk()

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
        if state != State.LISTENING:
            return
        if rms(chunk) > 0.015:
            self._last_voice = time.monotonic()
            self._heard_speech = True
        timeout = float(self.settings.max_silence_sec or 0)
        if timeout > 0 and self._heard_speech:
            if time.monotonic() - self._last_voice >= timeout:
                self.toggle_listen()

    def _on_wake(self) -> None:
        if self.state == State.IDLE:
            self._ui(self._begin_listen)

    def toggle_listen(self) -> None:
        self._ui(self._toggle_from_ui)

    def _toggle_from_ui(self) -> None:
        state = self.state
        if state in {State.LOADING, State.ERROR}:
            return
        if state == State.SPEAKING:
            self._cancel.set()
            self.audio.stop_playback()
            self._begin_listen()
            return
        if state == State.THINKING:
            self._cancel.set()
            self.audio.stop_playback()
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
        messages = list(self._turns)
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
            pass
        if role == "user":
            self._pending_user = ""
        else:
            self._pending_reply = ""
        self._refresh_talk()

    def _restore_idle_ui(self) -> None:
        if self._overlay_viewable():
            self.overlay.set_phase("idle")

    def _begin_listen(self) -> None:
        self._cancel.set()
        self.audio.stop_playback()
        self._cancel.clear()
        self.audio.set_capture_muted(False)
        self._heard_speech = False
        self._last_voice = time.monotonic()
        self.audio.start_listening()
        self._present_talk("listen")
        self._talk_set_user("")
        self._talk_set_reply("")
        self._set_state(State.LISTENING, f"{self.settings.hotkey.upper()} to send")

    def _finish_listen(self) -> None:
        audio = self.audio.stop_listening()
        self._present_talk("reply")
        self._talk_set_reply("…")
        self._set_state(State.THINKING, "transcribing")
        self._pipeline_thread = threading.Thread(
            target=self._pipeline,
            args=(audio,),
            name="pipeline",
            daemon=True,
        )
        self._pipeline_thread.start()

    def _pipeline(self, audio) -> None:
        assistant_text = ""
        user_text = ""
        try:
            if audio.size < self.settings.sample_rate * 0.25:
                self._talk_set_user("(too short)")
                self._set_state(State.IDLE, self._ready_detail())
                self._ui(self._restore_idle_ui)
                return
            with self._stt_lock:
                user_text = self.stt.transcribe(audio, self.settings.sample_rate)
            if self._cancel.is_set():
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
            started = False
            for chunk in self.llm.chat(
                user_text,
                memory_block=memory_block,
                tools=self._tool_schemas(),
                on_tool=self._run_tool,
                cancel=self._cancel,
                max_rounds=int(self.settings.max_tool_rounds),
            ):
                if self._cancel.is_set():
                    return
                full += chunk
                pending += chunk
                self._talk_set_reply(full)
                sentences, pending = split_sentences(pending)
                for sentence in sentences:
                    if self._cancel.is_set():
                        return
                    self._speak_sentence(sentence, start=not started)
                    started = True
            leftover = pending.strip()
            if leftover and not self._cancel.is_set():
                self._speak_sentence(leftover, start=not started)
                started = True
            assistant_text = full.strip()
            if assistant_text:
                self._commit_turn("assistant", assistant_text)
            self.audio.wait_playback()
        except Exception as exc:
            self._talk_set_reply(f"Error: {exc}")
        finally:
            self.audio.set_capture_muted(False)
            if not self._cancel.is_set() and self.state != State.LISTENING:
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

    def _run_tool(self, name: str, arguments) -> str:
        self._set_state(State.THINKING, f"tool: {name}")
        ctx = self.tools.context(
            cancel=self._cancel,
            status=lambda msg: self._set_state(State.THINKING, msg),
        )
        result = self.tools.invoke(name, arguments, ctx=ctx, timeout=float(self.settings.tool_timeout_sec))
        self._set_state(State.THINKING, "ollama")
        return result

    def _ingest_memory(self, user_text: str, assistant_text: str) -> None:
        try:
            self.memory.ingest(user_text, assistant_text, self.llm.generate)
        except Exception:
            pass

    def _speak_sentence(self, sentence: str, start: bool) -> None:
        samples, sr = self.tts.synthesize(sentence)
        if self._cancel.is_set():
            return
        if start:
            self.audio.set_capture_muted(True)
            self._set_state(State.SPEAKING)
        self.audio.play(samples, sr)

    def _caption_loop(self) -> None:
        while not self._stop.is_set():
            if self.state == State.LISTENING:
                snap = self.audio.snapshot_listening()
                max_samples = self.settings.sample_rate * 8
                if snap.size > max_samples:
                    snap = snap[-max_samples:]
                if snap.size > self.settings.sample_rate * 0.8:
                    try:
                        if not self._stt_lock.acquire(blocking=False):
                            continue
                        try:
                            if self.state != State.LISTENING:
                                continue
                            text = self.stt.transcribe(snap, self.settings.sample_rate)
                        finally:
                            self._stt_lock.release()
                        if text and self.state == State.LISTENING:
                            self._talk_set_user(text + " …")
                    except Exception:
                        pass
            self._stop.wait(1.6)

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
    tts = TextToSpeech(MODELS_DIR / "kokoro", settings.tts_voice)
    print("kokoro:  loading ...")
    tts.load(on_status=print)
    samples, sr = tts.synthesize("Bob is ready.")
    print(f"kokoro:  {len(samples)} samples @ {sr} Hz")
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
    print(f"gpu:    {gpu_memory_line()}")
    print("check:  ok")
    return 0
