from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bob.vad import EndpointState
from bob.whisper_mel import compute_whisper_log_mel_features

log = logging.getLogger(__name__)

HF_REPO = "pipecat-ai/smart-turn-v3"
ONNX_NAME = "smart-turn-v3.2-cpu.onnx"
SAMPLE_RATE = 16000
WINDOW_SEC = 8
COMPLETE_THRESHOLD = 0.5


@dataclass
class TurnVerdict:
    complete: bool
    probability: float


class SmartTurn:
    """Pipecat Smart Turn v3.2: semantic end-of-turn on CPU (~12-30 ms)."""

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = Path(models_dir)
        self._session = None
        self.error: str | None = None

    def load(self) -> None:
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
        except Exception as exc:
            self.error = f"Smart Turn import failed: {exc}"
            return
        try:
            self.models_dir.mkdir(parents=True, exist_ok=True)
            path = hf_hub_download(
                HF_REPO,
                ONNX_NAME,
                local_dir=str(self.models_dir),
                local_dir_use_symlinks=False,
            )
        except Exception as exc:
            self.error = f"Smart Turn download failed: {exc}"
            log.warning("%s", self.error)
            return
        try:
            so = ort.SessionOptions()
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            so.inter_op_num_threads = 1
            so.intra_op_num_threads = 1
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(
                path,
                sess_options=so,
                providers=["CPUExecutionProvider"],
            )
            dummy = np.zeros(SAMPLE_RATE, dtype=np.float32)
            self.predict(dummy)
            self.error = None
            log.info("Smart Turn ready (%s)", ONNX_NAME)
        except Exception as exc:
            self._session = None
            self.error = f"Smart Turn load failed: {exc}"
            log.warning("%s", self.error)

    def predict(self, audio: np.ndarray) -> TurnVerdict:
        if self._session is None:
            return TurnVerdict(complete=True, probability=1.0)
        pcm = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
        max_samples = SAMPLE_RATE * WINDOW_SEC
        if pcm.size > max_samples:
            pcm = pcm[-max_samples:]
        elif pcm.size < max_samples:
            pcm = np.pad(pcm, (max_samples - pcm.size, 0))
        log_mel = compute_whisper_log_mel_features(pcm, do_normalize=True)
        features = np.expand_dims(log_mel, axis=0)
        outputs = self._session.run(None, {"input_features": features})
        probability = float(outputs[0][0].item())
        return TurnVerdict(complete=probability > COMPLETE_THRESHOLD, probability=probability)


class TurnGate:
    """Endpoint after min silence when Smart Turn says complete, else wait until max."""

    def __init__(
        self,
        detector: SmartTurn | None,
        min_silence_ms: int = 200,
        max_silence_ms: int = 800,
        mode: str = "smart_turn",
    ) -> None:
        self.detector = detector
        self.min_silence_ms = int(min_silence_ms)
        self.max_silence_ms = int(max_silence_ms)
        self.mode = mode
        self.reset()

    def configure(
        self,
        min_silence_ms: int | None = None,
        max_silence_ms: int | None = None,
        mode: str | None = None,
    ) -> None:
        if min_silence_ms is not None:
            self.min_silence_ms = int(min_silence_ms)
        if max_silence_ms is not None:
            self.max_silence_ms = int(max_silence_ms)
        if mode is not None:
            self.mode = str(mode)
        self.reset()

    def reset(self) -> None:
        self._checked = False
        self._complete = False

    def should_end(self, ep: EndpointState, audio: np.ndarray | None) -> bool:
        if not ep.heard_speech:
            return False
        mode = self.mode
        ready = self.detector is not None and self.detector._session is not None and not self.detector.error
        if mode != "smart_turn" or not ready:
            return ep.silence_ms >= float(self.max_silence_ms if mode != "smart_turn" else self.min_silence_ms)
        if ep.in_speech:
            self.reset()
            return False
        if ep.silence_ms < float(self.min_silence_ms):
            return False
        if not self._checked:
            self._checked = True
            pcm = audio if audio is not None else np.zeros(0, dtype=np.float32)
            try:
                verdict = self.detector.predict(pcm)
                self._complete = verdict.complete
                log.debug("smart-turn p=%.3f complete=%s", verdict.probability, verdict.complete)
            except Exception:
                log.exception("Smart Turn predict failed")
                self._complete = True
        if self._complete:
            return True
        return ep.silence_ms >= float(self.max_silence_ms)
