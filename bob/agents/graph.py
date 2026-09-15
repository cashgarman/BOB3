from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from bob.agents.nodes.direct import direct_node
from bob.agents.nodes.memory import memory_agent_node
from bob.agents.nodes.orchestrator import orchestrator_node
from bob.agents.nodes.retrieve import retrieve_node
from bob.agents.nodes.speaker import speaker_node
from bob.agents.nodes.tools import tools_node
from bob.agents.nodes.validator import regex_gate_node, validator_node
from bob.agents.state import TurnRuntime, TurnState, reset_runtime, set_runtime
from bob.prompt_lab.versioning import current_version


def _route_from_orchestrator(state: TurnState) -> str:
    return str(state.get("route") or "speak")


def _after_memory(state: TurnState) -> str:
    if str(state.get("spoken") or "").strip():
        return "regex_gate"
    return "speaker"


def _after_direct(state: TurnState) -> str:
    if str(state.get("spoken") or state.get("draft") or "").strip():
        return "regex_gate"
    return "speaker"


def _after_tools(state: TurnState) -> str:
    if str(state.get("spoken") or state.get("draft") or "").strip():
        return "regex_gate"
    return "speaker"


def _after_gate(state: TurnState) -> str:
    if state.get("gate_ok"):
        return END
    if int(state.get("repair_count") or 0) >= 2:
        return END
    return "validator"


def _after_validator(state: TurnState) -> str:
    if state.get("gate_ok") or int(state.get("repair_count") or 0) >= 2:
        return END
    if not str(state.get("spoken") or state.get("draft") or "").strip():
        return "speaker"
    return END


def build_turn_graph():
    graph = StateGraph(TurnState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("direct", direct_node)
    graph.add_node("tools", tools_node)
    graph.add_node("memory_agent", memory_agent_node)
    graph.add_node("speaker", speaker_node)
    graph.add_node("regex_gate", regex_gate_node)
    graph.add_node("validator", validator_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        _route_from_orchestrator,
        {
            "direct": "direct",
            "tools": "tools",
            "memory": "memory_agent",
            "speak": "speaker",
        },
    )
    graph.add_conditional_edges(
        "direct",
        _after_direct,
        {"regex_gate": "regex_gate", "speaker": "speaker"},
    )
    graph.add_conditional_edges(
        "tools",
        _after_tools,
        {"regex_gate": "regex_gate", "speaker": "speaker"},
    )
    graph.add_conditional_edges(
        "memory_agent",
        _after_memory,
        {"regex_gate": "regex_gate", "speaker": "speaker"},
    )
    graph.add_edge("speaker", "regex_gate")
    graph.add_conditional_edges(
        "regex_gate",
        _after_gate,
        {"validator": "validator", END: END},
    )
    graph.add_conditional_edges(
        "validator",
        _after_validator,
        {"speaker": "speaker", END: END},
    )
    return graph.compile()


_COMPILED = None


def compiled_turn_graph():
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = build_turn_graph()
    return _COMPILED


def initial_turn_state(user_text: str, memory_block: str = "", session_id: int | None = None) -> TurnState:
    state: TurnState = {
        "user_text": user_text,
        "memory_block": memory_block or "",
        "route": "speak",
        "route_kind": "",
        "tool_results": [],
        "draft": "",
        "spoken": "",
        "chunks": [],
        "used_tools": False,
        "gate_ok": False,
        "repair_count": 0,
        "prompt_version": current_version(),
    }
    if session_id is not None:
        state["session_id"] = int(session_id)
    return state


def stream_turn(
    llm: Any,
    user_text: str,
    memory_block: str = "",
    tools: list[dict[str, Any]] | None = None,
    on_tool=None,
    on_thought=None,
    cancel=None,
    max_rounds: int = 1,
    runtime: TurnRuntime | None = None,
):
    """Run the turn graph and yield spoken chunks for TTS."""
    llm.last_internal_thought = ""
    if runtime is None:
        runtime = TurnRuntime(
            llm=llm,
            on_tool=on_tool,
            on_thought=on_thought,
            cancel=cancel,
            tools=None if llm._tools_unsupported else tools,
            max_rounds=max_rounds,
        )
    else:
        runtime.llm = llm
        if on_tool is not None:
            runtime.on_tool = on_tool
        if on_thought is not None:
            runtime.on_thought = on_thought
        if cancel is not None:
            runtime.cancel = cancel
        if tools is not None and not llm._tools_unsupported:
            runtime.tools = tools
        runtime.max_rounds = max_rounds
    if llm._tools_unsupported:
        runtime.tools = None
        runtime.on_tool = None

    token = set_runtime(runtime)
    try:
        result = compiled_turn_graph().invoke(
            initial_turn_state(user_text, memory_block, runtime.session_id)
        )
    finally:
        reset_runtime(token)

    llm.last_turn_scores = dict(result.get("scores") or {})
    chunks = [c for c in (result.get("chunks") or []) if str(c).strip()]
    spoken = str(result.get("spoken") or "").strip()
    if chunks:
        for chunk in chunks:
            yield chunk
        return
    if spoken:
        yield spoken
