from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from bob.hotkeys import HotkeyRecorder
from bob.prompts import load_system_prompt
from bob.settings import Settings
from bob.ui import theme as theming
from bob.ui.theme import PRESET_KEYS, Theme, key_for_label, labels_for, preset, set_role
from bob.voice_mood import MOOD_NAMES as MOODS

STT_MODELS = (
    "parakeet-tdt-0.6b-v3",
    "large-v3-turbo",
    "distil-large-v3",
    "medium",
    "small",
)
COMPUTE = ("int8_float16", "int8", "float16")
CONTEXT_LENGTHS = ("2048", "4096", "8192", "16384", "32768")
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
TTS_PREVIEW_TEXT = "Hello, how are you doing today?"


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
        on_hotkey_changed: Callable[[str], None] | None = None,
        on_preview_voice: Callable[[str, float], None] | None = None,
        on_open_theme: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        theme = theming.current()
        self.title("BOB settings")
        from bob.win32_app import apply_tk_icon

        apply_tk_icon(self)
        self.geometry("560x640")
        self.attributes("-topmost", True)
        self.configure(**theme.window())
        self.settings = settings
        self.on_save = on_save
        self.on_recording = on_recording
        self.on_hotkey_changed = on_hotkey_changed
        self.on_preview_voice = on_preview_voice
        self.on_open_theme = on_open_theme
        self.on_close = on_close
        self.vars: dict[str, ctk.StringVar | ctk.BooleanVar] = {}
        self._recorder: HotkeyRecorder | None = None
        self._recording = False
        self.protocol("WM_DELETE_WINDOW", self._close)

        frame = ctk.CTkScrollableFrame(self, **theme.scroll_frame())
        frame.pack(fill="both", expand=True, padx=14, pady=12)

        self._section(frame, "Appearance")
        self._theme_combo(frame)
        self._hint(frame, "Colours and font can be tuned per preset in the theme editor.")
        if on_open_theme:
            set_role(
                ctk.CTkButton(frame, text="Customize theme…", command=self._open_theme, **theme.button("surface")),
                "surface",
            ).pack(fill="x", pady=(0, 4))
        self._section(frame, "Models and voice")

        self._combo(frame, "LLM model", "llm_model", llm_models or [settings.llm_model])
        self._combo(frame, "STT model", "stt_model", list(STT_MODELS))
        self._combo(frame, "STT compute", "stt_compute_type", list(COMPUTE))
        self._combo(frame, "Context tokens", "llm_num_ctx", list(CONTEXT_LENGTHS))
        self._voice_picker(frame)
        self._entry(frame, "TTS speed (0.5–2.0)", "tts_speed")
        self._combo(frame, "Default speech mood", "tts_mood", list(MOODS))
        self._combo(frame, "Wake word", "wake_word", list(WAKE_WORDS))
        self._check(frame, "Wake word enabled", "wake_word_enabled")
        self._entry(frame, "Wake threshold", "wake_threshold")
        self._hotkey_picker(frame)
        self._check(frame, "Auto-endpoint (send after a pause)", "auto_endpoint")
        self._entry(frame, "Endpoint silence (ms)", "endpoint_silence_ms")
        self._check(frame, "Voice barge-in", "barge_in")
        self._hint(
            frame,
            "Barge-in assumes headphones. On speakers BOB will hear himself and cut off.",
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
        self._section(frame, "Agents")
        self._check(frame, "Score tool replies with a validator", "validator_on_tools")
        self._entry(frame, "Reply score sample rate", "score_sample_rate")
        self._check(frame, "Prompt lab enabled", "prompt_lab_enabled")
        self._check(frame, "Auto-improve system prompt", "prompt_auto_improve")
        self._entry(frame, "Prompt lab min scored turns", "prompt_min_turns")
        self._entry(frame, "Prompt lab min improvement", "prompt_min_improve")
        self._entry(frame, "Prompt rollback delta", "prompt_rollback_delta")
        self._entry(frame, "Prompt cooldown hours", "prompt_cooldown_hours")

        ctk.CTkLabel(frame, text="System prompt", anchor="w", **theme.label_style()).pack(fill="x", pady=(10, 2))
        self.prompt = ctk.CTkTextbox(frame, height=120, **theme.textbox())
        self.prompt.pack(fill="x")
        self.prompt.insert("1.0", load_system_prompt())

        self.error = set_role(
            ctk.CTkLabel(self, text="", text_color=theme.error, wraplength=520, justify="left"),
            "status",
        )
        self.error.pack(fill="x", padx=14)
        ctk.CTkButton(self, text="Save", command=self._save, **theme.button()).pack(pady=10)

    def apply_theme(self, theme: Theme) -> None:
        theming.restyle(self, theme)
        self.error.configure(text_color=theme.error)

    def _open_theme(self) -> None:
        if self.on_open_theme:
            self.on_open_theme()

    def _theme_combo(self, parent) -> None:
        theme = theming.current()
        ctk.CTkLabel(parent, text="Theme preset", anchor="w", **theme.label_style()).pack(fill="x", pady=(8, 2))
        var = ctk.StringVar(value=preset(self.settings.theme).title)
        self.vars["theme"] = var
        ctk.CTkComboBox(
            parent,
            values=labels_for(PRESET_KEYS),
            variable=var,
            state="readonly",
            **theme.combo(),
        ).pack(fill="x")

    def _section(self, parent, title: str) -> None:
        theme = theming.current()
        set_role(
            ctk.CTkLabel(parent, text=title.upper(), anchor="w", font=theme.font(11, "bold"), **theme.label_style(muted=True)),
            "muted",
        ).pack(fill="x", pady=(14, 0))

    def _hotkey_picker(self, parent) -> None:
        theme = theming.current()
        ctk.CTkLabel(parent, text="Hotkey", anchor="w", **theme.label_style()).pack(fill="x", pady=(8, 2))
        var = ctk.StringVar(value=str(self.settings.hotkey))
        self.vars["hotkey"] = var
        self._hotkey_btn = ctk.CTkButton(
            parent,
            text=var.get().upper(),
            command=self._toggle_hotkey_capture,
            **theme.button(),
        )
        self._hotkey_btn.pack(fill="x")
        self._hotkey_hint = set_role(
            ctk.CTkLabel(
                parent,
                text="Click, then press a key combination. It saves immediately.",
                anchor="w",
                font=theme.font(12),
                **theme.label_style(muted=True),
            ),
            "muted",
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
            if self.on_hotkey_changed:
                self.on_hotkey_changed(spec)
        if self._hotkey_btn.winfo_exists():
            self._hotkey_btn.configure(text=str(self.vars["hotkey"].get()).upper())
            self._hotkey_hint.configure(text="Click, then press a key combination. It saves immediately.")
        if self.on_recording:
            self.on_recording(False)

    def _close(self) -> None:
        self._finish_hotkey_capture(None)
        if self.on_close:
            self.on_close()
        self.destroy()

    def _entry(self, parent, label: str, key: str) -> None:
        theme = theming.current()
        ctk.CTkLabel(parent, text=label, anchor="w", **theme.label_style()).pack(fill="x", pady=(8, 2))
        var = ctk.StringVar(value=str(getattr(self.settings, key)))
        self.vars[key] = var
        ctk.CTkEntry(parent, textvariable=var, **theme.entry()).pack(fill="x")

    def _combo(self, parent, label: str, key: str, values: list[str]) -> None:
        theme = theming.current()
        ctk.CTkLabel(parent, text=label, anchor="w", **theme.label_style()).pack(fill="x", pady=(8, 2))
        current = str(getattr(self.settings, key) or "")
        if current and current not in values:
            values = [current, *values]
        var = ctk.StringVar(value=current)
        self.vars[key] = var
        ctk.CTkComboBox(
            parent,
            values=values or [""],
            variable=var,
            state="readonly",
            **theme.combo(),
        ).pack(fill="x")

    def _voice_picker(self, parent) -> None:
        theme = theming.current()
        ctk.CTkLabel(parent, text="TTS voice", anchor="w", **theme.label_style()).pack(fill="x", pady=(8, 2))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        current = str(self.settings.tts_voice or "")
        values = list(VOICES)
        if current and current not in values:
            values = [current, *values]
        var = ctk.StringVar(value=current)
        self.vars["tts_voice"] = var
        ctk.CTkComboBox(row, values=values, variable=var, state="readonly", **theme.combo()).pack(
            side="left", fill="x", expand=True
        )
        set_role(
            ctk.CTkButton(
                row,
                text="Preview",
                width=88,
                command=self._preview_voice,
                **theme.button("surface"),
            ),
            "surface",
        ).pack(side="right", padx=(8, 0))
        self._hint(parent, f'Preview plays: "{TTS_PREVIEW_TEXT}"')

    def _preview_voice(self) -> None:
        if not self.on_preview_voice:
            return
        voice = str(self.vars["tts_voice"].get()).strip()
        if not voice:
            return
        try:
            speed = float(str(self.vars["tts_speed"].get()).strip() or "1.0")
        except ValueError:
            speed = 1.0
        self.on_preview_voice(voice, speed)

    def _hint(self, parent, text: str) -> None:
        theme = theming.current()
        set_role(
            ctk.CTkLabel(
                parent,
                text=text,
                anchor="w",
                font=theme.font(12),
                wraplength=500,
                **theme.label_style(muted=True),
            ),
            "muted",
        ).pack(fill="x", pady=(0, 4))

    def _check(self, parent, label: str, key: str) -> None:
        theme = theming.current()
        var = ctk.BooleanVar(value=bool(getattr(self.settings, key)))
        self.vars[key] = var
        ctk.CTkCheckBox(parent, text=label, variable=var, **theme.check()).pack(anchor="w", pady=6)

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
            "prompt_min_turns",
            "endpoint_silence_ms",
            "barge_in_speech_ms",
            "stt_partial_interval_ms",
            "stt_commit_silence_ms",
        }
        floats = {
            "wake_threshold",
            "vad_threshold",
            "max_silence_sec",
            "tool_timeout_sec",
            "tts_speed",
            "score_sample_rate",
            "prompt_min_improve",
            "prompt_rollback_delta",
            "prompt_cooldown_hours",
        }
        problems: list[str] = []
        for key, value in raw.items():
            try:
                if key in ints:
                    typed[key] = int(float(str(value).strip() or 0))
                elif key in floats:
                    typed[key] = float(str(value).strip() or 0)
                else:
                    typed[key] = value
            except (TypeError, ValueError):
                problems.append(f"{key.replace('_', ' ')}: '{value}' is not a number")
        if "theme" in typed:
            choice = str(typed["theme"] or "").strip()
            typed["theme"] = choice if choice in PRESET_KEYS else key_for_label(choice)
        problems.extend(_validate(typed))
        if problems:
            self.error.configure(text="\n".join(problems[:4]))
            return
        self._finish_hotkey_capture(None)
        self.on_save(typed)
        if self.on_close:
            self.on_close()
        self.destroy()


def _validate(values: dict) -> list[str]:
    """Range checks for values that would otherwise break audio or the model."""
    out: list[str] = []
    checks = (
        ("llm_num_ctx", 512, 131072),
        ("sample_rate", 8000, 48000),
        ("max_history_turns", 1, 200),
        ("memory_max_inject", 0, 50),
        ("max_tool_rounds", 1, 10),
        ("prompt_min_turns", 1, 1000),
        ("endpoint_silence_ms", 100, 10000),
        ("barge_in_speech_ms", 50, 5000),
        ("stt_partial_interval_ms", 50, 5000),
        ("stt_commit_silence_ms", 100, 10000),
        ("wake_threshold", 0.0, 1.0),
        ("vad_threshold", 0.0, 1.0),
        ("tool_timeout_sec", 1.0, 600.0),
        ("tts_speed", 0.5, 2.0),
        ("score_sample_rate", 0.0, 1.0),
        ("prompt_min_improve", 0.0, 1.0),
        ("prompt_rollback_delta", 0.0, 1.0),
        ("prompt_cooldown_hours", 0.0, 720.0),
    )
    for key, low, high in checks:
        if key in values and not (low <= values[key] <= high):
            out.append(f"{key.replace('_', ' ')} must be between {low} and {high}")
    if "hotkey" in values:
        try:
            from bob.hotkeys import parse_hotkey

            parse_hotkey(str(values["hotkey"]))
        except ValueError as exc:
            out.append(str(exc))
    return out
