"""Pick an Ollama chat model that fits the user's GPU VRAM."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

STT_RESERVE_MB = 2048
OLLAMA_OVERHEAD_MB = 1536
HEADROOM_MB = 1536
TOTAL_RESERVE_MB = STT_RESERVE_MB + OLLAMA_OVERHEAD_MB + HEADROOM_MB


@dataclass(frozen=True)
class ModelChoice:
    name: str
    min_gpu_mb: int
    vram_needed_mb: int
    summary: str

    def fits(self, total_vram_mb: int | None) -> bool:
        if total_vram_mb is None:
            return self.min_gpu_mb <= 0
        return int(total_vram_mb) >= self.min_gpu_mb


CATALOG: tuple[ModelChoice, ...] = (
    ModelChoice("qwen2.5:1.5b", 0, 4096, "Smallest tool-calling model; 6 GB GPUs and CPU fallback"),
    ModelChoice("qwen2.5:3b", 7168, 5120, "Good quality on 8 GB GPUs"),
    ModelChoice("qwen3:4b", 9216, 6144, "Default recommendation for ~10 GB GPUs"),
    ModelChoice("qwen2.5:7b", 11264, 8192, "Stronger answers on 12 GB GPUs"),
    ModelChoice("qwen3:8b", 15360, 10240, "Largest catalog model; 16 GB+ GPUs"),
)


@dataclass(frozen=True)
class GpuInfo:
    name: str | None
    total_vram_mb: int | None


@dataclass(frozen=True)
class Recommendation:
    recommended: str
    reason: str
    gpu: GpuInfo
    free_for_llm_mb: int | None
    choices: tuple[ModelChoice, ...]

    def choice_fits(self, name: str) -> bool:
        for item in self.choices:
            if item.name == name:
                return item.fits(self.gpu.total_vram_mb)
        return False


def detect_gpu() -> GpuInfo:
    total = _nvml_total_mb()
    name = None
    if total is None:
        name, total = _nvidia_smi_gpu()
    else:
        name, _smi_total = _nvidia_smi_gpu()
        if total is None:
            total = _smi_total
    return GpuInfo(name=name, total_vram_mb=total)


def detect_gpu_vram_mb() -> int | None:
    return detect_gpu().total_vram_mb


def recommend_llm(total_vram_mb: int | None = None, gpu: GpuInfo | None = None) -> Recommendation:
    info = gpu if gpu is not None else (
        GpuInfo(name=None, total_vram_mb=total_vram_mb) if total_vram_mb is not None else detect_gpu()
    )
    vram = info.total_vram_mb
    if vram is None:
        pick = CATALOG[0]
        return Recommendation(
            recommended=pick.name,
            reason="No NVIDIA GPU detected. Using the smallest model; replies will be slow on CPU.",
            gpu=info,
            free_for_llm_mb=None,
            choices=CATALOG,
        )
    free = max(0, int(vram) - TOTAL_RESERVE_MB)
    pick = CATALOG[0]
    for item in CATALOG:
        if item.fits(vram):
            pick = item
    gb = vram / 1024
    gpu_label = info.name or "NVIDIA GPU"
    return Recommendation(
        recommended=pick.name,
        reason=f"{gpu_label} — {gb:.0f} GB VRAM detected. {pick.name} is the best catalog fit after reserving memory for speech models.",
        gpu=info,
        free_for_llm_mb=free,
        choices=CATALOG,
    )


def _nvml_total_mb() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class _NVMLMemory(ctypes.Structure):
            _fields_ = [
                ("total", ctypes.c_ulonglong),
                ("free", ctypes.c_ulonglong),
                ("used", ctypes.c_ulonglong),
            ]

        nvml = ctypes.WinDLL("nvml.dll")
        nvml.nvmlInit_v2.restype = ctypes.c_int
        if nvml.nvmlInit_v2() != 0:
            return None
        handle = ctypes.c_void_p()
        nvml.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
        nvml.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
        if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
            return None
        nvml.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NVMLMemory)]
        nvml.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
        mem = _NVMLMemory()
        if nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) != 0 or not mem.total:
            return None
        return int(mem.total // (1024 * 1024))
    except Exception:
        return None


def _hidden_kwargs() -> dict:
    kwargs: dict = {
        "text": True,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "timeout": 2.0,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return kwargs


def _nvidia_smi_gpu() -> tuple[str | None, int | None]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            **_hidden_kwargs(),
        )
        line = out.strip().splitlines()[0]
        name, _, rest = line.partition(",")
        total = int(float(rest.strip()))
        return name.strip() or None, total
    except Exception:
        return None, None
