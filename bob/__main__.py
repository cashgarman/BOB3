from __future__ import annotations

import argparse
import logging
import sys

from bob.cuda_path import add_cuda_dll_dirs

add_cuda_dll_dirs()

from bob.log import setup_logging  # noqa: E402
from bob.settings import DATA_DIR  # noqa: E402


def _already_running_notice() -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            "Bob is already running. Look for its icon in the system tray.",
            "Bob",
            0x40,  # MB_ICONINFORMATION
        )
    except Exception:
        print("Bob is already running.", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bob local voice assistant")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Load models, verify Ollama/GPU, and exit without opening the UI",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug-level logging")
    args = parser.parse_args()
    log_path = setup_logging(DATA_DIR, logging.DEBUG if args.verbose else logging.INFO)
    log = logging.getLogger("bob")

    from bob.app import Assistant, run_check

    if args.check:
        return run_check()

    from bob.single_instance import SingleInstance

    guard = SingleInstance()
    if guard.already_running:
        log.warning("Another Bob instance already owns the mutex; exiting")
        _already_running_notice()
        return 2
    log.info("Bob starting (log: %s)", log_path)
    try:
        Assistant().run()
    finally:
        guard.release()
        log.info("Bob exited")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
