from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from ctypes import wintypes

from bob.debug_log import dbg


@dataclass(frozen=True)
class UsageStats:
    gpu: float | None = None
    vram: float | None = None
    cpu: float | None = None


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _NVMLUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _NVMLMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


_SAMPLER: "UsageSampler | None" = None
_SAMPLER_THREAD: threading.Thread | None = None
_SAMPLER_STOP = threading.Event()
_SAMPLER_LOCK = threading.Lock()
_CACHED = UsageStats()
_NVML = None
_NVML_DEVICE = None
_NVML_FAILED = False
_SAMPLE_LOGS = 0


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
        gpu, vram, source = _nvidia_usage()
        cpu = _cpu_usage(self)
        self._last = UsageStats(gpu=gpu, vram=vram, cpu=cpu)
        self._last_at = now
        # #region agent log
        global _SAMPLE_LOGS
        if _SAMPLE_LOGS < 8:
            _SAMPLE_LOGS += 1
            dbg(
                "system_stats.py:sample",
                "usage sample",
                data={"source": source, "gpu": gpu, "vram": vram, "cpu": cpu, "n": _SAMPLE_LOGS},
                hypothesis_id="S1",
                run_id="tray-v8",
            )
        # #endregion
        return self._last


def sample_usage() -> UsageStats:
    global _SAMPLER, _SAMPLER_THREAD
    if _SAMPLER is None:
        _SAMPLER = UsageSampler()
    if _SAMPLER_THREAD is None or not _SAMPLER_THREAD.is_alive():
        _SAMPLER_STOP.clear()
        _SAMPLER_THREAD = threading.Thread(
            target=_sampler_loop,
            name="system-stats",
            daemon=True,
        )
        _SAMPLER_THREAD.start()
    with _SAMPLER_LOCK:
        return _CACHED


def _sampler_loop() -> None:
    global _CACHED
    sampler = _SAMPLER
    if sampler is None:
        return
    while not _SAMPLER_STOP.is_set():
        stats = sampler.sample()
        with _SAMPLER_LOCK:
            _CACHED = stats
        _SAMPLER_STOP.wait(sampler.interval_sec)


def _nvidia_usage() -> tuple[float | None, float | None, str]:
    gpu, vram = _nvml_usage()
    if gpu is not None or vram is not None:
        return gpu, vram, "nvml"
    gpu, vram = _nvidia_smi_usage()
    return gpu, vram, "nvidia-smi" if gpu is not None or vram is not None else "none"


def _nvml_usage() -> tuple[float | None, float | None]:
    global _NVML, _NVML_DEVICE, _NVML_FAILED
    if sys.platform != "win32" or _NVML_FAILED:
        return None, None
    try:
        if _NVML is None:
            nvml = ctypes.WinDLL("nvml.dll")
            nvml.nvmlInit_v2.restype = ctypes.c_int
            if nvml.nvmlInit_v2() != 0:
                _NVML_FAILED = True
                return None, None
            handle = ctypes.c_void_p()
            nvml.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
            nvml.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
            if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
                _NVML_FAILED = True
                return None, None
            nvml.nvmlDeviceGetUtilizationRates.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NVMLUtilization)]
            nvml.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int
            nvml.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NVMLMemory)]
            nvml.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
            _NVML = nvml
            _NVML_DEVICE = handle
        util = _NVMLUtilization()
        mem = _NVMLMemory()
        gpu_ok = _NVML.nvmlDeviceGetUtilizationRates(_NVML_DEVICE, ctypes.byref(util)) == 0
        mem_ok = _NVML.nvmlDeviceGetMemoryInfo(_NVML_DEVICE, ctypes.byref(mem)) == 0
        gpu = max(0.0, min(1.0, util.gpu / 100.0)) if gpu_ok else None
        vram = None
        if mem_ok and mem.total:
            vram = max(0.0, min(1.0, mem.used / mem.total))
        return gpu, vram
    except Exception:
        _NVML_FAILED = True
        return None, None


def _hidden_subprocess_kwargs() -> dict:
    kwargs: dict = {
        "text": True,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "timeout": 1.0,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _nvidia_smi_usage() -> tuple[float | None, float | None]:
    try:
        kwargs = _hidden_subprocess_kwargs()
        # #region agent log
        global _SAMPLE_LOGS
        if _SAMPLE_LOGS < 8:
            dbg(
                "system_stats.py:_nvidia_smi_usage",
                "spawning nvidia-smi",
                data={
                    "creationflags": kwargs.get("creationflags"),
                    "has_startupinfo": "startupinfo" in kwargs,
                },
                hypothesis_id="S1",
                run_id="tray-v8",
            )
        # #endregion
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            **kwargs,
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
