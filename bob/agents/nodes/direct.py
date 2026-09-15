from __future__ import annotations

from typing import Any

from bob.agents.state import TurnState, get_runtime
from bob.llm import _format_time_tool_result, _try_direct_answer, needs_current_time


def direct_node(state: TurnState) -> dict[str, Any]:
    runtime = get_runtime()
    llm = runtime.llm
    user_text = str(state.get("user_text") or "")
    kind = str(state.get("route_kind") or "")
    on_thought = runtime.on_thought

    if kind == "time" or (needs_current_time(user_text) and runtime.on_tool):
        try:
            result = runtime.on_tool("get_current_time", {})  # type: ignore[misc]
        except Exception as exc:
            result = f"Error: tool 'get_current_time' failed: {exc}"
        reply = _format_time_tool_result(result)
        if reply:
            llm._append_internal_thought("Called get_current_time directly (skipped LLM).", on_thought)
            llm.history.append({"role": "tool", "tool_name": "get_current_time", "content": result})
            llm._commit_assistant_reply(reply)
            return {
                "draft": reply,
                "spoken": reply,
                "chunks": [reply],
                "used_tools": True,
                "tool_results": [("get_current_time", result)],
                "gate_ok": True,
            }

    direct = _try_direct_answer(user_text)
    if direct:
        llm._append_internal_thought("Answered directly.", on_thought)
        llm._commit_assistant_reply(direct)
        return {"draft": direct, "spoken": direct, "chunks": [direct], "used_tools": False, "gate_ok": True}

    return {"draft": "", "gate_ok": False, "route": "speak"}
