from __future__ import annotations

import re

_SENTENCE = re.compile(r"(.+?[\.!\?](?:[\"')\]]+)?)(\s+|$)")
_CLAUSE = re.compile(r"(.{12,}?(?:,|;|:|—|–|\s-\s))(\s+|$)")
_ABBREV = re.compile(
    r"(?:^|[\s(\[])(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|etc|e\.g|i\.e|U\.S|U\.K|No|[A-Za-z])\.$",
    re.I,
)
_DECIMAL = re.compile(r".*\d\.$")


def _is_false_end(sentence: str) -> bool:
    if _DECIMAL.match(sentence):
        return True
    if _ABBREV.search(sentence):
        return True
    return bool(re.search(r"\b[A-Z]\.$", sentence))


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
        if _is_false_end(sentence):
            nxt = _SENTENCE.search(rest, match.end())
            if not nxt:
                break
            sentence = rest[: nxt.end()].strip()
            if _is_false_end(sentence.rstrip()):
                break
            done.append(sentence)
            rest = rest[nxt.end() :]
            continue
        done.append(sentence)
        rest = rest[match.end() :]
    return done, rest


def split_speakable(buffer: str, first: bool = False) -> tuple[list[str], str]:
    """Split a streaming reply into TTS chunks.

    The first chunk of a reply emits at a clause boundary (after ~12 characters)
    so time-to-first-audio stays low. Later chunks prefer whole sentences.
    """
    rest = buffer
    done: list[str] = []
    if first:
        match = _CLAUSE.search(rest)
        if match:
            clause = (match.group(1) or "").strip()
            if len(clause) >= 12:
                done.append(clause)
                rest = rest[match.end() :]
    more, rest = split_sentences(rest)
    done.extend(more)
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
