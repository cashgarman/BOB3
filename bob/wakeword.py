from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np


class WakeWordDetector:
    def __init__(
        self,
        model_name: str,
        threshold: float,
        sample_rate: int,
        models_dir: Path,
        on_detect: Callable[[], None],
    ) -> None:
        self.model_name = model_name
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.models_dir = Path(models_dir)
        self.on_detect = on_detect
        self.enabled = True
        self._model = None
        self._buf: deque[np.ndarray] = deque()
        self._pending = 0
        self._frame = 1280
        self._cooldown_until = 0.0
        self.error: str | None = None

    def load(self) -> None:
        try:
            from openwakeword.model import Model
            from openwakeword.utils import download_models
        except Exception as exc:  # pragma: no cover
            self.error = f"openWakeWord import failed: {exc}"
            return
        try:
            self.models_dir.mkdir(parents=True, exist_ok=True)
            download_models(model_names=[self.model_name], target_directory=str(self.models_dir))
        except Exception as exc:
            self.error = f"Wake-word model download failed: {exc}"
            return
        onnx = self._resolve_onnx()
        if onnx is None:
            self.error = f"No ONNX file for {self.model_name} in {self.models_dir}"
            return
        try:
            self._model = Model(
                wakeword_models=[str(onnx)],
                inference_framework="onnx",
                melspec_model_path=str(self.models_dir / "melspectrogram.onnx"),
                embedding_model_path=str(self.models_dir / "embedding_model.onnx"),
            )
        except Exception as exc:
            self.error = f"Wake-word load failed: {exc}"

    def set_model(self, model_name: str) -> None:
        """Switch wake word at runtime. Detection pauses until the new model is up."""
        name = (model_name or "").strip()
        if not name or name == self.model_name and self._model is not None:
            return
        self.model_name = name
        self._model = None
        self.error = None
        self.reset()
        self.load()

    def _resolve_onnx(self) -> Path | None:
        needle = self.model_name.replace(" ", "_")
        matches = sorted(self.models_dir.glob(f"*{needle}*.onnx"))
        if matches:
            return matches[0]
        any_onnx = sorted(p for p in self.models_dir.glob("*.onnx") if "mel" not in p.name and "embed" not in p.name and "vad" not in p.name)
        return any_onnx[0] if any_onnx else None

    def reset(self) -> None:
        self._buf.clear()
        self._pending = 0
        if self._model is not None:
            try:
                self._model.reset()
            except Exception:
                pass

    def feed(self, float_chunk: np.ndarray) -> None:
        if not self.enabled or self._model is None:
            return
        if time.monotonic() < self._cooldown_until:
            return
        pcm = np.clip(float_chunk, -1.0, 1.0)
        pcm_i16 = (pcm * 32767.0).astype(np.int16)
        self._buf.append(pcm_i16)
        self._pending += len(pcm_i16)
        while self._pending >= self._frame:
            frame = self._pop_frame()
            try:
                scores = self._model.predict(frame)
            except Exception:
                return
            score = 0.0
            if isinstance(scores, dict) and scores:
                score = max(float(v) for v in scores.values())
            if score >= self.threshold:
                self._cooldown_until = time.monotonic() + 2.0
                self.reset()
                self.on_detect()
                return

    def _pop_frame(self) -> np.ndarray:
        need = self._frame
        parts: list[np.ndarray] = []
        while need > 0 and self._buf:
            chunk = self._buf[0]
            if len(chunk) <= need:
                parts.append(chunk)
                self._buf.popleft()
                need -= len(chunk)
            else:
                parts.append(chunk[:need])
                self._buf[0] = chunk[need:]
                need = 0
        self._pending = sum(len(x) for x in self._buf)
        return np.concatenate(parts) if parts else np.zeros(self._frame, dtype=np.int16)
