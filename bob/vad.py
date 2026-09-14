from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WINDOW = 512
CONTEXT = 64


def speech_regions(
    audio: np.ndarray,
    sample_rate: int = 16000,
    threshold: float = 0.5,
    min_silence_ms: int = 500,
    speech_pad_ms: int = 120,
    min_speech_ms: int = 150,
) -> list[dict]:
    """Return Silero speech segments as dicts with start/end sample indices."""
    if audio is None or audio.size < WINDOW:
        return []
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    pcm = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
    opts = VadOptions(
        threshold=float(threshold),
        min_silence_duration_ms=int(min_silence_ms),
        speech_pad_ms=int(speech_pad_ms),
        min_speech_duration_ms=int(min_speech_ms),
    )
    try:
        return list(get_speech_timestamps(pcm, vad_options=opts, sampling_rate=sample_rate))
    except Exception:
        return []


class StreamingSilero:
    """Incremental Silero VAD: one ONNX forward per 512-sample window, state kept."""

    def __init__(self) -> None:
        self._session = None
        self.reset()

    def _ensure(self) -> None:
        if self._session is not None:
            return
        from faster_whisper.vad import get_vad_model

        self._session = get_vad_model().session

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT), dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)

    def feed(self, audio: np.ndarray) -> list[float]:
        pcm = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
        if pcm.size == 0:
            return []
        self._ensure()
        if self._pending.size:
            pcm = np.concatenate([self._pending, pcm])
        n = (pcm.size // WINDOW) * WINDOW
        self._pending = pcm[n:]
        if n == 0:
            return []
        probs: list[float] = []
        for start in range(0, n, WINDOW):
            window = pcm[start : start + WINDOW]
            inp = np.concatenate([self._context.reshape(-1), window])[None, :]
            output, self._h, self._c = self._session.run(
                None,
                {"input": inp.astype(np.float32), "h": self._h, "c": self._c},
            )
            self._context = window[None, -CONTEXT:]
            probs.append(float(np.asarray(output).reshape(-1)[-1]))
        return probs


@dataclass
class EndpointState:
    in_speech: bool
    heard_speech: bool
    speech_ms: float
    silence_ms: float
    turn_speech_ms: float = 0.0


class Endpointer:
    """Streaming endpointer: Silero probability per 32 ms window, no rolling re-decode."""

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_silence_ms: int = 700,
        min_speech_ms: int = 250,
        window_sec: float = 8.0,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.threshold = float(threshold)
        self.min_silence_ms = int(min_silence_ms)
        self.min_speech_ms = int(min_speech_ms)
        self._window = int(self.sample_rate * window_sec)
        self._vad = StreamingSilero()
        self.reset()

    def reset(self) -> None:
        self._vad.reset()
        self._chunks: list[np.ndarray] = []
        self._samples = 0
        self._heard = False
        self._in_speech = False
        self._speech_samples = 0
        self._silence_samples = 0
        self._speech_start = 0
        self._neg = max(self.threshold - 0.15, 0.01)
        self._turn_speech_samples = 0

    def configure(self, threshold: float | None = None, min_silence_ms: int | None = None) -> None:
        if threshold is not None:
            self.threshold = float(threshold)
            self._neg = max(self.threshold - 0.15, 0.01)
        if min_silence_ms is not None:
            self.min_silence_ms = int(min_silence_ms)

    def feed(self, chunk: np.ndarray) -> EndpointState:
        pcm = np.ascontiguousarray(chunk, dtype=np.float32).reshape(-1)
        if pcm.size == 0:
            return self.state
        self._chunks.append(pcm)
        self._samples += pcm.size
        self._trim()
        probs = self._vad.feed(pcm)
        if not probs:
            if self._in_speech:
                self._speech_samples += pcm.size
                self._turn_speech_samples += pcm.size
                self._silence_samples = 0
            elif self._heard:
                self._silence_samples += pcm.size
            return self.state
        for prob in probs:
            if self._in_speech:
                if prob < self._neg:
                    self._in_speech = False
                    self._silence_samples = WINDOW
                    self._speech_samples = 0
                else:
                    self._speech_samples += WINDOW
                    self._turn_speech_samples += WINDOW
                    self._silence_samples = 0
                    self._heard = True
            else:
                if prob >= self.threshold:
                    self._in_speech = True
                    self._heard = True
                    self._speech_samples = WINDOW
                    self._turn_speech_samples += WINDOW
                    self._silence_samples = 0
                    self._speech_start = max(0, self._samples - WINDOW)
                elif self._heard:
                    self._silence_samples += WINDOW
        return self.state

    @property
    def state(self) -> EndpointState:
        sr = max(1, self.sample_rate)
        return EndpointState(
            in_speech=self._in_speech,
            heard_speech=self._heard,
            speech_ms=1000.0 * self._speech_samples / sr,
            silence_ms=1000.0 * self._silence_samples / sr,
            turn_speech_ms=1000.0 * self._turn_speech_samples / sr,
        )

    def recent_audio(self, seconds: float = 8.0) -> np.ndarray:
        audio = self._concat()
        if audio.size == 0:
            return np.zeros(0, dtype=np.float32)
        keep = int(max(0.0, seconds) * self.sample_rate)
        if keep and audio.size > keep:
            return audio[-keep:]
        return audio

    def take_speech_seed(self) -> np.ndarray:
        """Audio from the current/last speech onset, padded slightly at the front."""
        audio = self._concat()
        if audio.size == 0:
            return np.zeros(0, dtype=np.float32)
        pad = int(0.15 * self.sample_rate)
        offset = self._samples - audio.size
        start = max(0, self._speech_start - offset - pad)
        if start >= audio.size:
            start = max(0, audio.size - int(1.5 * self.sample_rate))
        return audio[start:]

    def _concat(self) -> np.ndarray:
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._chunks)

    def _trim(self) -> None:
        cap = max(self._window, int(self.sample_rate * 8))
        extra = self._samples - cap
        if extra <= 0:
            return
        dropped = 0
        while self._chunks and dropped < extra:
            head = self._chunks[0]
            if dropped + head.size <= extra:
                dropped += head.size
                self._chunks.pop(0)
            else:
                keep = head.size - (extra - dropped)
                self._chunks[0] = head[-keep:]
                dropped = extra
                break
        self._samples -= dropped
        self._speech_start = max(0, self._speech_start - dropped)
