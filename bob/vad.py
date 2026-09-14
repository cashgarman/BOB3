from __future__ import annotations

from dataclasses import dataclass

import numpy as np


WINDOW = 512


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


@dataclass
class EndpointState:
    in_speech: bool
    heard_speech: bool
    speech_ms: float
    silence_ms: float


class Endpointer:
    """Streaming endpointer over a rolling window of 16 kHz audio."""

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_silence_ms: int = 700,
        min_speech_ms: int = 250,
        window_sec: float = 3.0,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.threshold = float(threshold)
        self.min_silence_ms = int(min_silence_ms)
        self.min_speech_ms = int(min_speech_ms)
        self._window = int(self.sample_rate * window_sec)
        self._eval_hop = int(self.sample_rate * 0.08)
        self.reset()

    def reset(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._samples = 0
        self._heard = False
        self._in_speech = False
        self._speech_samples = 0
        self._silence_samples = 0
        self._last_eval = 0
        self._speech_start = 0

    def configure(self, threshold: float | None = None, min_silence_ms: int | None = None) -> None:
        if threshold is not None:
            self.threshold = float(threshold)
        if min_silence_ms is not None:
            self.min_silence_ms = int(min_silence_ms)

    def feed(self, chunk: np.ndarray) -> EndpointState:
        pcm = np.ascontiguousarray(chunk, dtype=np.float32).reshape(-1)
        if pcm.size == 0:
            return self.state
        self._chunks.append(pcm)
        self._samples += pcm.size
        self._trim()
        if self._samples - self._last_eval < self._eval_hop:
            if self._in_speech:
                self._speech_samples += pcm.size
                self._silence_samples = 0
            elif self._heard:
                self._silence_samples += pcm.size
            return self.state
        self._last_eval = self._samples
        audio = self._concat()
        regions = speech_regions(
            audio,
            sample_rate=self.sample_rate,
            threshold=self.threshold,
            min_silence_ms=min(200, self.min_silence_ms),
            min_speech_ms=self.min_speech_ms,
        )
        near = int(0.2 * self.sample_rate)
        if regions:
            last = regions[-1]
            trailing = audio.size - int(last["end"])
            self._in_speech = trailing < near
            if self._in_speech:
                self._heard = True
                self._speech_samples = int(last["end"]) - int(last["start"])
                self._silence_samples = 0
                offset = self._samples - audio.size
                self._speech_start = offset + int(last["start"])
            else:
                self._silence_samples = max(0, trailing)
                self._speech_samples = 0
                if int(last["end"]) > 0:
                    self._heard = True
        else:
            self._in_speech = False
            self._speech_samples = 0
            if self._heard:
                self._silence_samples = min(self._silence_samples + pcm.size, audio.size)
            else:
                self._silence_samples = audio.size
        return self.state

    @property
    def state(self) -> EndpointState:
        sr = max(1, self.sample_rate)
        return EndpointState(
            in_speech=self._in_speech,
            heard_speech=self._heard,
            speech_ms=1000.0 * self._speech_samples / sr,
            silence_ms=1000.0 * self._silence_samples / sr,
        )

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
        self._last_eval = max(0, self._last_eval - dropped)
