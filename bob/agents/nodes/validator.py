from __future__ import annotations

import random
from typing import Any

from bob.agents.state import TurnState, get_runtime
from bob.llm import (
    _looks_like_spoken_answer,
    _sanitize_spoken_reply,
    is_failure_reply,
)
from bob.prompt_lab.scorer import heuristic_scores, parse_score_json, score_prompt


def regex_gate_node(state: TurnState) -> dict[str, Any]:
    user_text = str(state.get("user_text") or "")
    draft = str(state.get("spoken") or state.get("draft") or "")
    cleaned = _sanitize_spoken_reply(draft, None, user_text) or draft
    ok = bool(cleaned.strip()) and _looks_like_spoken_answer(cleaned, user_text)
    runtime = get_runtime()
    if ok:
        runtime.llm._append_internal_thought("Regex gate accepted the spoken reply.", runtime.on_thought)
        chunks = list(state.get("chunks") or [])
        if not chunks and cleaned:
            chunks = [cleaned]
        scores = heuristic_scores(cleaned, user_text)
        scores["prompt_version"] = int(state.get("prompt_version") or 0)
        return {
            "draft": cleaned,
            "spoken": cleaned,
            "chunks": chunks,
            "gate_ok": True,
            "scores": scores,
        }
    scores = heuristic_scores(cleaned, user_text)
    scores["prompt_version"] = int(state.get("prompt_version") or 0)
    runtime.llm._append_internal_thought("Regex gate rejected the draft; validator will retry.", runtime.on_thought)
    return {"draft": cleaned, "gate_ok": False, "scores": scores}


def validator_node(state: TurnState) -> dict[str, Any]:
    runtime = get_runtime()
    llm = runtime.llm
    user_text = str(state.get("user_text") or "")
    draft = str(state.get("draft") or "")
    used_tools = bool(state.get("used_tools"))
    repair_count = int(state.get("repair_count") or 0)
    sample = random.random() < float(runtime.score_sample_rate or 0)
    blocking = not bool(state.get("gate_ok"))
    llm_score = used_tools and runtime.validator_on_tools or sample

    if blocking:
        reply = llm._recover_reply(
            user_text,
            memory_block=str(state.get("memory_block") or ""),
            on_tool=runtime.on_tool,
        )
        if reply and not is_failure_reply(reply):
            if not llm._history_ends_with_assistant(reply):
                llm.history.append({"role": "assistant", "content": reply})
            scores = heuristic_scores(reply, user_text)
            scores["prompt_version"] = int(state.get("prompt_version") or 0)
            llm._append_internal_thought("Validator repaired the spoken reply.", runtime.on_thought)
            return {
                "draft": reply,
                "spoken": reply,
                "chunks": [reply],
                "gate_ok": _looks_like_spoken_answer(reply, user_text),
                "scores": scores,
                "repair_count": repair_count + 1,
            }
        if reply and is_failure_reply(reply):
            llm._append_internal_thought("Validator could not repair the spoken reply.", runtime.on_thought)

    scores = dict(state.get("scores") or heuristic_scores(draft, user_text))
    if llm_score and draft.strip():
        try:
            raw = llm.generate(score_prompt(), f"User: {user_text}\nBOB: {draft}", 120)
            parsed = parse_score_json(raw)
            if parsed:
                scores.update(parsed)
        except Exception:
            pass
    scores["prompt_version"] = int(state.get("prompt_version") or 0)
    return {
        "scores": scores,
        "repair_count": repair_count + 1,
        "gate_ok": bool(state.get("gate_ok")) or _looks_like_spoken_answer(draft, user_text),
    }
