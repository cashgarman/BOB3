from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import numpy as np

STT_FALLBACKS = ("large-v3-turbo", "distil-large-v3", "medium", "small")

# Near-silence: quieter than this and Whisper invents "you you you…".
_MIN_RMS = 0.006
_MIN_PEAK = 0.02


def create_speech_to_text(model_name: str, compute_type: str, models_dir: Path):
    """Parakeet by default; Whisper when the configured name is a Whisper size."""
    from bob.stt_parakeet import ParakeetSTT, is_parakeet

    if is_parakeet(model_name):
        return ParakeetSTT(model_name, models_dir / "parakeet")
    return SpeechToText(model_name, compute_type, models_dir / "whisper")


class SpeechToText:
    supports_prompt = True

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
        pcm = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
        peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
        if peak > 1.0:
            pcm = pcm / peak
            peak = 1.0
        rms = float(np.sqrt(np.mean(np.square(pcm)))) if pcm.size else 0.0
        if rms < _MIN_RMS and peak < _MIN_PEAK:
            return ""
        kwargs: dict = {}
        prompt = sanitize_prompt(initial_prompt)
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
            compression_ratio_threshold=2.2,
            log_prob_threshold=-0.8,
            **kwargs,
        )
        texts = []
        for seg in segments:
            text = (seg.text or "").strip()
            if not text or _is_hallucination(seg, text):
                continue
            cleaned = clean_transcript(text)
            if cleaned:
                texts.append(cleaned)
        return clean_transcript(" ".join(texts))


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        return True  # unknown: let the CUDA attempts decide


# Whisper's stock fillers for silence / noise.
_FILLERS = {
    "thank you",
    "thank you.",
    "thanks for watching",
    "thanks for watching.",
    "thank you for watching",
    "thank you for watching.",
    "thanks for watching!",
    "you",
    "you.",
    "bye",
    "bye.",
    "okay",
    "ok",
    "subtitles by the amara.org community",
}

_FILLER_WORDS = frozenset(
    {
        "you",
        "thank",
        "thanks",
        "bye",
        "okay",
        "ok",
        "watching",
        "for",
        "the",
        "a",
        "to",
        "and",
        "uh",
        "um",
        "yeah",
        "yes",
        "hmm",
        "subtitle",
        "subtitles",
        "amara",
        "org",
        "community",
        "by",
    }
)

_WORD_RE = re.compile(r"[a-z0-9']+")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def _has_phrase_loop(words: list[str], min_repeats: int = 4) -> bool:
    """True when a 1–4 word phrase repeats back-to-back many times."""
    n = len(words)
    if n < min_repeats:
        return False
    for phrase_len in (1, 2, 3, 4):
        need = phrase_len * min_repeats
        if n < need:
            continue
        for start in range(0, n - need + 1):
            phrase = words[start : start + phrase_len]
            if not phrase:
                continue
            ok = True
            for rep in range(1, min_repeats):
                i = start + rep * phrase_len
                if words[i : i + phrase_len] != phrase:
                    ok = False
                    break
            if ok:
                return True
    return False


def is_bad_transcript(text: str) -> bool:
    """Detect Whisper silence hallucinations and token-loop garbage.

    Single stock phrases like "Thank you." are *not* rejected here — those need
    segment no_speech scores (see _is_hallucination). Loops always are.
    """
    raw = (text or "").strip()
    if not raw:
        return True
    words = _words(raw)
    if not words:
        return True
    if _has_phrase_loop(words, min_repeats=4):
        return True
    if len(words) >= 8:
        top, count = Counter(words).most_common(1)[0]
        if count >= 6 and count / len(words) >= 0.55:
            return True
        unique = set(words)
        if len(unique) <= 3 and all(w in _FILLER_WORDS for w in unique):
            return True
    # "Thank you. Thank you. Thank you."
    sentences = [s.strip() for s in re.split(r"[.!?]+", raw) if s.strip()]
    if len(sentences) >= 3:
        norms = [_words(s) for s in sentences]
        if norms and all(n == norms[0] and n for n in norms):
            phrase = " ".join(norms[0])
            if phrase in {f.rstrip(".!?") for f in _FILLERS} or all(
                w in _FILLER_WORDS for w in norms[0]
            ):
                return True
    return False


def clean_transcript(text: str) -> str:
    """Drop known garbage; otherwise return stripped text."""
    raw = (text or "").strip()
    if not raw or is_bad_transcript(raw):
        return ""
    return raw


def sanitize_prompt(prompt: str) -> str:
    """Never feed a hallucination loop back into Whisper as context."""
    raw = (prompt or "").strip()
    if not raw or is_bad_transcript(raw):
        return ""
    words = _words(raw)
    if _has_phrase_loop(words, min_repeats=3):
        return ""
    return raw


def _is_hallucination(seg, text: str) -> bool:
    no_speech = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
    logprob = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
    compression = float(getattr(seg, "compression_ratio", 0.0) or 0.0)
    if compression > 2.4:
        return True
    if no_speech > 0.85 and logprob < -0.5:
        return True
    if is_bad_transcript(text):
        return True
    lowered = text.lower().strip()
    bare = lowered.rstrip(".!?,;:")
    if bare in _FILLERS or lowered in _FILLERS:
        # Stock silence fillers only when Whisper doubts there was speech.
        return no_speech > 0.45
    return False
