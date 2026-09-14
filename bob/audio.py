from __future__ import annotations

import threading
from collections import deque
from typing import Callable

import numpy as np
import sounddevice as sd


WAVE_BARS = 72
PEAKS_PER_CHUNK = 8
PLAY_SR = 24000
PLAY_BLOCK = 256


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


def _resample(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or samples.size == 0:
        return np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
    n = max(1, int(round(samples.size * dst_sr / src_sr)))
    x = np.linspace(0.0, 1.0, samples.size, endpoint=False)
    xi = np.linspace(0.0, 1.0, n, endpoint=False)
    return np.interp(xi, x, samples.astype(np.float32)).astype(np.float32)


class AudioHub:
    """16 kHz capture plus an always-open 24 kHz streaming playback sink."""

    def __init__(
        self,
        sample_rate: int = 16000,
        blocksize: int = 512,
        input_device: str | int | None = None,
        output_device: str | int | None = None,
        wasapi_exclusive: bool = False,
    ) -> None:
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.input_device = input_device or None
        self.output_device = output_device or None
        self.wasapi_exclusive = bool(wasapi_exclusive)
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
        self._play_sr = PLAY_SR
        self._play_current: np.ndarray | None = None
        self._play_offset = 0
        self._play_done = threading.Event()
        self._play_done.set()
        self._cancel_play = threading.Event()
        self._epoch = 0
        self._active_epoch = 0
        self._ended = True
        self._on_first_out: Callable[[], None] | None = None
        self._first_out = False

    @property
    def active_epoch(self) -> int:
        return self._active_epoch

    def start(self, on_chunk: Callable[[np.ndarray], None] | None = None) -> None:
        """Open the microphone. A device that no longer exists falls back to the default."""
        self._on_chunk = on_chunk
        try:
            self._stream = self._open_input(self.input_device)
        except Exception:
            if not self.input_device:
                raise
            self.input_device = None
            self._stream = self._open_input(None)
        self._stream.start()
        try:
            self._ensure_play_stream()
        except Exception:
            if self.output_device:
                self.output_device = None
                try:
                    self._ensure_play_stream()
                except Exception:
                    pass

    def _open_input(self, device: str | int | None) -> sd.InputStream:
        kwargs = {}
        if device:
            kwargs["device"] = device
        return sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.blocksize,
            callback=self._on_input,
            **kwargs,
        )

    def stop(self) -> None:
        self.cancel_playback()
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

    def start_listening(self, seed: np.ndarray | None = None) -> None:
        with self._lock:
            self._listen_chunks.clear()
            if seed is not None and seed.size:
                self._listen_chunks.append(np.ascontiguousarray(seed, dtype=np.float32).reshape(-1))
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
            self._write_wave(peaks, n)

    def _write_wave(self, peaks: np.ndarray, n: int) -> None:
        if n < WAVE_BARS:
            self._wave_bars[:-n] = self._wave_bars[n:]
        self._wave_bars[-n:] = peaks[-n:]

    def set_capture_muted(self, muted: bool) -> None:
        self._capture_muted = muted

    def begin_utterance(self, on_first_out: Callable[[], None] | None = None) -> int:
        with self._lock:
            self._epoch += 1
            self._active_epoch = self._epoch
            self._ended = False
            self._play_queue.clear()
            self._play_current = None
            self._play_offset = 0
            self._cancel_play.clear()
            self._play_done.clear()
            self._on_first_out = on_first_out
            self._first_out = False
            epoch = self._active_epoch
        try:
            self._ensure_play_stream()
        except Exception:
            self._play_done.set()
        return epoch

    def enqueue(self, epoch: int, samples: np.ndarray, sample_rate: int | None = None) -> None:
        if samples.size == 0:
            return
        audio = np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
        if sample_rate and sample_rate != self._play_sr:
            audio = _resample(audio, sample_rate, self._play_sr)
        with self._lock:
            if epoch != self._active_epoch or self._cancel_play.is_set() or self._ended:
                return
            self._play_queue.append(audio)

    def end_utterance(self, epoch: int) -> None:
        with self._lock:
            if epoch != self._active_epoch:
                return
            self._ended = True
            if self._queue_drained():
                self._play_done.set()

    def wait_utterance(self, epoch: int) -> None:
        with self._lock:
            if epoch != self._active_epoch:
                return
        self._play_done.wait()

    def cancel_playback(self) -> None:
        with self._lock:
            self._epoch += 1
            self._active_epoch = self._epoch
            self._ended = True
            self._play_queue.clear()
            self._play_current = None
            self._play_offset = 0
            self._cancel_play.set()
            self._play_done.set()
            self._on_first_out = None
            self._first_out = True

    def stop_playback(self) -> None:
        self.cancel_playback()

    def play(self, samples: np.ndarray, sample_rate: int) -> None:
        """Block until playback finishes or cancel_playback() is called."""
        epoch = self.begin_utterance()
        self.enqueue(epoch, samples, sample_rate)
        self.end_utterance(epoch)
        self.wait_utterance(epoch)

    def play_async(self, samples: np.ndarray, sample_rate: int) -> None:
        epoch = self._active_epoch
        if self._play_done.is_set() or epoch == 0:
            epoch = self.begin_utterance()
        self.enqueue(epoch, samples, sample_rate)

    def wait_playback(self) -> None:
        self._play_done.wait()

    @property
    def is_playing(self) -> bool:
        return not self._play_done.is_set()

    def _queue_drained(self) -> bool:
        current_done = self._play_current is None or self._play_offset >= len(self._play_current)
        return current_done and not self._play_queue

    def _ensure_play_stream(self) -> None:
        if self._play_stream is not None:
            if not self._play_stream.active:
                self._play_stream.start()
            return
        kwargs: dict = {}
        if self.output_device:
            kwargs["device"] = self.output_device
        extra = self._wasapi_extra()
        if extra is not None:
            kwargs["extra_settings"] = extra
        try:
            self._play_stream = sd.OutputStream(
                samplerate=self._play_sr,
                channels=1,
                dtype="float32",
                blocksize=PLAY_BLOCK,
                callback=self._on_output,
                **kwargs,
            )
            self._play_stream.start()
        except Exception:
            if extra is None:
                raise
            kwargs.pop("extra_settings", None)
            self.wasapi_exclusive = False
            self._play_stream = sd.OutputStream(
                samplerate=self._play_sr,
                channels=1,
                dtype="float32",
                blocksize=PLAY_BLOCK,
                callback=self._on_output,
                **kwargs,
            )
            self._play_stream.start()

    def _wasapi_extra(self):
        if not self.wasapi_exclusive:
            return None
        extra_cls = getattr(sd, "WasapiSettings", None)
        if extra_cls is None:
            return None
        try:
            return extra_cls(exclusive=True)
        except Exception:
            return None

    def _on_output(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        if self._cancel_play.is_set():
            outdata.fill(0)
            self._play_done.set()
            return
        needed = frames
        out = np.zeros(frames, dtype=np.float32)
        pos = 0
        with self._lock:
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
            ended = self._ended
            drained = self._queue_drained()
        outdata[:, 0] = out
        if needed < frames and not self._first_out:
            self._first_out = True
            cb = self._on_first_out
            self._on_first_out = None
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass
        if needed < frames:
            peaks = _chunk_peaks(out)
            n = min(int(peaks.size), WAVE_BARS)
            if n > 0:
                with self._lock:
                    self._write_wave(peaks, n)
        else:
            with self._lock:
                self._wave_bars *= np.float32(0.72)
        if ended and drained:
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
