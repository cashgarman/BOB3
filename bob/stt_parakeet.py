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
PARAKEET_HF_REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
PARAKEET_REQUIRED_FILES = ("config.json", "vocab.txt")


def parakeet_model_ready(path: Path) -> bool:
    root = Path(path)
    return all((root / name).is_file() for name in PARAKEET_REQUIRED_FILES)


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
        try:
            import onnx_asr
        except ImportError as exc:
            raise RuntimeError(
                "Parakeet STT needs the onnx-asr package. "
                "Install with: pip install onnx-asr"
            ) from exc

        model_dir = self._ensure_model_files()
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
                    str(model_dir),
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

    def _ensure_model_files(self) -> Path:
        """Download Parakeet ONNX weights into models/parakeet if missing.

        onnx-asr treats an existing empty local_dir as offline and will not
        fetch from Hugging Face, so we populate the folder ourselves first.
        """
        self.download_root.mkdir(parents=True, exist_ok=True)
        if parakeet_model_ready(self.download_root):
            return self.download_root
        from huggingface_hub import snapshot_download

        log.info("Downloading Parakeet model from %s …", PARAKEET_HF_REPO)
        snapshot_download(PARAKEET_HF_REPO, local_dir=str(self.download_root))
        return self.download_root

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int,
        initial_prompt: str = "",
        *,
        allow_short_fillers: bool = False,
    ) -> str:
        if self._model is None:
            raise RuntimeError("Parakeet is not loaded")
        if audio.size == 0:
            return ""
        from bob.stt import clean_transcript, prepare_pcm

        pcm, _, _, ok = prepare_pcm(audio)
        if not ok:
            return ""
        try:
            result = self._model.recognize(pcm, sample_rate=int(sample_rate))
        except TypeError:
            result = self._model.recognize(pcm)
        raw = _result_text(result)
        return clean_transcript(raw, allow_short_fillers=allow_short_fillers)


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
