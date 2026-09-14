from __future__ import annotations

import asyncio
import queue
import threading

import numpy as np

from bob.audio import AudioHub
from bob.tts import TextToSpeech

_END = object()


class SpeechStreamer:
    """Synthesize text chunks on a worker thread and enqueue PCM without blocking playback."""

    def __init__(self, tts: TextToSpeech, audio: AudioHub) -> None:
        self.tts = tts
        self.audio = audio
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._epoch = 0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tts-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.cancel()

    def begin(self) -> int:
        self._drain()
        self._epoch = self.audio.begin_utterance()
        return self._epoch

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
                        samples, sr = self.tts.synthesize(str(item))
                    except Exception:
                        continue
                    if epoch == self.audio.active_epoch:
                        self.audio.enqueue(epoch, samples, sr)
        finally:
            loop.close()

    async def _synth(self, epoch: int, text: str) -> None:
        agen = self.tts.synthesize_stream(text)
        try:
            async for samples, sr in agen:
                if epoch != self.audio.active_epoch:
                    return
                self.audio.enqueue(epoch, np.asarray(samples, dtype=np.float32), sr)
        finally:
            aclose = getattr(agen, "aclose", None)
            if aclose is not None:
                await aclose()
