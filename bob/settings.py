from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from bob.prompts import load_system_prompt

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
MODELS_DIR = ROOT / "models"
DATA_DIR = ROOT / "data"


@dataclass
class Settings:
    llm_model: str = "qwen3:4b"
    stt_model: str = "parakeet-tdt-0.6b-v3"
    stt_compute_type: str = "int8_float16"
    llm_num_ctx: int = 4096
    tts_voice: str = "af_heart"
    tts_speed: float = 1.0
    tts_mood: str = "neutral"
    wake_word: str = "hey_jarvis"
    wake_word_enabled: bool = True
    wake_threshold: float = 0.5
    hotkey: str = "ctrl+shift+space"
    max_silence_sec: float = 0.2
    auto_endpoint: bool = True
    endpoint_silence_ms: int = 700
    turn_detector: str = "smart_turn"
    turn_min_silence_ms: int = 200
    turn_max_silence_ms: int = 800
    barge_in: bool = True
    barge_in_speech_ms: int = 250
    stt_partial_interval_ms: int = 500
    stt_commit_silence_ms: int = 500
    vad_threshold: float = 0.5
    sample_rate: int = 16000
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_gpu_overhead: int = 1610612736
    max_history_turns: int = 12
    system_prompt: str = field(default_factory=load_system_prompt)
    show_overlay: bool = True
    start_with_windows: bool = False
    input_device: str = ""
    output_device: str = ""
    wasapi_exclusive: bool = False
    memory_autosave: bool = True
    memory_max_inject: int = 8
    tools_enabled: bool = True
    tool_timeout_sec: float = 20.0
    max_tool_rounds: int = 4
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    # UI theme: a preset name from bob.ui.theme.PRESETS plus per-slot overrides
    # (e.g. {"accent": "#ff8800", "font_family": "Consolas", "appearance": "light"}).
    theme: str = "midnight"
    theme_overrides: dict[str, str] = field(default_factory=dict)

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.write_text(yaml.safe_dump(asdict(self), sort_keys=False), encoding="utf-8")

    def update(self, **kwargs: Any) -> None:
        known = {f.name for f in fields(self)}
        for key, value in kwargs.items():
            if key in known:
                if key == "hotkey":
                    value = str(value or "").strip().lower()
                setattr(self, key, value)
        self.save()


def load_settings(path: Path = CONFIG_PATH) -> Settings:
    data: dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    known = {f.name for f in Settings.__dataclass_fields__.values()}
    coerced: dict[str, Any] = {}
    for key, value in data.items():
        if key not in known:
            continue
        coerced[key] = value
    if "endpoint_silence_ms" not in coerced and "max_silence_sec" in coerced:
        try:
            sec = float(coerced.get("max_silence_sec") or 0)
        except (TypeError, ValueError):
            sec = 0.0
        if sec > 0:
            coerced["endpoint_silence_ms"] = int(sec * 1000)
            coerced.setdefault("auto_endpoint", True)
    if not isinstance(coerced.get("theme_overrides", {}), dict):
        coerced["theme_overrides"] = {}
    if "theme" in coerced:
        coerced["theme"] = str(coerced["theme"] or "midnight")
    if "tts_mood" in coerced:
        from bob.voice_mood import resolve_mood

        coerced["tts_mood"] = resolve_mood(coerced.get("tts_mood"))
    if "hotkey" in coerced:
        coerced["hotkey"] = str(coerced.get("hotkey") or "").strip().lower()
    if "turn_detector" in coerced:
        mode = str(coerced.get("turn_detector") or "smart_turn").strip().lower()
        coerced["turn_detector"] = mode if mode in {"smart_turn", "silence"} else "smart_turn"
    if "system_prompt" not in coerced:
        coerced["system_prompt"] = load_system_prompt()
    return Settings(**coerced)
