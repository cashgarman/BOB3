from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
MODELS_DIR = ROOT / "models"
DATA_DIR = ROOT / "data"


@dataclass
class Settings:
    llm_model: str = "qwen2.5:latest"
    stt_model: str = "large-v3-turbo"
    stt_compute_type: str = "int8_float16"
    llm_num_ctx: int = 4096
    tts_voice: str = "af_heart"
    wake_word: str = "hey_jarvis"
    wake_word_enabled: bool = True
    wake_threshold: float = 0.5
    hotkey: str = "ctrl+shift+space"
    max_silence_sec: float = 0.0
    sample_rate: int = 16000
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_gpu_overhead: int = 1610612736
    max_history_turns: int = 12
    system_prompt: str = (
        "You are Bob, a local voice assistant. Speak in short, natural sentences "
        "meant to be heard aloud. No markdown, bullet lists, or code fences unless "
        "the user asks. Keep answers concise."
    )
    show_overlay: bool = True
    start_with_windows: bool = False
    input_device: str = ""
    output_device: str = ""
    memory_autosave: bool = True
    memory_max_inject: int = 8
    tools_enabled: bool = True
    tool_timeout_sec: float = 20.0
    max_tool_rounds: int = 4
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.write_text(yaml.safe_dump(asdict(self), sort_keys=False), encoding="utf-8")

    def update(self, **kwargs: Any) -> None:
        known = {f.name for f in fields(self)}
        for key, value in kwargs.items():
            if key in known:
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
    return Settings(**coerced)
