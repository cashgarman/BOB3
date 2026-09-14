from __future__ import annotations

from bob.tools.base import ToolContext, ToolError
from bob.tools.registry import tool


@tool
def memory_search(query: str, limit: int = 5, *, ctx: ToolContext) -> str:
    """Search what Bob remembers about the user.

    Args:
        query: What to look for, such as a person, place, or preference.
        limit: How many stored facts to return at most.
    """
    memory = ctx.memory
    if memory is None or not getattr(memory, "ready", False):
        raise ToolError("long-term memory is not available")
    found = memory.retrieve(query, limit=max(1, min(int(limit), 20)))
    return found or f"Nothing stored about {query!r}."
