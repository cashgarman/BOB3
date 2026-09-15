from __future__ import annotations

from typing import Any

from bob.agents.state import Route, TurnState, get_runtime
from bob.llm import (
    _fresh_web_search,
    _is_web_search_followup,
    _try_direct_answer,
    needs_agentic_tools,
    needs_calendar_context,
    needs_chat_context,
    needs_conversation_log,
    needs_current_time,
)


def choose_route(
    user_text: str,
    *,
    thinks: bool,
    has_tools: bool,
    tools_unsupported: bool,
    history: list[dict[str, Any]] | None = None,
) -> tuple[Route, str]:
    """Heuristic router. LLM routing is reserved for ambiguous agentic turns."""
    if tools_unsupported:
        has_tools = False
    if needs_calendar_context(user_text) and has_tools:
        return "tools", "calendar"
    if needs_current_time(user_text) and has_tools:
        return "direct", "time"
    if _fresh_web_search(user_text) and has_tools:
        return "tools", "web"
    if _is_web_search_followup(user_text, history or []) and has_tools:
        return "tools", "web_followup"
    if _try_direct_answer(user_text):
        return "direct", "shortcut"
    if needs_chat_context(user_text):
        return "speak", "chitchat"
    if has_tools and thinks and not needs_agentic_tools(user_text):
        return "speak", "chitchat"
    if needs_conversation_log(user_text) and has_tools:
        return "memory", "conversation"
    if has_tools and (needs_agentic_tools(user_text) or not thinks):
        return "tools", "react"
    return "speak", "chitchat"


def orchestrator_node(state: TurnState) -> dict[str, Any]:
    runtime = get_runtime()
    llm = runtime.llm
    user_text = str(state.get("user_text") or "")
    has_tools = bool(runtime.tools) and runtime.on_tool is not None and not llm._tools_unsupported
    thinks = llm._thinks()
    route, kind = choose_route(
        user_text,
        thinks=thinks,
        has_tools=has_tools,
        tools_unsupported=bool(llm._tools_unsupported),
        history=llm.history,
    )
    llm._append_internal_thought(
        f"Route: {route} ({kind}).",
        runtime.on_thought,
    )
    return {"route": route, "route_kind": kind}
