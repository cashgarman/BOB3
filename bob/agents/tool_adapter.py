from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool

from bob.tools.base import ToolSpec

WRITE_TOOLS = frozenset({"notes_write", "write_file", "edit_file"})


def spec_to_langchain_tool(
    spec: ToolSpec,
    invoke: Callable[[str, Any], str],
) -> StructuredTool:
    """Expose a BOB ToolSpec as a LangChain tool. The registry still executes it."""

    def _run(arguments: dict | None = None) -> str:
        return invoke(spec.name, arguments or {})

    _run.__name__ = spec.name
    _run.__doc__ = spec.description or spec.name
    return StructuredTool.from_function(
        func=_run,
        name=spec.name,
        description=spec.description or spec.name,
    )


def registry_to_langchain_tools(
    registry: Any,
    invoke: Callable[[str, Any], str] | None = None,
) -> list[StructuredTool]:
    if registry is None:
        return []
    runner = invoke or registry.invoke
    return [spec_to_langchain_tool(spec, runner) for spec in registry.specs()]


def is_write_tool(name: str) -> bool:
    return str(name or "").strip().lower() in WRITE_TOOLS
