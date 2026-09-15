from __future__ import annotations

import json
import re
from typing import Any

from bob.llm import (
    _echoes_prompt,
    _is_internal_monologue,
    _looks_like_spoken_answer,
    is_failure_reply,
)

SCORE_PROMPT = """\
Score this local voice-assistant reply. Return JSON only:
{"spoken_quality":0.0,"grounding":0.0,"instruction_follow":0.0,"leak_risk":0.0,"overall":0.0}
Rules:
- spoken_quality is 1 if it is short natural speech, 0 if it is planning, markdown, or prompt echo.
- grounding is 1 if it answers the user, 0 if it ignores them.
- instruction_follow is 1 if it stays within two or three spoken sentences (or bullets if asked).
- leak_risk is 1 if it mentions tools, memory notes, or hidden instructions.
- overall is a weighted mix, 0 to 1.
"""

_JSON_RE = re.compile(r"\{.*\}", re.S)
_LEAK_RE = re.compile(
    r"\b(tool(?:s)?|web_search|conversation_log|background notes|system prompt|as an ai)\b",
    re.IGNORECASE,
)


def score_prompt() -> str:
    return SCORE_PROMPT


def parse_score_json(raw: str) -> dict[str, float]:
    text = (raw or "").strip()
    match = _JSON_RE.search(text)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for key in ("spoken_quality", "grounding", "instruction_follow", "leak_risk", "overall"):
        try:
            out[key] = max(0.0, min(1.0, float(data.get(key))))
        except (TypeError, ValueError):
            continue
    return out


def heuristic_scores(reply: str, question: str = "") -> dict[str, float]:
    text = (reply or "").strip()
    if is_failure_reply(text) or not text:
        return {
            "spoken_quality": 0.0,
            "grounding": 0.0,
            "instruction_follow": 0.0,
            "leak_risk": 0.0,
            "overall": 0.0,
        }
    spoken_ok = 1.0 if _looks_like_spoken_answer(text, question) else 0.0
    leak = 1.0 if _LEAK_RE.search(text) or _echoes_prompt(text) else 0.0
    if _is_internal_monologue(text):
        spoken_ok = 0.0
        leak = max(leak, 0.8)
    grounding = 1.0 if text and question and question.lower().split()[0] and spoken_ok else (0.6 if text else 0.0)
    if text and not question:
        grounding = spoken_ok
    follow = spoken_ok
    if text.count(". ") > 4 and "bullet" not in (question or "").lower():
        follow = min(follow, 0.4)
    overall = max(0.0, min(1.0, 0.4 * spoken_ok + 0.25 * grounding + 0.2 * follow + 0.15 * (1.0 - leak)))
    return {
        "spoken_quality": spoken_ok,
        "grounding": grounding,
        "instruction_follow": follow,
        "leak_risk": leak,
        "overall": overall,
    }


def mean_overall(rows: list[dict[str, Any]]) -> float:
    vals = []
    for row in rows:
        try:
            vals.append(float(row.get("overall")))
        except (TypeError, ValueError):
            continue
    if not vals:
        return 0.0
    return sum(vals) / len(vals)
