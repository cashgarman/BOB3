"""Run pip with stderr progress parsing for the setup UI."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

_PKG = Path(__file__).resolve().parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from install_progress import (
    InstallCancelled,
    append_log,
    cancel_requested,
    check_cancel,
    format_bytes,
    format_eta,
    log_note,
    write_progress,
)

_PIP_LOG_MARKERS = (
    "Collecting ",
    "Downloading ",
    "Installing ",
    "Building ",
    "Successfully installed",
    "Requirement already satisfied",
    "ERROR:",
    "WARNING:",
    "Failed ",
)

_LINE_RE = re.compile(
    r"(?P<done>\d+(?:\.\d+)?)\s*/\s*(?P<total>\d+(?:\.\d+)?)\s*(?P<unit>[KMGT]?i?B)"
    r"(?:\s+(?P<rate>\d+(?:\.\d+)?\s*(?:[KMGT]?i?B/s|MB/s|kB/s|MiB/s)))?"
    r"(?:\s+eta\s+(?P<eta>\d+:\d+(?::\d+)?))?",
    re.IGNORECASE,
)
_SIZE_RE = re.compile(r"\((\d+(?:\.\d+)?)\s*([KMGT]?i?B)\)", re.IGNORECASE)
_RATE_RE = re.compile(
    r"(?P<rate>\d+(?:\.\d+)?)\s*(?P<unit>[KMGT]?i?B)/s",
    re.IGNORECASE,
)


def _to_bytes(value: float, unit: str) -> int:
    unit = unit.upper().replace("IB", "B").rstrip("B")
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    key = unit if unit in mult else unit[:1]
    return int(value * mult.get(key, 1))


def _parse_eta(text: str) -> float | None:
    parts = text.strip().split(":")
    try:
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    return None


def _parse_rate(text: str) -> float | None:
    match = _RATE_RE.search(text)
    if not match:
        return None
    return float(_to_bytes(float(match.group("rate")), match.group("unit")))


class PipProgressTracker:
    STEP_DURATION_SECONDS = 900.0

    def __init__(
        self,
        *,
        overall_start: float,
        overall_span: float,
        step: int,
        step_total: int,
        label: str,
    ) -> None:
        self.overall_start = overall_start
        self.overall_span = overall_span
        self.step = step
        self.step_total = step_total
        self.label = label
        self._last_emit = 0.0
        self._last_completed = 0
        self._last_time = time.time()
        self._announced_total = 0
        self._completed_files_bytes = 0
        self._current_file_done = 0
        self._current_file_total = 0
        self._announced_packages: set[str] = set()

    def _session_totals(self) -> tuple[int, int]:
        done = self._completed_files_bytes + self._current_file_done
        total = max(self._announced_total, done)
        if self._current_file_total > 0:
            total = max(total, self._completed_files_bytes + self._current_file_total)
        return done, total

    def _announce_package(self, text: str, size_bytes: int) -> None:
        key = text.strip()
        if not key or key in self._announced_packages:
            return
        self._announced_packages.add(key)
        log_note(key)
        if self._current_file_total > 0 and self._current_file_done < self._current_file_total:
            self._completed_files_bytes += self._current_file_done
        self._current_file_done = 0
        self._current_file_total = size_bytes
        self._announced_total += size_bytes

    def emit(
        self,
        *,
        detail: str | None = None,
        stage: float | None = None,
        completed: int | None = None,
        total: int | None = None,
        rate_bps: float | None = None,
        eta_seconds: float | None = None,
    ) -> None:
        now = time.time()
        if completed is not None and total and completed > self._last_completed:
            dt = max(now - self._last_time, 0.001)
            if rate_bps is None:
                rate_bps = (completed - self._last_completed) / dt
            self._last_completed = completed
            self._last_time = now
            if eta_seconds is None and rate_bps > 0:
                eta_seconds = (total - completed) / rate_bps
        overall = self.overall_start
        if stage is not None:
            overall += self.overall_span * max(0.0, min(1.0, stage))
        elif completed is not None and total:
            overall += self.overall_span * (completed / max(total, 1))
        step_eta = eta_seconds
        overall_eta = None
        if eta_seconds is not None and total and completed is not None and total > completed:
            overall_eta = eta_seconds + max(0.0, (1.0 - overall) * self.STEP_DURATION_SECONDS * 2.0)
        write_progress(
            phase="pip",
            message=self.label,
            detail=detail,
            overall=overall,
            stage=stage,
            completed=completed,
            total=total,
            rate_bps=rate_bps,
            eta_seconds=eta_seconds,
            step_eta_seconds=step_eta,
            step_duration_seconds=self.STEP_DURATION_SECONDS,
            overall_eta_seconds=overall_eta,
            step=self.step,
            step_total=self.step_total,
        )
        self._last_emit = now

    def _maybe_log_pip_line(self, text: str) -> None:
        if any(marker in text for marker in _PIP_LOG_MARKERS):
            log_note(text)

    def handle_line(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        if "Using cached" in text:
            log_note(text)
            self.emit(detail=text, stage=0.95)
            return
        match = _LINE_RE.search(text)
        if match:
            done = _to_bytes(float(match.group("done")), match.group("unit"))
            total = _to_bytes(float(match.group("total")), match.group("unit"))
            if total > 0 and self._current_file_total == 0:
                self._announce_package(text, total)
            self._current_file_done = done
            self._current_file_total = max(self._current_file_total, total)
            if done >= total and total > 0:
                log_note(f"completed {format_bytes(total)}")
                self._completed_files_bytes += total
                self._current_file_done = 0
                self._current_file_total = 0
            session_done, session_total = self._session_totals()
            rate_bps = _parse_rate(text)
            eta = _parse_eta(match.group("eta") or "") if match.group("eta") else None
            detail = f"{format_bytes(session_done)} / {format_bytes(session_total)} downloaded"
            if rate_bps:
                detail += f"  {format_bytes(rate_bps)}/s"
            if eta is not None:
                detail += f"  {format_eta(eta)}"
            stage = session_done / max(session_total, 1) if session_total else done / max(total, 1)
            self.emit(
                detail=detail,
                stage=stage,
                completed=session_done,
                total=session_total,
                rate_bps=rate_bps,
                eta_seconds=eta,
            )
            return
        size_match = _SIZE_RE.search(text)
        self._maybe_log_pip_line(text)
        if "Downloading" in text or "Collecting" in text:
            detail = text
            if size_match and "Downloading" in text:
                size_bytes = _to_bytes(float(size_match.group(1)), size_match.group(2))
                self._announce_package(text, size_bytes)
                session_done, session_total = self._session_totals()
                detail = f"{text}  ({format_bytes(size_bytes)})  ·  {format_bytes(session_total)} total"
                self.emit(
                    detail=detail,
                    stage=0.05,
                    completed=session_done,
                    total=session_total,
                )
                return
            self.emit(detail=detail, stage=0.05)
            return
        if "Installing" in text or "Building" in text or "Successfully installed" in text:
            session_done, session_total = self._session_totals()
            self.emit(
                detail=text,
                stage=0.9,
                completed=session_done if session_total else None,
                total=session_total if session_total else None,
            )


def pip_install(
    python: Path,
    args: list[str],
    tracker: PipProgressTracker,
) -> None:
    check_cancel()
    tracker.emit(stage=0.0)
    cmd = [str(python), "-m", "pip", "install", *args, "--progress-bar", "on"]
    from install_progress import log_command

    log_command(" ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if cancel_requested():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                write_progress(
                    phase="pip",
                    message="Installation cancelled.",
                    cancelled=True,
                    done=True,
                )
                raise InstallCancelled("Installation cancelled.")
            tracker.handle_line(line.rstrip())
        code = proc.wait()
    except InstallCancelled:
        raise
    except KeyboardInterrupt:
        proc.terminate()
        raise InstallCancelled("Installation cancelled.") from None
    if cancel_requested():
        raise InstallCancelled("Installation cancelled.")
    if code != 0:
        append_log(f"  exited {code}")
        raise subprocess.CalledProcessError(code, cmd)
    append_log("  done")
