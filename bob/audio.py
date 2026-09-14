from __future__ import annotations

import threading
from collections import deque
from typing import Callable

import numpy as np
import sounddevice as sd


WAVE_BARS = 72
PEAKS_PER_CHUNK = 8


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float32)))))


def _chunk_peaks(samples: np.ndarray, bins: int = PEAKS_PER_CHUNK) -> np.ndarray:
    if samples.size == 0:
        return np.zeros(bins, dtype=np.float32)
    step = samples.size // bins
    if step < 1:
        out = np.zeros(bins, dtype=np.float32)
        n = min(bins, samples.size)
        out[-n:] = np.abs(samples[-n:])
        return out
    trimmed = samples[: step * bins].reshape(bins, step)
    return np.max(np.abs(trimmed), axis=1).astype(np.float32)


class AudioHub:
    """16 kHz capture plus on-demand playback. Listening is a toggle buffer."""

    def __init__(
        self,
        sample_rate: int = 16000,
        blocksize: int = 1280,
        input_device: str | int | None = None,
        output_device: str | int | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.input_device = input_device or None
        self.output_device = output_device or None
        self._lock = threading.Lock()
        self._listen_chunks: list[np.ndarray] = []
        self._listening = False
        self._capture_muted = False
        self.level = 0.0
        self._wave_bars = np.zeros(WAVE_BARS, dtype=np.float32)
        self._on_chunk: Callable[[np.ndarray], None] | None = None
        self._stream: sd.InputStream | None = None
        self._play_stream: sd.OutputStream | None = None
        self._play_queue: deque[np.ndarray] = deque()
        self._play_sr = 24000
        self._play_current: np.ndarray | None = None
        self._play_offset = 0
        self._play_done = threading.Event()
        self._play_done.set()
        self._stop_play = threading.Event()

    def start(self, on_chunk: Callable[[np.ndarray], None] | None = None) -> None:
        self._on_chunk = on_chunk
        kwargs = {}
        if self.input_device:
            kwargs["device"] = self.input_device
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.blocksize,
            callback=self._on_input,
            **kwargs,
        )
        self._stream.start()

    def stop(self) -> None:
        self.stop_playback()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._play_stream is not None:
            self._play_stream.stop()
            self._play_stream.close()
            self._play_stream = None

    def _on_input(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        mono = np.ascontiguousarray(indata[:, 0], dtype=np.float32)
        self.level = rms(mono)
        muted = self._capture_muted
        listening = self._listening
        if listening and not muted:
            with self._lock:
                self._listen_chunks.append(mono.copy())
            self._push_wave(mono)
        if self._on_chunk is not None and not muted:
            self._on_chunk(mono)

    def start_listening(self) -> None:
        with self._lock:
            self._listen_chunks.clear()
            self._wave_bars[:] = 0
            self._listening = True

    def stop_listening(self) -> np.ndarray:
        with self._lock:
            self._listening = False
            if not self._listen_chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._listen_chunks)
            self._listen_chunks.clear()
            return audio

    def snapshot_listening(self) -> np.ndarray:
        with self._lock:
            if not self._listen_chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._listen_chunks)

    @property
    def is_listening(self) -> bool:
        return self._listening

    def waveform_bars(self) -> np.ndarray:
        with self._lock:
            return self._wave_bars.copy()

    def _push_wave(self, samples: np.ndarray) -> None:
        peaks = _chunk_peaks(samples)
        n = min(int(peaks.size), WAVE_BARS)
        if n <= 0:
            return
        with self._lock:
            if n < WAVE_BARS:
                self._wave_bars[:-n] = self._wave_bars[n:]
            self._wave_bars[-n:] = peaks[-n:]

    def set_capture_muted(self, muted: bool) -> None:
        self._capture_muted = muted

    def play(self, samples: np.ndarray, sample_rate: int) -> None:
        """Block until playback finishes or stop_playback() is called."""
        self.stop_playback()
        if samples.size == 0:
            return
        audio = np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
        self._stop_play.clear()
        self._play_done.clear()
        self._play_sr = sample_rate
        self._play_queue.clear()
        self._play_queue.append(audio)
        self._play_current = None
        self._play_offset = 0
        self._ensure_play_stream(sample_rate)
        self._play_done.wait()

    def play_async(self, samples: np.ndarray, sample_rate: int) -> None:
        if samples.size == 0:
            return
        audio = np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
        self._stop_play.clear()
        self._play_done.clear()
        self._play_sr = sample_rate
        self._play_queue.append(audio)
        self._ensure_play_stream(sample_rate)

    def wait_playback(self) -> None:
        self._play_done.wait()

    def stop_playback(self) -> None:
        self._stop_play.set()
        self._play_queue.clear()
        self._play_current = None
        self._play_offset = 0
        self._play_done.set()

    @property
    def is_playing(self) -> bool:
        return not self._play_done.is_set()

    def _ensure_play_stream(self, sample_rate: int) -> None:
        if self._play_stream is not None and self._play_sr == sample_rate:
            if not self._play_stream.active:
                self._play_stream.start()
            return
        if self._play_stream is not None:
            self._play_stream.stop()
            self._play_stream.close()
        self._play_sr = sample_rate
        kwargs = {}
        if self.output_device:
            kwargs["device"] = self.output_device
        self._play_stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=2048,
            callback=self._on_output,
            **kwargs,
        )
        self._play_stream.start()

    def _on_output(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        if self._stop_play.is_set():
            outdata.fill(0)
            self._play_done.set()
            return
        needed = frames
        out = np.zeros(frames, dtype=np.float32)
        pos = 0
        while needed > 0:
            if self._play_current is None or self._play_offset >= len(self._play_current):
                if self._play_queue:
                    self._play_current = self._play_queue.popleft()
                    self._play_offset = 0
                else:
                    break
            remain = len(self._play_current) - self._play_offset
            take = min(needed, remain)
            out[pos : pos + take] = self._play_current[self._play_offset : self._play_offset + take]
            self._play_offset += take
            pos += take
            needed -= take
        outdata[:, 0] = out
        if needed < frames:
            self._push_wave(out)
        else:
            with self._lock:
                self._wave_bars *= np.float32(0.72)
        if needed == frames:
            self._play_done.set()


def list_devices(kind: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for dev in sd.query_devices():
        if kind == "input" and int(dev.get("max_input_channels") or 0) < 1:
            continue
        if kind == "output" and int(dev.get("max_output_channels") or 0) < 1:
            continue
        name = str(dev.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names
