from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from bob.agents.nodes.memory import ingest_facts
from bob.agents.state import TurnRuntime, reset_runtime, set_runtime


class IngestState(TypedDict, total=False):
    user_text: str
    assistant_text: str
    stored: list[str]


def _ingest_node(state: IngestState) -> dict[str, Any]:
    from bob.agents.state import get_runtime

    runtime = get_runtime()
    stored = ingest_facts(
        str(state.get("user_text") or ""),
        str(state.get("assistant_text") or ""),
        runtime.llm.generate,
        runtime.memory,
    )
    return {"stored": stored}


def build_ingest_graph():
    graph = StateGraph(IngestState)
    graph.add_node("ingest", _ingest_node)
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", END)
    return graph.compile()


_INGEST = None


def run_memory_ingest(runtime: TurnRuntime, user_text: str, assistant_text: str) -> list[str]:
    global _INGEST
    if _INGEST is None:
        _INGEST = build_ingest_graph()
    token = set_runtime(runtime)
    try:
        result = _INGEST.invoke({"user_text": user_text, "assistant_text": assistant_text})
    finally:
        reset_runtime(token)
    return list(result.get("stored") or [])
