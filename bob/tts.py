from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np

KOKORO_ONNX = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"


def _download(url: str, dest: Path, on_status=None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    if on_status:
        on_status(f"Downloading {dest.name} ...")

    last_pct = {"n": -10}

    def _progress(block, block_size, total):
        if on_status and total:
            pct = min(100, int(block * block_size * 100 / total))
            if pct >= last_pct["n"] + 10 or pct == 100:
                last_pct["n"] = pct
                on_status(f"Downloading {dest.name} ({pct}%)")

    urllib.request.urlretrieve(url, tmp, reporthook=_progress)
    tmp.replace(dest)


def clamp_speed(value) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.5, min(2.0, speed))


class TextToSpeech:
    def __init__(self, models_dir: Path, voice: str, speed: float = 1.0) -> None:
        self.models_dir = models_dir
        self.voice = voice
        self.speed = clamp_speed(speed)
        self.sample_rate = 24000
        self._kokoro = None

    def load(self, on_status=None) -> None:
        from kokoro_onnx import Kokoro

        onnx = self.models_dir / "kokoro-v1.0.onnx"
        voices = self.models_dir / "voices-v1.0.bin"
        _download(KOKORO_ONNX, onnx, on_status)
        _download(KOKORO_VOICES, voices, on_status)
        if on_status:
            on_status("Loading Kokoro TTS (CPU) ...")
        self._kokoro = Kokoro(str(onnx), str(voices))
        try:
            self._kokoro.create("Ready.", voice=self.voice, speed=1.0)
        except Exception:
            pass

    async def synthesize_stream(self, text: str):
        if self._kokoro is None:
            raise RuntimeError("TTS is not loaded")
        text = (text or "").strip()
        if not text:
            return
        async for samples, sr in self._kokoro.create_stream(text, voice=self.voice, speed=self.speed):
            self.sample_rate = int(sr)
            yield np.asarray(samples, dtype=np.float32), int(sr)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        if self._kokoro is None:
            raise RuntimeError("TTS is not loaded")
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32), self.sample_rate
        samples, sr = self._kokoro.create(text, voice=self.voice, speed=self.speed)
        self.sample_rate = int(sr)
        return np.asarray(samples, dtype=np.float32), int(sr)
