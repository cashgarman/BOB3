from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np

from bob.voice_mood import MoodProfile, apply_mood_audio, profile_for, resolve_mood

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
        self.mood = "neutral"
        self.device = "cpu"
        self._kokoro = None

    def load(self, on_status=None) -> None:
        import os

        from bob.cuda_path import add_cuda_dll_dirs, preload_onnxruntime

        add_cuda_dll_dirs()
        preload_onnxruntime()
        onnx = self.models_dir / "kokoro-v1.0.onnx"
        voices = self.models_dir / "voices-v1.0.bin"
        _download(KOKORO_ONNX, onnx, on_status)
        _download(KOKORO_VOICES, voices, on_status)
        last_error: Exception | None = None
        for provider, label in (
            ("CUDAExecutionProvider", "CUDA"),
            ("CPUExecutionProvider", "CPU"),
        ):
            os.environ["ONNX_PROVIDER"] = provider
            try:
                from kokoro_onnx import Kokoro

                if on_status:
                    on_status(f"Loading Kokoro TTS ({label}) ...")
                self._kokoro = Kokoro(str(onnx), str(voices))
                self._kokoro.create("Ready.", voice=self.voice, speed=1.0)
                self.device = "cuda" if "CUDA" in provider else "cpu"
                return
            except Exception as exc:
                last_error = exc
                self._kokoro = None
        raise RuntimeError(f"Failed to load Kokoro: {last_error}") from last_error

    def set_mood(self, mood: str | None) -> str:
        self.mood = resolve_mood(mood)
        return self.mood

    def _mood_kwargs(self, mood: str | None) -> tuple[float, MoodProfile]:
        profile = profile_for(mood if mood is not None else self.mood)
        return clamp_speed(self.speed * profile.speed), profile

    async def synthesize_stream(self, text: str, mood: str | None = None):
        if self._kokoro is None:
            raise RuntimeError("TTS is not loaded")
        text = (text or "").strip()
        if not text:
            return
        speed, profile = self._mood_kwargs(mood)
        async for samples, sr in self._kokoro.create_stream(
            text,
            voice=self.voice,
            speed=speed,
            sentence_pause=profile.sentence_pause,
            clause_pause=profile.clause_pause,
        ):
            self.sample_rate = int(sr)
            yield apply_mood_audio(np.asarray(samples, dtype=np.float32), profile), int(sr)

    def synthesize(self, text: str, mood: str | None = None) -> tuple[np.ndarray, int]:
        if self._kokoro is None:
            raise RuntimeError("TTS is not loaded")
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32), self.sample_rate
        speed, profile = self._mood_kwargs(mood)
        samples, sr = self._kokoro.create(
            text,
            voice=self.voice,
            speed=speed,
            sentence_pause=profile.sentence_pause,
            clause_pause=profile.clause_pause,
        )
        self.sample_rate = int(sr)
        return apply_mood_audio(np.asarray(samples, dtype=np.float32), profile), int(sr)
