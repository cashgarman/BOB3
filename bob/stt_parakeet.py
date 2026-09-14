from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

PARAKEET_ALIASES = {
    "parakeet",
    "parakeet-tdt",
    "parakeet-tdt-0.6b-v3",
    "nemo-parakeet-tdt-0.6b-v3",
}
PARAKEET_MODEL = "nemo-parakeet-tdt-0.6b-v3"


def is_parakeet(name: str) -> bool:
    key = (name or "").strip().lower()
    return key in PARAKEET_ALIASES or key.startswith("parakeet") or "parakeet-tdt" in key


class ParakeetSTT:
    """NVIDIA Parakeet TDT 0.6B v3 via onnx-asr (CUDA). Fast single-pass ASR."""

    supports_prompt = False

    def __init__(self, model_name: str, download_root: Path) -> None:
        self.requested_model = model_name
        self.model_name = PARAKEET_MODEL
        self.download_root = Path(download_root)
        self.compute_type = "fp16"
        self.device = "cuda"
        self._model = None

    def load(self) -> None:
        from bob.cuda_path import add_cuda_dll_dirs, preload_onnxruntime

        add_cuda_dll_dirs()
        preload_onnxruntime()
        import onnx_asr

        self.download_root.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for providers, device, q in (
            (["CUDAExecutionProvider", "CPUExecutionProvider"], "cuda", None),
            (["CUDAExecutionProvider", "CPUExecutionProvider"], "cuda", "int8"),
            (["CPUExecutionProvider"], "cpu", "int8"),
        ):
            try:
                kwargs: dict = {"providers": providers}
                if q:
                    kwargs["quantization"] = q
                self._model = onnx_asr.load_model(
                    PARAKEET_MODEL,
                    str(self.download_root),
                    **kwargs,
                )
                self.device = device
                self.compute_type = q or "fp16"
                self.model_name = PARAKEET_MODEL
                # Warm the CUDA graph / ORT session.
                self.transcribe(np.zeros(16000, dtype=np.float32), 16000)
                log.info("Parakeet %s on %s (%s)", self.model_name, self.device, self.compute_type)
                return
            except Exception as exc:
                last_error = exc
                log.warning("Parakeet load %s/%s failed: %s", device, q or "fp16", exc)
                self._model = None
        raise RuntimeError(f"Failed to load Parakeet: {last_error}") from last_error

    def transcribe(self, audio: np.ndarray, sample_rate: int, initial_prompt: str = "") -> str:
        if self._model is None:
            raise RuntimeError("Parakeet is not loaded")
        if audio.size == 0:
            return ""
        pcm = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
        peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
        if peak > 1.0:
            pcm = pcm / peak
        try:
            result = self._model.recognize(pcm, sample_rate=int(sample_rate))
        except TypeError:
            result = self._model.recognize(pcm)
        from bob.stt import clean_transcript

        return clean_transcript(_result_text(result))


def _result_text(result) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, (list, tuple)):
        parts = [_result_text(item) for item in result]
        return " ".join(p for p in parts if p).strip()
    text = getattr(result, "text", None)
    if text:
        return str(text).strip()
    return str(result).strip()
