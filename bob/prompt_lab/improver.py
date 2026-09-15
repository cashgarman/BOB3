from __future__ import annotations

from collections.abc import Callable

IMPROVE_PROMPT = """\
You rewrite BOB's system prompt using scored voice transcripts.
Keep BOB a local voice assistant that speaks two or three natural sentences.
Lead with the answer. No markdown or bullets unless the user asks.
Background notes and memory are never read aloud unless the user asks.
Return ONLY the new system prompt, no commentary.
Do not mention tools, scores, or that you are rewriting a prompt.
"""


def propose_system_prompt(
    current: str,
    transcripts: list[tuple[str, str, float]],
    generate: Callable[[str, str, int], str],
) -> str:
    lines = [f"Current prompt:\n{current.strip()}"]
    if transcripts:
        lines.append("Recent scored turns:")
        for user, reply, score in transcripts[:12]:
            lines.append(f"- score={score:.2f} user={user[:160]!r} bob={reply[:160]!r}")
    raw = generate(IMPROVE_PROMPT, "\n".join(lines), 400)
    return (raw or "").strip()
