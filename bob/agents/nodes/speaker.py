from __future__ import annotations

from typing import Any

from bob.agents.state import TurnState, get_runtime
from bob.llm import _finalize_spoken_reply, _looks_like_spoken_answer, _try_direct_answer


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

    from bob.agents.nodes.tools import consume_round

    system = llm._answer_system(memory_block=memory_block)
    spoken: list[str] = []
    content, _calls = consume_round(llm, system, None, runtime.cancel, spoken, user_text, runtime.on_thought)
    cleaned = _finalize_spoken_reply(content or "".join(spoken), llm.history, user_text) or (content or "").strip()
    gate_ok = bool(cleaned.strip()) and _looks_like_spoken_answer(cleaned, user_text)
    llm._append_internal_thought("Answered with a direct generation pass.", runtime.on_thought)
    if cleaned and not gate_ok:
        llm._append_internal_thought(
            "Generation was unusable; handing to the validator.",
            runtime.on_thought,
        )
    if cleaned and gate_ok:
        llm.history.append({"role": "assistant", "content": cleaned})
    chunks = [cleaned] if cleaned else (spoken or ([content] if content.strip() else []))
    return {"draft": cleaned, "spoken": cleaned, "chunks": chunks, "gate_ok": gate_ok}
