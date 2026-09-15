"""JSON progress file shared by the setup UI and install scripts."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

_WRITE_ATTEMPTS = 12
_WRITE_RETRY_DELAY = 0.05

STATUS_NAME = "bob-install.json"
CANCEL_NAME = "bob-install.cancel"
LOG_NAME = "bob-install.log"

# Steps 1–3: Ollama, MSI, Python deps. Steps 4–11: bootstrap model stages.
INSTALL_STEPS = 11
BOOTSTRAP_STEP_START = 4
BOOTSTRAP_STAGE_COUNT = 8
BOOTSTRAP_STAGE_DURATIONS_SECONDS = (30, 300, 180, 90, 45, 45, 120, 30)


class InstallCancelled(RuntimeError):
    """Raised when the user cancels the installer."""


def _default_state_dir() -> Path:
    base = (os.environ.get("LOCALAPPDATA") or "").strip() or tempfile.gettempdir()
    return Path(base) / "BOB" / "setup"


def status_path() -> Path:
    override = (os.environ.get("BOB_INSTALL_PROGRESS") or "").strip()
    if override:
        return Path(override)
    return _default_state_dir() / STATUS_NAME


def cancel_path() -> Path:
    override = (os.environ.get("BOB_INSTALL_CANCEL") or "").strip()
    if override:
        return Path(override)
    return _default_state_dir() / CANCEL_NAME


def log_path() -> Path:
    override = (os.environ.get("BOB_INSTALL_LOG") or "").strip()
    if override:
        return Path(override)
    return _default_state_dir() / LOG_NAME


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_err: OSError | None = None
    for attempt in range(_WRITE_ATTEMPTS):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{attempt}.tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            return
        except OSError as exc:
            last_err = exc
            time.sleep(_WRITE_RETRY_DELAY * (attempt + 1))
        finally:
            try:
                if tmp.is_file():
                    tmp.unlink()
            except OSError:
                pass
    if last_err is not None:
        raise last_err
    raise OSError(f"could not write {path}")


def log_command(command: str) -> None:
    append_log("> " + command.strip())


def log_note(message: str) -> None:
    text = (message or "").strip()
    if text:
        append_log("  " + text)


def log_phase(step: int | None, message: str) -> None:
    text = (message or "").strip()
    if not text:
        return
    if step is not None and step > 0:
        append_log(f"[step {step}] {text}")
    else:
        append_log(text)


def append_log(line: str) -> None:
    text = line.rstrip()
    if not text:
        return
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    last_err: OSError | None = None
    for attempt in range(_WRITE_ATTEMPTS):
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(text + "\n")
            return
        except OSError as exc:
            last_err = exc
            time.sleep(_WRITE_RETRY_DELAY * (attempt + 1))
    if last_err is not None:
        raise last_err


def clear_log() -> None:
    path = log_path()
    if path.is_file():
        path.unlink()


def clear_cancel() -> None:
    path = cancel_path()
    if path.is_file():
        path.unlink()


def request_cancel() -> None:
    cancel_path().write_text("1", encoding="utf-8")


def cancel_requested() -> bool:
    return cancel_path().is_file()


def check_cancel() -> None:
    if cancel_requested():
        raise InstallCancelled("Installation cancelled.")


def write_progress(
    *,
    phase: str,
    message: str,
    overall: float | None = None,
    stage: float | None = None,
    completed: int | None = None,
    total: int | None = None,
    rate_bps: float | None = None,
    eta_seconds: float | None = None,
    step_eta_seconds: float | None = None,
    step_duration_seconds: float | None = None,
    overall_eta_seconds: float | None = None,
    step: int | None = None,
    step_total: int | None = None,
    error: str | None = None,
    detail: str | None = None,
    done: bool = False,
    cancelled: bool = False,
) -> Path:
    payload: dict[str, Any] = {
        "phase": phase,
        "message": message,
        "detail": detail,
        "overall": None if overall is None else max(0.0, min(1.0, float(overall))),
        "stage": None if stage is None else max(0.0, min(1.0, float(stage))),
        "completed": completed,
        "total": total,
        "rate_bps": rate_bps,
        "eta_seconds": eta_seconds,
        "step_eta_seconds": step_eta_seconds,
        "step_duration_seconds": step_duration_seconds,
        "overall_eta_seconds": overall_eta_seconds,
        "step": step,
        "step_total": step_total,
        "error": error,
        "done": done,
        "cancelled": cancelled,
        "updated_at": time.time(),
    }
    path = status_path()
    _atomic_write_text(path, json.dumps(payload))
    return path


def read_progress() -> dict[str, Any]:
    path = status_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def format_bytes(n: int | float | None) -> str:
    if n is None:
        return ""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(n)} B"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds > 86400:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s remaining"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s remaining"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m remaining"


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds > 86400:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m" if secs == 0 else f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def format_rate(rate_bps: float | None) -> str:
    if rate_bps is None or rate_bps <= 0:
        return ""
    return f"{format_bytes(rate_bps)}/s"
