from __future__ import annotations

import re

_SENTENCE = re.compile(r"(.+?[\.!\?](?:[\"')\]]+)?)(\s+|$)")


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Pull complete spoken sentences off a streaming buffer."""
    done: list[str] = []
    rest = buffer
    while True:
        match = _SENTENCE.search(rest)
        if not match:
            break
        sentence = (match.group(1) or "").strip()
        if len(sentence) < 2:
            break
        done.append(sentence)
        rest = rest[match.end() :]
    return done, rest


def gpu_memory_line() -> str:
    import subprocess

    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total",
                "--format=csv,noheader",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip().splitlines()[0]
    except Exception as exc:
        return f"nvidia-smi unavailable ({exc})"
