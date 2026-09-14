from __future__ import annotations

from datetime import datetime

from bob.tools.registry import tool


@tool
def get_current_time() -> str:
    """Get the current local date and time. Use this instead of guessing."""
    now = datetime.now().astimezone()
    hour = now.strftime("%I").lstrip("0") or "12"
    stamp = f"{now:%A, %B} {now.day}, {now.year} at {hour}:{now:%M} {now:%p}"
    zone = now.strftime("%Z")
    return f"{stamp} {zone}".strip()
