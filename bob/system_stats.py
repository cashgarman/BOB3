from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from dataclasses import dataclass
from ctypes import wintypes


@dataclass(frozen=True)
class UsageStats:
    gpu: float | None = None
    vram: float | None = None
    cpu: float | None = None


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


_SAMPLER: "UsageSampler | None" = None


class UsageSampler:
    """Throttled GPU/VRAM/CPU sampler for lightweight UI meters."""

    def __init__(self, interval_sec: float = 0.5) -> None:
        self.interval_sec = max(0.2, float(interval_sec))
        self._last_at = 0.0
        self._last = UsageStats()
        self._cpu_prev_idle: int | None = None
        self._cpu_prev_total: int | None = None

    def sample(self) -> UsageStats:
        now = time.monotonic()
        if now - self._last_at < self.interval_sec:
            return self._last
        gpu, vram = _nvidia_usage()
        cpu = _cpu_usage(self)
        self._last = UsageStats(gpu=gpu, vram=vram, cpu=cpu)
        self._last_at = now
        return self._last


def sample_usage() -> UsageStats:
    global _SAMPLER
    if _SAMPLER is None:
        _SAMPLER = UsageSampler()
    return _SAMPLER.sample()


def _nvidia_usage() -> tuple[float | None, float | None]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1.0,
        )
        line = out.strip().splitlines()[0]
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            return None, None
        gpu = max(0.0, min(1.0, float(parts[0]) / 100.0))
        used = float(parts[1])
        total = float(parts[2])
        vram = max(0.0, min(1.0, used / total)) if total > 0 else None
        return gpu, vram
    except Exception:
        return None, None


def _filetime_to_int(value: _FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) + int(value.dwLowDateTime)


def _cpu_usage(sampler: UsageSampler) -> float | None:
    if sys.platform != "win32":
        return None
    idle = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    ok = ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle),
        ctypes.byref(kernel),
        ctypes.byref(user),
    )
    if not ok:
        return None
    idle_t = _filetime_to_int(idle)
    total_t = _filetime_to_int(kernel) + _filetime_to_int(user)
    prev_idle = sampler._cpu_prev_idle
    prev_total = sampler._cpu_prev_total
    sampler._cpu_prev_idle = idle_t
    sampler._cpu_prev_total = total_t
    if prev_idle is None or prev_total is None:
        return None
    idle_delta = idle_t - prev_idle
    total_delta = total_t - prev_total
    if total_delta <= 0:
        return None
    busy = max(0.0, min(1.0, 1.0 - (idle_delta / total_delta)))
    return busy
