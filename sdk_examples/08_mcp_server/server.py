"""Example 08 - A custom MCP server Bob can connect to.

When to use MCP instead of the SDK
----------------------------------
The SDK (`@tool`) is simpler and runs inside Bob's process. Reach for an MCP
server when the tool:

* is written in another language or already exists as an MCP server,
* needs its own dependencies or Python version, or
* should keep running (and keep state) independently of Bob.

This file uses the official `mcp` package that Bob already depends on. The
decorator style is intentionally close to Bob's SDK: type hints and docstrings
become the schema here too.

Running it
----------
Two transports are supported. **stdio** lets Bob launch the server itself:

    # config.yaml
    mcp_servers:
      - id: kitchen
        enabled: true
        command: C:/Users/you/BOB3/.venv/Scripts/python.exe
        args: ["C:/Users/you/BOB3/sdk_examples/08_mcp_server/server.py"]

**Streamable HTTP** lets a server you started separately be shared:

    .venv\\Scripts\\python.exe sdk_examples\\08_mcp_server\\server.py --http

    # config.yaml
    mcp_servers:
      - id: kitchen
        enabled: true
        url: http://127.0.0.1:8765/mcp

In both cases the tools appear to the model as `kitchen_start_timer`,
`kitchen_check_timers`, and `kitchen_unit_convert`: the server id becomes a
prefix so two servers can expose the same tool name without colliding.

Try it without Bob's voice loop:

    .venv\\Scripts\\python.exe sdk_examples\\run_example.py --mcp kitchen=sdk_examples/08_mcp_server/server.py --call kitchen_unit_convert amount=2 unit_from=cups unit_to=ml
"""

from __future__ import annotations

import sys
import threading
import time

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# `instructions` is sent to clients on connect; Bob does not currently inject
# it into the prompt, so keep the guidance in each tool's docstring as well.
mcp = MCPServer("Kitchen", instructions="Kitchen timers and unit conversion.")

# Server-side state. Because the server is its own process, timers keep
# running even if Bob restarts (for the HTTP transport).
_timers: dict[str, float] = {}
_lock = threading.Lock()

_TO_ML = {"ml": 1.0, "l": 1000.0, "cups": 236.588, "tbsp": 14.787, "tsp": 4.929, "floz": 29.574}


@mcp.tool()
def start_timer(name: str, minutes: float) -> str:
    """Start a named kitchen timer.

    Args:
        name: What the timer is for, for example "pasta".
        minutes: How long the timer should run.
    """
    if minutes <= 0:
        # MCP's ToolError, like Bob's, becomes an error result the model reads.
        raise ToolError("the timer needs a positive number of minutes")
    with _lock:
        _timers[name.strip().lower()] = time.monotonic() + minutes * 60
    return f"Started a {minutes:g} minute timer for {name}."


@mcp.tool()
def check_timers() -> str:
    """Report how much time is left on every running kitchen timer."""
    now = time.monotonic()
    with _lock:
        if not _timers:
            return "No timers are running."
        parts = []
        for name, ends_at in sorted(_timers.items()):
            remaining = ends_at - now
            if remaining <= 0:
                parts.append(f"the {name} timer is finished")
            else:
                parts.append(f"{name} has {max(1, round(remaining / 60))} minutes left")
        # Forget timers that finished more than ten minutes ago.
        for name in [n for n, t in _timers.items() if now - t > 600]:
            _timers.pop(name, None)
    return "; ".join(parts).capitalize() + "."


@mcp.tool()
def unit_convert(amount: float, unit_from: str, unit_to: str) -> str:
    """Convert cooking volumes between ml, l, cups, tbsp, tsp, and floz.

    Args:
        amount: The quantity to convert.
        unit_from: The unit you have.
        unit_to: The unit you want.
    """
    source = unit_from.strip().lower()
    target = unit_to.strip().lower()
    if source not in _TO_ML or target not in _TO_ML:
        raise ToolError(f"I can convert between {', '.join(_TO_ML)} only")
    result = amount * _TO_ML[source] / _TO_ML[target]
    return f"{amount:g} {source} is about {result:.2f} {target}."


if __name__ == "__main__":
    # `mcp.run()` blocks. stdio is the default and is what Bob uses when the
    # config has a `command`. `--http` serves Streamable HTTP on port 8765.
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http", port=8765)
    else:
        mcp.run()
