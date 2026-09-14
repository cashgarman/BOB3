"""Bob tool SDK: write a Python function, decorate it, Bob can call it.

    from bob.tools import tool, ToolContext

    @tool
    def coin_flip(ctx: ToolContext) -> str:
        "Flip a coin and return heads or tails."
        import random
        return random.choice(["heads", "tails"])

Drop a file with tools like that into `data/tools/` and Bob loads it at start.
"""

from bob.tools.base import MAX_RESULT_CHARS, ToolContext, ToolError, ToolSpec
from bob.tools.registry import ToolRegistry, declared_tools, tool
from bob.tools.schema import spec_from_function

__all__ = [
    "MAX_RESULT_CHARS",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "ToolSpec",
    "declared_tools",
    "spec_from_function",
    "tool",
]
