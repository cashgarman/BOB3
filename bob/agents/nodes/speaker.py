from __future__ import annotations

from typing import Any

from bob.agents.state import TurnState, get_runtime
from bob.llm import _looks_like_spoken_answer, _try_direct_answer, is_failure_reply


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
        llm.history.append({"role": "assistant", "content": direct})
        return {"draft": direct, "spoken": direct, "chunks": [direct], "gate_ok": True}

    reply = llm._generate_spoken_answer(
        user_text,
        memory_block=memory_block,
        on_tool=runtime.on_tool,
    )
    gate_ok = bool(reply.strip()) and not is_failure_reply(reply) and _looks_like_spoken_answer(reply, user_text)
    llm._append_internal_thought("Answered with a direct generation pass.", runtime.on_thought)
    if reply and not gate_ok:
        llm._append_internal_thought(
            "Generation was unusable; handing to the validator.",
            runtime.on_thought,
        )
    if reply and gate_ok:
        llm.history.append({"role": "assistant", "content": reply})
    chunks = [reply] if reply else []
    return {"draft": reply, "spoken": reply, "chunks": chunks, "gate_ok": gate_ok}
