"""Download Ollama + local ML assets with per-stage progress callbacks."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_ROOT = _PKG.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from install_progress import format_bytes

ProgressFn = Callable[[int, int, str, int | None, int | None], None]

STAGES = (
    "ollama",
    "llm",
    "parakeet",
    "kokoro",
    "wakeword",
    "smart_turn",
    "embeddings",
    "verify",
)

STAGE_TITLES = (
    "Starting Ollama",
    "Pulling AI model via Ollama",
    "Downloading Parakeet speech model",
    "Downloading Kokoro voice",
    "Downloading wake-word model",
    "Downloading Smart Turn model",
    "Downloading memory embeddings",
    "Verifying BOB",
)

PARAKEET_HF_REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
KOKORO_ONNX = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
SMART_TURN_REPO = "pipecat-ai/smart-turn-v3"
SMART_TURN_ONNX = "smart-turn-v3.2-cpu.onnx"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

HF_RETRY_ATTEMPTS = 5
HF_RETRY_BASE_DELAY = 2.0


class BootstrapError(RuntimeError):
    pass


def bootstrap_all(
    install_root: Path,
    on_progress: ProgressFn | None = None,
    *,
    llm_model: str | None = None,
    ollama_host: str | None = None,
    skip_verify: bool = False,
) -> None:
    root = Path(install_root)
    settings = _load_settings(root)
    model = (llm_model or settings.get("llm_model") or "qwen3:4b").strip()
    host = (ollama_host or settings.get("ollama_host") or "http://127.0.0.1:11434").strip()
    models_dir = root / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    wake_word = str(settings.get("wake_word") or "hey_jarvis")
    total = len(STAGES) - (1 if skip_verify else 0)

    def emit(index: int, name: str, completed: int | None, nbytes: int | None, label: str | None = None) -> None:
        if on_progress:
            title = label or STAGE_TITLES[index] if index < len(STAGE_TITLES) else name
            on_progress(index, total, title, completed, nbytes)

    emit(0, "ollama", 0, 1, "Starting Ollama")
    _ensure_ollama(host)
    emit(0, "ollama", 1, 1, "Ollama is running")

    emit(1, "llm", 0, None, f"Pulling {model} via Ollama")
    from bob.ollama_pull import pull_model

    def _llm_progress(completed: int | None, nbytes: int | None, status: str) -> None:
        emit(1, "llm", completed, nbytes, f"Pulling {model} via Ollama — {status}")

    pull_model(host, model, on_progress=_llm_progress)
    emit(1, "llm", 1, 1, f"{model} ready")

    emit(2, "parakeet", 0, None, "Downloading Parakeet speech model")
    _download_parakeet(models_dir / "parakeet", lambda c, t: emit(2, "parakeet", c, t, "Downloading Parakeet speech model"))
    emit(2, "parakeet", 1, 1, "Parakeet ready")

    emit(3, "kokoro", 0, None, "Downloading Kokoro voice")
    _download_kokoro(models_dir / "kokoro", lambda c, t, n: emit(3, "kokoro", c, t, f"Downloading {n}"))
    emit(3, "kokoro", 1, 1, "Kokoro ready")

    emit(4, "wakeword", 0, None, "Downloading wake-word model")
    _download_wakeword(models_dir / "wakeword", wake_word, lambda c, t: emit(4, "wakeword", c, t, "Downloading wake-word model"))
    emit(4, "wakeword", 1, 1, "Wake word ready")

    emit(5, "smart_turn", 0, None, "Downloading Smart Turn model")
    _download_smart_turn(models_dir, lambda c, t: emit(5, "smart_turn", c, t, "Downloading Smart Turn model"))
    emit(5, "smart_turn", 1, 1, "Smart Turn ready")

    emit(6, "embeddings", 0, None, "Downloading memory embeddings")
    _download_embeddings(models_dir / "embeddings", lambda c, t: emit(6, "embeddings", c, t, "Downloading memory embeddings"))
    emit(6, "embeddings", 1, 1, "Embeddings ready")

    if skip_verify:
        return
    emit(7, "verify", 0, 1, "Verifying BOB")
    _verify(root)
    emit(7, "verify", 1, 1, "BOB is ready")


def _load_settings(root: Path) -> dict:
    path = root / "config.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _is_retryable_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    retry_markers = (
        "disconnected",
        "connection",
        "timeout",
        "timed out",
        "reset",
        "temporarily unavailable",
        "502",
        "503",
        "504",
    )
    if any(marker in msg for marker in retry_markers):
        return True
    name = type(exc).__name__.lower()
    return "connect" in name or "timeout" in name or "protocol" in name


def _retry(label: str, fn: Callable[[], object], *, attempts: int = HF_RETRY_ATTEMPTS) -> object:
    delay = HF_RETRY_BASE_DELAY
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if not _is_retryable_error(exc) or attempt + 1 >= attempts:
                break
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
    raise BootstrapError(
        f"{label} failed after {attempts} attempts: {last}. "
        "Check your internet connection and run setup again."
    )


def _tqdm_class(on_bytes: Callable[[int | None, int | None], None]):
    from huggingface_hub.utils import tqdm as hf_tqdm

    class _Progress(hf_tqdm):
        def update(self, n: float = 1) -> bool | None:
            result = super().update(n)
            total = int(self.total) if self.total else None
            current = int(self.n) if self.n else None
            if total and current is not None:
                on_bytes(current, total)
            return result

    return _Progress


def _ensure_ollama(host: str, timeout_sec: float = 60.0) -> None:
    from bob.ollama_pull import ping

    if ping(host):
        return
    _start_ollama()
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if ping(host):
            return
        time.sleep(1.0)
    raise BootstrapError(
        "Ollama is installed but not responding. Start Ollama from the Start Menu and retry."
    )


def _start_ollama() -> None:
    candidates = []
    local = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    if local.is_file():
        candidates.append(local)
    candidates.append(Path("ollama"))
    for exe in candidates:
        try:
            subprocess.Popen(
                [str(exe), "serve"],
                cwd=str(Path.home()),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
            return
        except OSError:
            continue


def _download_parakeet(dest: Path, on_bytes: Callable[[int | None, int | None], None]) -> None:
    from bob.stt_parakeet import parakeet_model_ready

    dest.mkdir(parents=True, exist_ok=True)
    if parakeet_model_ready(dest):
        on_bytes(1, 1)
        return
    from huggingface_hub import snapshot_download

    def _do() -> str:
        return snapshot_download(
            PARAKEET_HF_REPO,
            local_dir=str(dest),
            tqdm_class=_tqdm_class(on_bytes),
            resume_download=True,
        )

    _retry("Parakeet speech model download", _do)
    on_bytes(1, 1)


def _download_kokoro(dest: Path, on_file: Callable[[int | None, int | None, str], None]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    files = (
        (KOKORO_ONNX, dest / "kokoro-v1.0.onnx"),
        (KOKORO_VOICES, dest / "voices-v1.0.bin"),
    )
    for url, path in files:
        _download_file(url, path, lambda c, t, n=path.name: on_file(c, t, n))


def _download_file(url: str, dest: Path, on_progress: Callable[[int | None, int | None], None]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1_000_000:
        on_progress(dest.stat().st_size, dest.stat().st_size)
        return
    tmp = dest.with_suffix(dest.suffix + ".part")

    def _reporthook(block: int, block_size: int, total: int) -> None:
        done = block * block_size
        on_progress(done, total or None)

    def _do() -> None:
        urllib.request.urlretrieve(url, tmp, reporthook=_reporthook)
        tmp.replace(dest)
        on_progress(dest.stat().st_size, dest.stat().st_size)

    _retry(f"Download {dest.name}", _do)


def _download_wakeword(
    dest: Path,
    model_name: str,
    on_bytes: Callable[[int | None, int | None], None] | None = None,
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    from openwakeword.utils import download_models

    on_bytes and on_bytes(0, None)
    _retry("Wake-word model download", lambda: download_models(model_names=[model_name], target_directory=str(dest)))
    on_bytes and on_bytes(1, 1)


def _download_smart_turn(
    models_dir: Path,
    on_bytes: Callable[[int | None, int | None], None] | None = None,
) -> None:
    dest = models_dir / SMART_TURN_ONNX
    if dest.is_file():
        on_bytes and on_bytes(1, 1)
        return
    from huggingface_hub import hf_hub_download

    models_dir.mkdir(parents=True, exist_ok=True)

    def _do() -> str:
        return hf_hub_download(
            SMART_TURN_REPO,
            SMART_TURN_ONNX,
            local_dir=str(models_dir),
            local_dir_use_symlinks=False,
            resume_download=True,
            tqdm_class=_tqdm_class(on_bytes or (lambda _c, _t: None)),
        )

    _retry("Smart Turn model download", _do)
    on_bytes and on_bytes(1, 1)


def _download_embeddings(
    dest: Path,
    on_bytes: Callable[[int | None, int | None], None] | None = None,
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    from sentence_transformers import SentenceTransformer

    on_bytes and on_bytes(0, None)

    def _do() -> SentenceTransformer:
        return SentenceTransformer(EMBED_MODEL, cache_folder=str(dest), device="cpu")

    _retry("Memory embeddings download", _do)
    on_bytes and on_bytes(1, 1)


def _verify(root: Path) -> None:
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        python = Path(sys.executable)
    result = subprocess.run(
        [str(python), "-m", "bob", "--check"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "health check failed").strip()
        raise BootstrapError(err)


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Download BOB models")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--llm-model")
    parser.add_argument("--ollama-host")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args(argv)

    def _print(stage: int, total: int, name: str, completed: int | None, nbytes: int | None) -> None:
        pct = int(100 * (stage + (0 if not nbytes else min(1.0, (completed or 0) / nbytes))) / max(total, 1))
        extra = ""
        if completed is not None and nbytes:
            extra = f" {format_bytes(completed)} / {format_bytes(nbytes)}"
        print(f"[{pct:3d}%] {name}{extra}", flush=True)

    bootstrap_all(
        args.root,
        on_progress=_print,
        llm_model=args.llm_model,
        ollama_host=args.ollama_host,
        skip_verify=args.skip_verify,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
