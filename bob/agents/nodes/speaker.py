from __future__ import annotations

from typing import Any

from bob.agents.state import TurnState, get_runtime
from bob.llm import _GENERIC_REASK_REPLY, _fallback_spoken_reply, _try_direct_answer, is_failure_reply


def speaker_node(state: TurnState) -> dict[str, Any]:
    runtime = get_runtime()
    llm = runtime.llm
    user_text = str(state.get("user_text") or "")
    memory_block = str(state.get("memory_block") or "")
    if str(state.get("spoken") or "").strip():
        return {}

    direct = _try_direct_answer(user_text)
    if direct:
        llm._append_internal_thought("Answered directly.", runtime.on_thought)
        llm._commit_assistant_reply(direct)
        return {
            "draft": direct,
            "spoken": direct,
            "chunks": [direct],
            "gate_ok": True,
            "judge_ok": True,
            "trusted_reply": True,
        }

    draft = llm._generate_spoken_answer(
        user_text,
        memory_block=memory_block,
        on_tool=runtime.on_tool,
    )
    judge_ok = False
    reason = "empty reply"
    if draft.strip() and not is_failure_reply(draft):
        judge_ok, reason = llm._judge_reply(user_text, draft)

    if not judge_ok:
        llm._append_internal_thought(
            f"Judge rejected the draft ({reason or 'unclear'}); retrying once.",
            runtime.on_thought,
        )
        retry = llm._generate_spoken_answer(
            user_text,
            memory_block=memory_block,
            on_tool=runtime.on_tool,
            correction=reason or "it was not natural spoken language",
        )
        if retry.strip() and not is_failure_reply(retry) and retry.strip() != draft.strip():
            retry_ok, retry_reason = llm._judge_reply(user_text, retry)
            if retry_ok:
                draft, judge_ok, reason = retry, True, ""
            else:
                draft, reason = retry, retry_reason

    used_fallback = False
    if not judge_ok:
        fallback = _fallback_spoken_reply(user_text) or _GENERIC_REASK_REPLY
        llm._append_internal_thought(
            "Used a safe fallback reply after the judge rejected two attempts.",
            runtime.on_thought,
        )
        draft = fallback
        used_fallback = True
    else:
        llm._append_internal_thought("Answered with a direct generation pass; the judge approved it.", runtime.on_thought)

    reply = llm._commit_assistant_reply(draft)
    gate_ok = bool(reply.strip())
    return {
        "draft": reply,
        "spoken": reply,
        "chunks": [reply] if reply else [],
        "gate_ok": gate_ok,
        "judge_ok": judge_ok,
        "used_fallback": used_fallback,
        "trusted_reply": True,
    }
