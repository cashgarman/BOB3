from __future__ import annotations

from bob.tools.base import ToolContext, ToolError
from bob.tools.registry import tool


@tool
def conversation_log(limit: int = 20, *, ctx: ToolContext) -> str:
    """List recent messages in this chat with timestamps.

    Use this when the user asks when they said something, how many prompts they
    sent, or what they asked earlier in the current conversation.

    Args:
        limit: How many recent messages to return (newest last).
    """
    chat = ctx.chat
    session_id = ctx.session_id
    if chat is None or session_id is None:
        raise ToolError("conversation log is not available")
    messages = chat.list_messages(int(session_id))
    if not messages:
        return "No messages in this conversation yet."
    take = max(1, min(int(limit), 100))
    lines: list[str] = []
    for msg in messages[-take:]:
        role = "User" if msg.role == "user" else "Bob"
        text = (msg.content or "").strip().replace("\n", " ")
        if len(text) > 160:
            text = text[:157] + "..."
        lines.append(f"{msg.created_at} {role}: {text}")
    return "\n".join(lines)
