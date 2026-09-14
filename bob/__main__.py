from __future__ import annotations

import argparse
import sys

from bob.cuda_path import add_cuda_dll_dirs

add_cuda_dll_dirs()

from bob.app import Assistant, run_check


def main() -> None:
    parser = argparse.ArgumentParser(description="Bob local voice assistant")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Load models, verify Ollama/GPU, and exit without opening the UI",
    )
    args = parser.parse_args()
    if args.check:
        raise SystemExit(run_check())
    Assistant().run()


if __name__ == "__main__":
    sys.exit(main() or 0)
