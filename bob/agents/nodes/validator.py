from __future__ import annotations

from typing import Any

from bob.agents.state import TurnState, get_runtime
from bob.llm import _fallback_spoken_reply, _looks_like_spoken_answer, _sanitize_spoken_reply, is_failure_reply
from bob.prompt_lab.scorer import heuristic_scores


def regex_gate_node(state: TurnState) -> dict[str, Any]:
    """Cheap structural gate for replies that never went through the judge.

    Judge-approved replies (speaker/tool-synthesis paths) arrive here with
    `trusted_reply=True` and are only checked for non-emptiness; everything
    else still runs the lightweight `_looks_like_spoken_answer` structural
    check as a safety net.
    """
    user_text = str(state.get("user_text") or "")
    draft = str(state.get("spoken") or state.get("draft") or "")
    cleaned = _sanitize_spoken_reply(draft, None, user_text) or draft
    judge_ok = state.get("judge_ok")
    used_fallback = bool(state.get("used_fallback"))
    if state.get("trusted_reply"):
        ok = bool(cleaned.strip())
    else:
        ok = bool(cleaned.strip()) and _looks_like_spoken_answer(cleaned, user_text)
    runtime = get_runtime()
    scores = heuristic_scores(cleaned, user_text, judge_ok=judge_ok, used_fallback=used_fallback)
    scores["prompt_version"] = int(state.get("prompt_version") or 0)
    if ok:
        runtime.llm._append_internal_thought("Gate accepted the spoken reply.", runtime.on_thought)
        chunks = list(state.get("chunks") or [])
        if not chunks and cleaned:
            chunks = [cleaned]
        return {
            "draft": cleaned,
            "spoken": cleaned,
            "chunks": chunks,
            "gate_ok": True,
            "scores": scores,
        }
    runtime.llm._append_internal_thought("Gate rejected the draft; validator will retry.", runtime.on_thought)
    return {"draft": cleaned, "gate_ok": False, "scores": scores}


def validator_node(state: TurnState) -> dict[str, Any]:
    """Last-chance repair for drafts that never got a usable reply.

    Judge-approved (`trusted_reply`) replies pass straight through. Anything
    else gets one more `_recover_reply` attempt, which is itself judged
    before being committed to history.
    """
    runtime = get_runtime()
    llm = runtime.llm
    user_text = str(state.get("user_text") or "")
    draft = str(state.get("draft") or "")
    repair_count = int(state.get("repair_count") or 0)
    blocking = not bool(state.get("gate_ok"))
    judge_ok = state.get("judge_ok")
    used_fallback = bool(state.get("used_fallback"))

    if state.get("trusted_reply") and draft.strip():
        scores = heuristic_scores(draft, user_text, judge_ok=judge_ok, used_fallback=used_fallback)
        scores["prompt_version"] = int(state.get("prompt_version") or 0)
        return {
            "draft": draft,
            "spoken": draft,
            "chunks": list(state.get("chunks") or [draft]),
            "gate_ok": True,
            "scores": scores,
            "repair_count": repair_count,
        }

    if blocking:
        reply = llm._recover_reply(
            user_text,
            memory_block=str(state.get("memory_block") or ""),
            on_tool=runtime.on_tool,
        )
        if reply and not is_failure_reply(reply):
            reply_judge_ok, reason = llm._judge_reply(user_text, reply)
            reply_used_fallback = False
            if not reply_judge_ok:
                fallback = _fallback_spoken_reply(user_text)
                if fallback:
                    llm._append_internal_thought(
                        f"Judge rejected the repaired reply ({reason or 'unclear'}); using a safe fallback.",
                        runtime.on_thought,
                    )
                    reply = fallback
                    reply_used_fallback = True
            llm._commit_assistant_reply(reply)
            scores = heuristic_scores(reply, user_text, judge_ok=reply_judge_ok, used_fallback=reply_used_fallback)
            scores["prompt_version"] = int(state.get("prompt_version") or 0)
            llm._append_internal_thought("Validator repaired the spoken reply.", runtime.on_thought)
            return {
                "draft": reply,
                "spoken": reply,
                "chunks": [reply],
                "gate_ok": True,
                "judge_ok": reply_judge_ok,
                "used_fallback": reply_used_fallback,
                "scores": scores,
                "repair_count": repair_count + 1,
            }
        if reply and is_failure_reply(reply):
            llm._append_internal_thought("Validator could not repair the spoken reply.", runtime.on_thought)

    scores = dict(
        state.get("scores") or heuristic_scores(draft, user_text, judge_ok=judge_ok, used_fallback=used_fallback)
    )
    scores["prompt_version"] = int(state.get("prompt_version") or 0)
    return {
        "scores": scores,
        "repair_count": repair_count + 1,
        "gate_ok": bool(state.get("gate_ok")) or _looks_like_spoken_answer(draft, user_text),
    }
