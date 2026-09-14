from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np

from bob.stt import SpeechToText, clean_transcript, sanitize_prompt
from bob.vad import speech_regions

MAX_PARTIAL_SEC = 15.0


def _join(*parts: str) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def _agree_prefix(prev: list[str], curr: list[str]) -> list[str]:
    stable: list[str] = []
    for a, b in zip(prev, curr):
        if a.lower() == b.lower():
            stable.append(b)
        else:
            break
    return stable


class StreamingTranscriber:
    """Incremental ASR: commit closed VAD regions for Whisper; decode only the tail."""

    def __init__(
        self,
        stt: SpeechToText,
        sample_rate: int = 16000,
        commit_silence_ms: int = 500,
        partial_interval_ms: int = 500,
        vad_threshold: float = 0.5,
        on_partial: Callable[[str], None] | None = None,
    ) -> None:
        self.stt = stt
        self.sample_rate = int(sample_rate)
        self.commit_silence_ms = int(commit_silence_ms)
        self.partial_interval_ms = int(partial_interval_ms)
        self.vad_threshold = float(vad_threshold)
        self.on_partial = on_partial
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._committed = ""
        self._display_tail = ""
        self._prev_partial: list[str] = []
        self._active = False
        self._total_samples = 0
        self._dirty = threading.Event()
        self._stop = threading.Event()
        self._finalize_req = threading.Event()
        self._finalize_done = threading.Event()
        self._finalize_done.set()
        self._final_text = ""
        self._worker: threading.Thread | None = None

    def configure(
        self,
        commit_silence_ms: int | None = None,
        partial_interval_ms: int | None = None,
        vad_threshold: float | None = None,
        sample_rate: int | None = None,
    ) -> None:
        if commit_silence_ms is not None:
            self.commit_silence_ms = int(commit_silence_ms)
        if partial_interval_ms is not None:
            self.partial_interval_ms = int(partial_interval_ms)
        if vad_threshold is not None:
            self.vad_threshold = float(vad_threshold)
        if sample_rate is not None:
            self.sample_rate = int(sample_rate)

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, name="stt-stream", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._dirty.set()
        self._finalize_done.set()

    def start_turn(self, seed: np.ndarray | None = None) -> None:
        with self._lock:
            self._chunks = []
            if seed is not None and seed.size:
                pcm = np.ascontiguousarray(seed, dtype=np.float32).reshape(-1)
                self._chunks.append(pcm)
                self._total_samples = int(pcm.size)
            else:
                self._total_samples = 0
            self._committed = ""
            self._display_tail = ""
            self._prev_partial = []
            self._final_text = ""
            self._active = True
            self._finalize_req.clear()
            self._finalize_done.clear()
        self._dirty.set()

    def push(self, chunk: np.ndarray) -> None:
        if not self._active:
            return
        pcm = np.ascontiguousarray(chunk, dtype=np.float32).reshape(-1)
        if pcm.size == 0:
            return
        with self._lock:
            self._chunks.append(pcm)
            self._total_samples += pcm.size
        self._dirty.set()

    def finalize(self) -> str:
        if not self._active and self._finalize_done.is_set():
            return self._final_text
        self._finalize_req.set()
        self._dirty.set()
        self._finalize_done.wait()
        return self._final_text

    def cancel(self) -> None:
        self._active = False
        self._finalize_req.clear()
        self._finalize_done.set()
        with self._lock:
            self._chunks = []

    @property
    def total_samples(self) -> int:
        return self._total_samples

    @property
    def current_text(self) -> str:
        with self._lock:
            return _join(self._committed, self._display_tail)

    def _loop(self) -> None:
        while not self._stop.is_set():
            timeout = max(0.05, self.partial_interval_ms / 1000.0)
            self._dirty.wait(timeout=timeout)
            self._dirty.clear()
            if self._stop.is_set():
                return
            if not self._active and not self._finalize_req.is_set():
                continue
            try:
                self._tick()
            except Exception:
                if self._finalize_req.is_set():
                    with self._lock:
                        self._final_text = self._committed
                    self._active = False
                    self._finalize_req.clear()
                    self._finalize_done.set()

    def _snapshot(self) -> np.ndarray:
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._chunks)

    def _drop_prefix(self, n: int) -> None:
        if n <= 0:
            return
        with self._lock:
            remain = n
            while self._chunks and remain > 0:
                head = self._chunks[0]
                if head.size <= remain:
                    remain -= head.size
                    self._chunks.pop(0)
                else:
                    self._chunks[0] = head[remain:]
                    remain = 0

    def _decode(self, audio: np.ndarray, prompt: str) -> str:
        min_samples = int(self.sample_rate * 0.2)
        if audio.size < min_samples:
            return ""
        # Skip Whisper on pure silence/noise — it invents "you you you…".
        regions = speech_regions(
            audio,
            sample_rate=self.sample_rate,
            threshold=self.vad_threshold,
            min_silence_ms=self.commit_silence_ms,
        )
        if not regions:
            return ""
        use_prompt = ""
        if getattr(self.stt, "supports_prompt", False):
            use_prompt = sanitize_prompt(prompt)
        text = self.stt.transcribe(audio, self.sample_rate, initial_prompt=use_prompt)
        return clean_transcript(text)

    def _tick(self) -> None:
        buf = self._snapshot()
        with self._lock:
            committed = self._committed
        do_final = self._finalize_req.is_set()
        if buf.size == 0:
            if do_final:
                self._final_text = committed
                self._active = False
                self._finalize_req.clear()
                self._finalize_done.set()
            return

        use_prompt = getattr(self.stt, "supports_prompt", False)
        if use_prompt:
            commit_samples = int(self.sample_rate * self.commit_silence_ms / 1000)
            regions = speech_regions(
                buf,
                sample_rate=self.sample_rate,
                threshold=self.vad_threshold,
                min_silence_ms=self.commit_silence_ms,
            )
            closed_end = 0
            for index, region in enumerate(regions):
                end = int(region["end"])
                last = index == len(regions) - 1
                trailing = buf.size - end
                if trailing >= commit_samples or (do_final and not last):
                    closed_end = end
                else:
                    break

            if closed_end > int(self.sample_rate * 0.25):
                text = self._decode(buf[:closed_end], committed)
                if text:
                    committed = _join(committed, text)
                    with self._lock:
                        self._committed = committed
                        self._display_tail = ""
                    if self.on_partial and committed:
                        self.on_partial(committed)
                self._drop_prefix(closed_end)
                self._prev_partial = []
                buf = buf[closed_end:]

        if do_final:
            tail = self._decode(buf, committed) if buf.size else ""
            self._final_text = clean_transcript(_join(committed, tail))
            self._active = False
            with self._lock:
                self._chunks = []
                self._committed = self._final_text
                self._display_tail = ""
            self._finalize_req.clear()
            self._finalize_done.set()
            return

        min_partial = int(self.sample_rate * 0.4)
        if buf.size < min_partial:
            return
        cap = int(self.sample_rate * MAX_PARTIAL_SEC)
        decode_buf = buf[-cap:] if buf.size > cap else buf
        partial = self._decode(decode_buf, committed)
        words = partial.split() if partial else []
        if use_prompt:
            stable = _agree_prefix(self._prev_partial, words)
            self._prev_partial = words
            tail = " ".join(stable)
        else:
            tail = partial
            self._prev_partial = words
        tail = clean_transcript(tail) if tail else ""
        with self._lock:
            self._display_tail = tail
        display = _join(committed, tail)
        if self.on_partial:
            # Clear live captions when a silence hallucination is filtered out.
            self.on_partial(display)
