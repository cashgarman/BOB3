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
        if not _cuda_available():
            # Without CUDA every attempt below would download a model and then
            # fail the same way; go straight to the CPU fallback.
            last_error = RuntimeError("no CUDA device visible to CTranslate2")
            chain = []
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

    def transcribe(self, audio: np.ndarray, sample_rate: int, initial_prompt: str = "") -> str:
        if self._model is None:
            raise RuntimeError("Whisper is not loaded")
        if audio.size == 0:
            return ""
        pcm = np.ascontiguousarray(audio, dtype=np.float32)
        peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
        if peak > 1.0:
            pcm = pcm / peak
        kwargs: dict = {}
        prompt = (initial_prompt or "").strip()
        if prompt:
            kwargs["initial_prompt"] = prompt[-800:]
        segments, _info = self._model.transcribe(
            pcm,
            language="en",
            vad_filter=False,
            beam_size=1,
            without_timestamps=True,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            **kwargs,
        )
        texts = []
        for seg in segments:
            text = seg.text.strip()
            if not text or _is_hallucination(seg, text):
                continue
            texts.append(text)
        return " ".join(texts).strip()


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        return True  # unknown: let the CUDA attempts decide


# Whisper's stock fillers for silence / noise. Only dropped when the model
# itself was unsure there was speech, so a real "Thank you." still gets through.
_FILLERS = {
    "thank you.",
    "thanks for watching.",
    "thank you for watching.",
    "thanks for watching!",
    "you",
    "you.",
    "bye.",
    "subtitles by the amara.org community",
}


def _is_hallucination(seg, text: str) -> bool:
    no_speech = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
    logprob = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
    if no_speech > 0.85 and logprob < -0.8:
        return True
    return no_speech > 0.5 and text.lower() in _FILLERS
