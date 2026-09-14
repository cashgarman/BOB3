from __future__ import annotations

from pathlib import Path

import numpy as np

STT_FALLBACKS = ("large-v3-turbo", "distil-large-v3", "medium", "small")


class SpeechToText:
    def __init__(self, model_name: str, compute_type: str, download_root: Path) -> None:
        self.requested_model = model_name
        self.compute_type = compute_type
        self.download_root = download_root
        self.model_name = model_name
        self._model = None
        self.device = "cuda"

    def load(self) -> None:
        from bob.cuda_path import add_cuda_dll_dirs

        add_cuda_dll_dirs()
        from faster_whisper import WhisperModel

        self.download_root.mkdir(parents=True, exist_ok=True)
        chain: list[str] = []
        for name in (self.requested_model, *STT_FALLBACKS):
            if name not in chain:
                chain.append(name)
        last_error: Exception | None = None
        compute_order = [self.compute_type]
        for extra in ("int8_float16", "int8", "float16"):
            if extra not in compute_order:
                compute_order.append(extra)
        for name in chain:
            for ctype in compute_order:
                try:
                    self._model = WhisperModel(
                        name,
                        device="cuda",
                        compute_type=ctype,
                        download_root=str(self.download_root),
                    )
                    self.model_name = name
                    self.device = "cuda"
                    self.compute_type = ctype
                    return
                except Exception as exc:
                    last_error = exc
                    msg = str(exc).lower()
                    # Download / path errors: retry same model with next compute type
                    # only after CUDA OOM should we drop to a smaller model.
                    if "out of memory" in msg or "cuda" in msg and "memory" in msg:
                        break
                    continue
        # Last resort: CPU, never steal the LLM by retrying huge CUDA allocs.
        try:
            self._model = WhisperModel(
                "small",
                device="cpu",
                compute_type="int8",
                download_root=str(self.download_root),
            )
            self.model_name = "small"
            self.device = "cpu"
            self.compute_type = "int8"
        except Exception as exc:
            raise RuntimeError(f"Failed to load Whisper: {last_error or exc}") from exc

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        if self._model is None:
            raise RuntimeError("Whisper is not loaded")
        if audio.size == 0:
            return ""
        pcm = np.ascontiguousarray(audio, dtype=np.float32)
        peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
        if peak > 1.0:
            pcm = pcm / peak
        segments, _info = self._model.transcribe(
            pcm,
            language="en",
            vad_filter=False,
            beam_size=1,
            without_timestamps=True,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
