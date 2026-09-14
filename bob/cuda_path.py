from __future__ import annotations

import os
import sys
from pathlib import Path

# Python 3.8+ removes PATH from the Windows DLL search. add_dll_directory
# only stays in effect while these cookie objects remain alive.
_DLL_DIR_HANDLES: list[object] = []
_PRELOADED: list[str] = []

_PRELOAD_ORDER = (
    "cudart64_12.dll",
    "nvJitLink_120_0.dll",
    "nvrtc64_120_0.dll",
    "cublasLt64_12.dll",
    "cublas64_12.dll",
    "cufft64_11.dll",
    "cudnn64_9.dll",
)


def add_cuda_dll_dirs() -> list[str]:
    """Put pip-installed NVIDIA CUDA 12 DLLs on the Windows loader path."""
    added: list[str] = []
    site = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not site.is_dir():
        return added
    bins = sorted(p for p in site.glob("*/bin") if p.is_dir())
    for folder in bins:
        path = str(folder)
        if hasattr(os, "add_dll_directory"):
            try:
                _DLL_DIR_HANDLES.append(os.add_dll_directory(path))
            except OSError:
                pass
        if path not in os.environ.get("PATH", ""):
            os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
        added.append(path)
    _preload_cuda_dlls(bins)
    return added


def _preload_cuda_dlls(bins: list[Path]) -> None:
    import ctypes

    found: dict[str, Path] = {}
    for folder in bins:
        for dll in folder.glob("*.dll"):
            found[dll.name.lower()] = dll
    for name in _PRELOAD_ORDER:
        path = found.get(name.lower())
        if path is None or name in _PRELOADED:
            continue
        try:
            ctypes.WinDLL(str(path))
            _PRELOADED.append(name)
        except OSError:
            continue


def preload_onnxruntime() -> None:
    """Load CUDA/cuDNN into onnxruntime-gpu after the pip NVIDIA wheels are on PATH."""
    add_cuda_dll_dirs()
    try:
        import onnxruntime as ort
    except Exception:
        return
    preload = getattr(ort, "preload_dlls", None)
    if callable(preload):
        try:
            preload()
        except Exception:
            pass
