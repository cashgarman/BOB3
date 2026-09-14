from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME = "bob.log"


def setup_logging(data_dir: Path, level: int = logging.INFO) -> Path:
    """Log to data/bob.log (rotating) and, when a console exists, to stderr.

    Bob normally runs under pythonw.exe, which has no console, so without this
    every traceback from a background thread is lost.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LOG_NAME
    root = logging.getLogger()
    if any(getattr(h, "_bob_log", False) for h in root.handlers):
        return path
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)-12s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler._bob_log = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        stream._bob_log = True  # type: ignore[attr-defined]
        root.addHandler(stream)

    # Third-party libraries are chatty at INFO.
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers", "lancedb", "mcp", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        name = args.thread.name if args.thread else "?"
        logging.getLogger("bob.thread").error(
            "Unhandled exception in thread %s", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        )

    threading.excepthook = _thread_hook

    def _sys_hook(exc_type, exc_value, exc_tb) -> None:
        logging.getLogger("bob").critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _sys_hook
    return path
