from __future__ import annotations

import asyncio
import queue
import threading

import numpy as np

from bob.audio import AudioHub
from bob.tts import TextToSpeech
from bob.voice_mood import resolve_mood

_END = object()


class SpeechStreamer:
    """Synthesize text chunks on a worker thread and enqueue PCM without blocking playback."""

    def __init__(self, tts: TextToSpeech, audio: AudioHub) -> None:
        self.tts = tts
        self.audio = audio
        self.mood = "neutral"
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._epoch = 0
        self._thread: threading.Thread | None = None
        self._on_first_pcm = None
        self._pcm_marked = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tts-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.cancel()

    def begin(self, on_first_pcm=None, on_first_out=None) -> int:
        self._drain()
        self._on_first_pcm = on_first_pcm
        self._pcm_marked = False
        self._epoch = self.audio.begin_utterance(on_first_out=on_first_out)
        return self._epoch

    def set_mood(self, mood: str | None) -> str:
        """Delivery style for chunks that have not been synthesized yet."""
        self.mood = resolve_mood(mood)
        self.tts.set_mood(self.mood)
        return self.mood

    def feed(self, text: str) -> None:
        piece = (text or "").strip()
        if not piece or self._epoch <= 0:
            return
        self._q.put((self._epoch, piece))

    def finish(self) -> None:
        if self._epoch <= 0:
            return
        self._q.put((self._epoch, _END))

    def cancel(self) -> None:
        self._drain()
        self._epoch = 0
        self.audio.cancel_playback()

    def wait(self, epoch: int) -> None:
        self.audio.wait_utterance(epoch)

    def _drain(self) -> None:
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while not self._stop.is_set():
                try:
                    epoch, item = self._q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is _END:
                    self.audio.end_utterance(epoch)
                    continue
                if epoch != self.audio.active_epoch:
                    continue
                try:
                    loop.run_until_complete(self._synth(epoch, str(item)))
                except Exception:
                    try:
                        samples, sr = self.tts.synthesize(str(item), mood=self.mood)
                    except Exception:
                        continue
                    if epoch == self.audio.active_epoch:
                        self._mark_pcm()
                        self.audio.enqueue(epoch, samples, sr)
        finally:
            loop.close()

    async def _synth(self, epoch: int, text: str) -> None:
        agen = self.tts.synthesize_stream(text, mood=self.mood)
        try:
            async for samples, sr in agen:
                if epoch != self.audio.active_epoch:
                    return
                self._mark_pcm()
                self.audio.enqueue(epoch, np.asarray(samples, dtype=np.float32), sr)
        finally:
            aclose = getattr(agen, "aclose", None)
            if aclose is not None:
                await aclose()

    def _mark_pcm(self) -> None:
        if self._pcm_marked:
            return
        self._pcm_marked = True
        cb = self._on_first_pcm
        self._on_first_pcm = None
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

