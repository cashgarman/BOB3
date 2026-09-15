from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bob.paths import project_root
from bob.prompts import PROMPTS_DIR, load_system_prompt, save_system_prompt

VERSIONS_DIR = PROMPTS_DIR / "versions"
STATE_NAME = "prompt_lab.json"
SPOKEN_STYLE_MARKERS = ("aloud", "spoken", "markdown", "bullet")


@dataclass
class PromptLabState:
    current_version: int = 0
    applied_score: float = 0.0
    last_apply_at: float = 0.0
    cooldown_until: float = 0.0
    pinned: bool = False
    history: list[dict] = field(default_factory=list)


def state_path(data_dir: Path | None = None) -> Path:
    root = Path(data_dir) if data_dir is not None else project_root() / "data"
    return root / STATE_NAME


def load_state(data_dir: Path | None = None) -> PromptLabState:
    path = state_path(data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PromptLabState()
    if not isinstance(raw, dict):
        return PromptLabState()
    history = raw.get("history") if isinstance(raw.get("history"), list) else []
    return PromptLabState(
        current_version=int(raw.get("current_version") or 0),
        applied_score=float(raw.get("applied_score") or 0.0),
        last_apply_at=float(raw.get("last_apply_at") or 0.0),
        cooldown_until=float(raw.get("cooldown_until") or 0.0),
        pinned=bool(raw.get("pinned")),
        history=list(history),
    )


def save_state(state: PromptLabState, data_dir: Path | None = None) -> None:
    path = state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def current_version(data_dir: Path | None = None) -> int:
    return int(load_state(data_dir).current_version or 0)


def version_path(version: int) -> Path:
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return VERSIONS_DIR / f"system.v{int(version)}.txt"


def snapshot_current(data_dir: Path | None = None) -> PromptLabState:
    """Ensure the live system prompt is version 1 if nothing has been stored yet."""
    state = load_state(data_dir)
    if state.current_version > 0 and version_path(state.current_version).is_file():
        return state
    text = load_system_prompt()
    state.current_version = max(1, state.current_version)
    version_path(state.current_version).write_text(text.strip() + "\n", encoding="utf-8")
    save_state(state, data_dir)
    return state


def prompt_preserves_spoken_style(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t or len(t) > 4000:
        return False
    return sum(1 for marker in SPOKEN_STYLE_MARKERS if marker in t) >= 2


def apply_prompt(text: str, *, score: float = 0.0, data_dir: Path | None = None) -> PromptLabState:
    cleaned = (text or "").strip()
    if not prompt_preserves_spoken_style(cleaned):
        raise ValueError("candidate prompt dropped BOB's spoken-style rules")
    state = snapshot_current(data_dir)
    nxt = int(state.current_version) + 1
    version_path(nxt).write_text(cleaned + "\n", encoding="utf-8")
    save_system_prompt(cleaned)
    state.history.append(
        {
            "from": state.current_version,
            "to": nxt,
            "at": time.time(),
            "score": float(score),
        }
    )
    state.current_version = nxt
    state.applied_score = float(score)
    state.last_apply_at = time.time()
    state.pinned = False
    save_state(state, data_dir)
    return state


def rollback_prompt(*, cooldown_hours: float = 24.0, data_dir: Path | None = None) -> PromptLabState | None:
    state = load_state(data_dir)
    prev = int(state.current_version) - 1
    if prev < 1:
        path = version_path(state.current_version)
        if path.is_file():
            save_system_prompt(path.read_text(encoding="utf-8"))
        return None
    path = version_path(prev)
    if not path.is_file():
        return None
    save_system_prompt(path.read_text(encoding="utf-8"))
    state.history.append({"from": state.current_version, "to": prev, "at": time.time(), "rollback": True})
    state.current_version = prev
    state.pinned = True
    state.cooldown_until = time.time() + max(0.0, float(cooldown_hours)) * 3600.0
    save_state(state, data_dir)
    return state


def in_cooldown(state: PromptLabState | None = None, data_dir: Path | None = None) -> bool:
    state = state or load_state(data_dir)
    return bool(state.pinned) or (state.cooldown_until > time.time())
