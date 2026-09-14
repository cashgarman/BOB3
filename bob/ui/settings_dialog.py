from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from bob.hotkeys import HotkeyRecorder
from bob.settings import Settings

STT_MODELS = ("large-v3-turbo", "distil-large-v3", "medium", "small")
COMPUTE = ("int8_float16", "int8", "float16")
WAKE_WORDS = ("hey_jarvis", "hey_mycroft", "alexa", "hey_rhasspy")
VOICES = (
    "af_heart",
    "af_bella",
    "af_nicole",
    "af_sarah",
    "am_adam",
    "am_michael",
    "am_echo",
    "bf_emma",
    "bm_george",
    "bm_lewis",
)


class SettingsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        settings: Settings,
        on_save: Callable[[dict], None],
        llm_models: list[str],
        inputs: list[str],
        outputs: list[str],
        on_recording: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.title("Bob settings")
        self.geometry("560x640")
        self.attributes("-topmost", True)
        self.settings = settings
        self.on_save = on_save
        self.on_recording = on_recording
        self.vars: dict[str, ctk.StringVar | ctk.BooleanVar] = {}
        self._recorder: HotkeyRecorder | None = None
        self._recording = False
        self.protocol("WM_DELETE_WINDOW", self._close)

        frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=14, pady=12)

        self._combo(frame, "LLM model", "llm_model", llm_models or [settings.llm_model])
        self._combo(frame, "STT model", "stt_model", list(STT_MODELS))
        self._combo(frame, "STT compute", "stt_compute_type", list(COMPUTE))
        self._entry(frame, "Context tokens", "llm_num_ctx")
        self._combo(frame, "TTS voice", "tts_voice", list(VOICES))
        self._combo(frame, "Wake word", "wake_word", list(WAKE_WORDS))
        self._check(frame, "Wake word enabled", "wake_word_enabled")
        self._entry(frame, "Wake threshold", "wake_threshold")
        self._hotkey_picker(frame)
        self._check(frame, "Auto-endpoint (send after a pause)", "auto_endpoint")
        self._entry(frame, "Endpoint silence (ms)", "endpoint_silence_ms")
        self._check(frame, "Voice barge-in", "barge_in")
        self._hint(
            frame,
            "Barge-in assumes headphones. On speakers Bob will hear himself and cut off.",
        )
        self._entry(frame, "Barge-in speech (ms)", "barge_in_speech_ms")
        self._entry(frame, "STT partial interval (ms)", "stt_partial_interval_ms")
        self._entry(frame, "STT commit silence (ms)", "stt_commit_silence_ms")
        self._entry(frame, "VAD threshold", "vad_threshold")
        self._entry(frame, "Sample rate", "sample_rate")
        self._entry(frame, "Ollama host", "ollama_host")
        self._entry(frame, "Ollama GPU overhead bytes", "ollama_gpu_overhead")
        self._entry(frame, "History turns", "max_history_turns")
        self._combo(frame, "Input device", "input_device", [""] + inputs)
        self._combo(frame, "Output device", "output_device", [""] + outputs)
        self._check(frame, "Show overlay", "show_overlay")
        self._check(frame, "Start with Windows", "start_with_windows")
        self._check(frame, "Memory autosave", "memory_autosave")
        self._entry(frame, "Max memories injected", "memory_max_inject")
        self._check(frame, "Tools enabled", "tools_enabled")
        self._entry(frame, "Tool timeout seconds", "tool_timeout_sec")
        self._entry(frame, "Max tool rounds per turn", "max_tool_rounds")

        ctk.CTkLabel(frame, text="System prompt", anchor="w").pack(fill="x", pady=(10, 2))
        self.prompt = ctk.CTkTextbox(frame, height=120)
        self.prompt.pack(fill="x")
        self.prompt.insert("1.0", settings.system_prompt)

        ctk.CTkButton(self, text="Save", command=self._save).pack(pady=10)

    def _hotkey_picker(self, parent) -> None:
        ctk.CTkLabel(parent, text="Hotkey", anchor="w").pack(fill="x", pady=(8, 2))
        var = ctk.StringVar(value=str(self.settings.hotkey))
        self.vars["hotkey"] = var
        self._hotkey_btn = ctk.CTkButton(
            parent,
            text=var.get().upper(),
            command=self._toggle_hotkey_capture,
        )
        self._hotkey_btn.pack(fill="x")
        self._hotkey_hint = ctk.CTkLabel(
            parent,
            text="Click, then press any key combination. The next key is stored.",
            anchor="w",
            text_color="#6b7280",
            font=("Segoe UI", 12),
        )
        self._hotkey_hint.pack(fill="x", pady=(2, 0))

    def _toggle_hotkey_capture(self) -> None:
        if self._recording:
            self._finish_hotkey_capture(None)
            return
        self._recording = True
        self._hotkey_btn.configure(text="Press any key…")
        self._hotkey_hint.configure(text="Waiting for a key. Click again to cancel.")
        if self.on_recording:
            self.on_recording(True)
        self._recorder = HotkeyRecorder()
        self._recorder.start(lambda spec: self.after(0, lambda s=spec: self._finish_hotkey_capture(s)))

    def _finish_hotkey_capture(self, spec: str | None) -> None:
        recorder = self._recorder
        self._recorder = None
        self._recording = False
        if recorder:
            recorder.stop()
        if spec:
            self.vars["hotkey"].set(spec)
        if self._hotkey_btn.winfo_exists():
            self._hotkey_btn.configure(text=str(self.vars["hotkey"].get()).upper())
            self._hotkey_hint.configure(text="Click, then press any key combination. The next key is stored.")
        if self.on_recording:
            self.on_recording(False)

    def _close(self) -> None:
        self._finish_hotkey_capture(None)
        self.destroy()

    def _entry(self, parent, label: str, key: str) -> None:
        ctk.CTkLabel(parent, text=label, anchor="w").pack(fill="x", pady=(8, 2))
        var = ctk.StringVar(value=str(getattr(self.settings, key)))
        self.vars[key] = var
        ctk.CTkEntry(parent, textvariable=var).pack(fill="x")

    def _combo(self, parent, label: str, key: str, values: list[str]) -> None:
        ctk.CTkLabel(parent, text=label, anchor="w").pack(fill="x", pady=(8, 2))
        current = str(getattr(self.settings, key) or "")
        if current and current not in values:
            values = [current, *values]
        var = ctk.StringVar(value=current)
        self.vars[key] = var
        ctk.CTkComboBox(parent, values=values or [""], variable=var).pack(fill="x")

    def _hint(self, parent, text: str) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            text_color="#6b7280",
            font=("Segoe UI", 12),
            wraplength=500,
        ).pack(fill="x", pady=(0, 4))

    def _check(self, parent, label: str, key: str) -> None:
        var = ctk.BooleanVar(value=bool(getattr(self.settings, key)))
        self.vars[key] = var
        ctk.CTkCheckBox(parent, text=label, variable=var).pack(anchor="w", pady=6)

    def _save(self) -> None:
        raw = {key: var.get() for key, var in self.vars.items()}
        raw["system_prompt"] = self.prompt.get("1.0", "end").strip()
        typed = {}
        ints = {
            "llm_num_ctx",
            "sample_rate",
            "ollama_gpu_overhead",
            "max_history_turns",
            "memory_max_inject",
            "max_tool_rounds",
            "endpoint_silence_ms",
            "barge_in_speech_ms",
            "stt_partial_interval_ms",
            "stt_commit_silence_ms",
        }
        floats = {"wake_threshold", "vad_threshold", "max_silence_sec", "tool_timeout_sec"}
        for key, value in raw.items():
            if key in ints:
                typed[key] = int(float(value or 0))
            elif key in floats:
                typed[key] = float(value or 0)
            else:
                typed[key] = value
        self._finish_hotkey_capture(None)
        self.on_save(typed)
        self.destroy()
