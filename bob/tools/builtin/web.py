from __future__ import annotations

import webbrowser
from urllib.parse import urlparse

from bob.tools.base import ToolError
from bob.tools.registry import tool


@tool
def open_url(url: str) -> str:
    """Open a web page in the user's default browser.

    Args:
        url: Full http or https address, for example https://example.com.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("only full http:// or https:// addresses can be opened")
    if not webbrowser.open(parsed.geturl(), new=2):
        raise ToolError("no browser was available to open the page")
    return f"Opened {parsed.netloc} in the browser."
