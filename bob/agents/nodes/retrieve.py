from __future__ import annotations

from typing import Any

from bob.agents.state import TurnState, get_runtime
from bob.llm import (
    _user_wants_bullets,
    needs_chat_context,
    needs_conversation_log,
    needs_current_time,
    needs_prompt_files,
)


def retrieve_node(state: TurnState) -> dict[str, Any]:
    """Load long-term + session memory, then optional tool prefetch."""
    runtime = get_runtime()
    llm = runtime.llm
    user_text = str(state.get("user_text") or "")
    if not llm.history or llm.history[-1].get("role") != "user" or str(llm.history[-1].get("content") or "") != user_text:
        llm.history.append({"role": "user", "content": user_text})
    llm._trim()
    fast_prompt = needs_prompt_files(user_text, llm.history)
    if not fast_prompt:
        llm._manage_context()

    memory_block = str(state.get("memory_block") or "")
    if not memory_block.strip() and not fast_prompt:
        memory_block = _retrieve_memory(runtime, user_text)
    if not fast_prompt:
        memory_block = _prefetch_tool_context(runtime, user_text, memory_block)
    return {"memory_block": memory_block}


def _retrieve_memory(runtime: Any, user_text: str) -> str:
    parts: list[str] = []
    memory = runtime.memory
    if memory is not None:
        try:
            block = memory.retrieve(user_text, limit=int(runtime.memory_max_inject))
        except Exception:
            block = ""
        if block:
            parts.append(str(block).strip())
    session_memory = runtime.session_memory
    if runtime.session_rag_enabled and session_memory is not None and getattr(session_memory, "ready", False):
        try:
            session_block = session_memory.retrieve(
                runtime.session_id,
                user_text,
                limit=int(runtime.session_rag_max_inject),
            )
        except Exception:
            session_block = ""
        if session_block:
            parts.insert(0, str(session_block).strip())
    return "\n\n".join(p for p in parts if p)


def _prefetch_tool_context(runtime: Any, user_text: str, memory_block: str) -> str:
    registry = runtime.registry
    if not runtime.tools_enabled or registry is None or runtime.on_tool is None:
        return memory_block
    names = set(registry.names()) if hasattr(registry, "names") else set()
    blocks: list[str] = []
    if (needs_conversation_log(user_text) or needs_chat_context(user_text)) and "conversation_log" in names:
        log_text = runtime.on_tool("conversation_log", {"limit": 40})
        blocks.append(f"Conversation log (for this chat):\n{log_text}")
    if needs_current_time(user_text) and "get_current_time" in names:
        now = runtime.on_tool("get_current_time", {})
        blocks.append(f"Current local time: {now}")
    if needs_chat_context(user_text) and not needs_conversation_log(user_text):
        if "summarize_for_speech" in names and "conversation_log" in names:
            log_text = runtime.on_tool("conversation_log", {"limit": 20})
            style = "bullets" if _user_wants_bullets(user_text) else "brief"
            summary = runtime.on_tool(
                "summarize_for_speech",
                {"text": log_text, "question": user_text, "style": style},
            )
            if summary and not str(summary).startswith("Error"):
                blocks.append(f"Conversation summary:\n{summary}")
    if not blocks:
        return memory_block
    block = "\n\n".join(blocks)
    if memory_block.strip():
        return f"{block}\n\n{memory_block.strip()}"
    return block
