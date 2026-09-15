from __future__ import annotations

from ddgs import DDGS

from bob.tools.base import ToolContext, ToolError
from bob.tools.registry import tool

SEARCH_TIMEOUT = 6.0
MAX_RESULTS = 8


def _format_hit(index: int, hit: dict) -> str:
    title = (hit.get("title") or "Untitled").strip()
    body = (hit.get("body") or hit.get("snippet") or "").strip()
    href = (hit.get("href") or hit.get("link") or "").strip()
    if body and href:
        return f"{index}. {title} — {body} ({href})"
    if href:
        return f"{index}. {title} ({href})"
    if body:
        return f"{index}. {title} — {body}"
    return f"{index}. {title}"


@tool
def web_search(query: str, limit: int = 5, *, ctx: ToolContext) -> str:
    """Search the web for current information.

    Args:
        query: What to look up online.
        limit: How many results to return at most.
    """
    if ctx.cancelled:
        raise ToolError("search was cancelled")
    q = (query or "").strip()
    if not q:
        raise ToolError("a search query is required")
    count = max(1, min(int(limit), MAX_RESULTS))
    ctx.status("searching the web")
    try:
        hits = DDGS(timeout=SEARCH_TIMEOUT).text(q, max_results=count)
    except Exception as exc:
        raise ToolError(f"web search failed: {exc}") from exc
    if not hits:
        return f"No results found for {q!r}."
    lines = [_format_hit(i, hit) for i, hit in enumerate(hits, 1)]
    return "\n".join(lines)
