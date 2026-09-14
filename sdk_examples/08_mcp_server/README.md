# Example 08 — MCP server

**File:** [`server.py`](server.py)

When a tool should not run inside Bob's process, expose it as an [MCP](https://modelcontextprotocol.io) server. Bob already depends on the official `mcp` Python package and speaks both **stdio** and **Streamable HTTP**.

## When to use MCP instead of the SDK

Use the SDK (`@tool` in `data/tools/`) if the tool is a few functions of Python that can share Bob's venv.

Reach for MCP when the tool:

- is written in another language, or already exists as an MCP server you can launch,
- needs its own dependencies or Python version,
- should keep running (and keep state) even if Bob restarts — use HTTP for that.

To the model the two sources are identical. Only the name is prefixed with the server id: `start_timer` on a server whose `id` is `kitchen` is offered as `kitchen_start_timer`.

## What this server provides

| MCP name | Bob's name (id=`kitchen`) | Does |
|---|---|---|
| `start_timer` | `kitchen_start_timer` | Start a named countdown. |
| `check_timers` | `kitchen_check_timers` | Report remaining time on every timer. |
| `unit_convert` | `kitchen_unit_convert` | Convert cooking volumes (`ml`, `l`, `cups`, `tbsp`, `tsp`, `floz`). |

State is an in-memory dict with a lock. On **stdio**, Bob launches the process and kills it on quit, so timers die with Bob. On **HTTP**, you start the server yourself and timers survive Bob restarts.

The decorator style is close to Bob's SDK: type hints and docstrings become the schema. One difference: MCP passes the **whole** docstring through as the description, `Args:` included, so keep it short.

## Try it without the voice loop

```powershell
# Launch the server as a stdio subprocess and inspect / call its tools
.venv\Scripts\python.exe sdk_examples\run_example.py --mcp kitchen=sdk_examples/08_mcp_server/server.py --schema

.venv\Scripts\python.exe sdk_examples\run_example.py --mcp kitchen=sdk_examples/08_mcp_server/server.py --call kitchen_unit_convert amount=2 unit_from=cups unit_to=ml

.venv\Scripts\python.exe sdk_examples\run_example.py --mcp kitchen=sdk_examples/08_mcp_server/server.py --call kitchen_start_timer name=pasta minutes=8
.venv\Scripts\python.exe sdk_examples\run_example.py --mcp kitchen=sdk_examples/08_mcp_server/server.py --call kitchen_check_timers
```

Each `--mcp` invocation is a **new** process, so a timer started in one command is not visible to the next. Use `--chat` (one process) or the HTTP transport for that.

### Streamable HTTP

In one terminal:

```powershell
.venv\Scripts\python.exe sdk_examples\08_mcp_server\server.py --http
```

In another:

```powershell
.venv\Scripts\python.exe sdk_examples\run_example.py --mcp-url kitchen=http://127.0.0.1:8765/mcp --call kitchen_start_timer name=pasta minutes=8
.venv\Scripts\python.exe sdk_examples\run_example.py --mcp-url kitchen=http://127.0.0.1:8765/mcp --call kitchen_check_timers
```

## Install it in Bob

Edit [`config.yaml`](../../config.yaml). Use the **full path** to this repo's Python and to `server.py`.

**stdio** (Bob launches and kills the server):

```yaml
mcp_servers:
  - id: kitchen
    enabled: true
    command: C:/Users/you/BOB3/.venv/Scripts/python.exe
    args: ["C:/Users/you/BOB3/sdk_examples/08_mcp_server/server.py"]
```

**HTTP** (you start `server.py --http` yourself):

```yaml
mcp_servers:
  - id: kitchen
    enabled: true
    url: http://127.0.0.1:8765/mcp
```

Optional keys on a stdio server: `env` (dict of extra environment variables) and `cwd`. Set `enabled: false` to keep the entry without connecting.

A server that fails to start is skipped. `.\run.ps1 --check` prints `tools: WARN mcp kitchen: …` and Bob still boots.

## Next

[09_testing_registry.md](../09_testing_registry.md) — driving the SDK from a script, without Bob and without the harness.
