from __future__ import annotations

from typing import Any

from bob.agents.state import TurnState, get_runtime
from bob.llm import needs_conversation_log


def memory_agent_node(state: TurnState) -> dict[str, Any]:
    """Fetch conversation/memory tools, then let the speaker synthesize."""
    runtime = get_runtime()
    llm = runtime.llm
    user_text = str(state.get("user_text") or "")
    on_tool = runtime.on_tool
    results: list[tuple[str, str]] = []
    if on_tool is None:
        return {"used_tools": False, "tool_results": []}

    if needs_conversation_log(user_text):
        try:
            result = on_tool("conversation_log", {"limit": 40})
        except Exception as exc:
            result = f"Error: tool 'conversation_log' failed: {exc}"
        llm.history.append({"role": "tool", "tool_name": "conversation_log", "content": result})
        results.append(("conversation_log", result))
    else:
        try:
            result = on_tool("memory_search", {"query": user_text})
        except Exception as exc:
            result = f"Error: tool 'memory_search' failed: {exc}"
        llm.history.append({"role": "tool", "tool_name": "memory_search", "content": result})
        results.append(("memory_search", result))

    reply = llm._finalize_tool_synthesis(user_text, str(state.get("memory_block") or ""), runtime.on_thought)
    if reply:
        return {
            "draft": reply,
            "spoken": reply,
            "chunks": [reply],
            "used_tools": True,
            "tool_results": results,
            "gate_ok": True,
        }
    return {"used_tools": True, "tool_results": results, "draft": "", "gate_ok": False}


def ingest_facts(user_text: str, assistant_text: str, generate, memory: Any) -> list[str]:
    if memory is None:
        return []
    return list(memory.ingest(user_text, assistant_text, generate) or [])
