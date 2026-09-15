from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bob.prompts import load_system_prompt
from bob.prompt_lab.improver import propose_system_prompt
from bob.prompt_lab.scorer import heuristic_scores, mean_overall
from bob.prompt_lab.versioning import (
    apply_prompt,
    in_cooldown,
    load_state,
    prompt_preserves_spoken_style,
    rollback_prompt,
    snapshot_current,
)

log = logging.getLogger(__name__)


def shadow_eval(
    turns: list[tuple[str, str]],
    candidate_prompt: str,
    generate: Callable[[str, str, int], str],
) -> float:
    if not turns:
        return 0.0
    scores: list[float] = []
    for user, _reply in turns:
        try:
            drafted = generate(candidate_prompt, user or " ", 160)
        except Exception:
            drafted = ""
        scores.append(float(heuristic_scores(drafted, user).get("overall") or 0.0))
    return sum(scores) / len(scores)


def maybe_rollback(
    recent_scores: list[dict[str, Any]],
    *,
    rollback_delta: float,
    cooldown_hours: float,
    data_dir: Path | None = None,
) -> bool:
    state = load_state(data_dir)
    if state.current_version < 2 or not recent_scores:
        return False
    live = mean_overall(recent_scores)
    if live + float(rollback_delta) < float(state.applied_score or 0):
        result = rollback_prompt(cooldown_hours=cooldown_hours, data_dir=data_dir)
        return result is not None
    leak = [float(row.get("leak_risk") or 0) for row in recent_scores]
    if leak and (sum(leak) / len(leak)) >= 0.4:
        result = rollback_prompt(cooldown_hours=cooldown_hours, data_dir=data_dir)
        return result is not None
    return False


def maybe_improve_prompt(
    *,
    generate: Callable[[str, str, int], str],
    transcripts: list[tuple[str, str, float]],
    holdout: list[tuple[str, str]],
    min_turns: int = 30,
    min_improve: float = 0.05,
    auto_improve: bool = True,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    state = load_state(data_dir)
    if not auto_improve or in_cooldown(state, data_dir):
        return {"applied": False, "reason": "cooldown" if in_cooldown(state, data_dir) else "disabled"}
    if len(transcripts) < int(min_turns):
        return {"applied": False, "reason": "not_enough_turns"}
    snapshot_current(data_dir)
    current = load_system_prompt()
    candidate = propose_system_prompt(current, transcripts, generate)
    if not prompt_preserves_spoken_style(candidate) or candidate.strip() == current.strip():
        return {"applied": False, "reason": "rejected_candidate"}
    baseline = shadow_eval(holdout or [(u, r) for u, r, _s in transcripts[-8:]], current, generate)
    proposed = shadow_eval(holdout or [(u, r) for u, r, _s in transcripts[-8:]], candidate, generate)
    if proposed + 1e-9 < baseline + float(min_improve):
        return {"applied": False, "reason": "no_gain", "baseline": baseline, "proposed": proposed}
    apply_prompt(candidate, score=proposed, data_dir=data_dir)
    return {"applied": True, "baseline": baseline, "proposed": proposed}


def run_prompt_lab(
    settings: Any,
    generate: Callable[[str, str, int], str],
    transcripts: list[tuple[str, str, float]],
    recent_scores: list[dict[str, Any]],
    data_dir: Path | None = None,
) -> dict[str, Any]:
    if not getattr(settings, "prompt_lab_enabled", True):
        return {"applied": False, "reason": "disabled"}
    rolled = maybe_rollback(
        recent_scores,
        rollback_delta=float(getattr(settings, "prompt_rollback_delta", 0.08) or 0.08),
        cooldown_hours=float(getattr(settings, "prompt_cooldown_hours", 24.0) or 24.0),
        data_dir=data_dir,
    )
    if rolled:
        log.info("Prompt lab rolled back the system prompt")
        return {"applied": False, "reason": "rolled_back"}
    holdout = [(u, r) for u, r, _s in transcripts[-8:]]
    return maybe_improve_prompt(
        generate=generate,
        transcripts=transcripts,
        holdout=holdout,
        min_turns=int(getattr(settings, "prompt_min_turns", 30) or 30),
        min_improve=float(getattr(settings, "prompt_min_improve", 0.05) or 0.05),
        auto_improve=bool(getattr(settings, "prompt_auto_improve", True)),
        data_dir=data_dir,
    )
