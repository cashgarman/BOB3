# Bob tool SDK examples

Worked examples for giving Bob new abilities. Each example is a **commented Python file** plus a **Markdown guide** covering what it teaches, how to run it, and what to copy into Bob.

Read them in order; each builds on the one before. [`SDK_REFERENCE.md`](SDK_REFERENCE.md) is the compact API for `@tool`, `ToolContext`, `ToolRegistry`, and MCP config.

| # | Code | Guide | Teaches |
|---|------|-------|---------|
| 01 | [`01_hello_tool.py`](01_hello_tool.py) | [md](01_hello_tool.md) | The `@tool` decorator, docstring-as-description, returning speech-friendly text |
| 02 | [`02_typed_arguments.py`](02_typed_arguments.py) | [md](02_typed_arguments.md) | Type hints, defaults, `Literal`, `list[...]`, `Args:` docs, argument coercion |
| 03 | [`03_using_context.py`](03_using_context.py) | [md](03_using_context.md) | `ToolContext`: `data_dir`, `settings`, `memory`, `status()`, `cancel` |
| 04 | [`04_errors_cancel_and_limits.py`](04_errors_cancel_and_limits.py) | [md](04_errors_cancel_and_limits.md) | `ToolError`, timeouts, cancellation, result clipping, dict results |
| 05 | [`05_explicit_schema.py`](05_explicit_schema.py) | [md](05_explicit_schema.md) | `@tool(name=, description=, parameters=)`, hand-written JSON Schema, `**kwargs` |
| 06 | [`06_external_api.py`](06_external_api.py) | [md](06_external_api.md) | Calling web APIs with `httpx`: timeouts, chained requests, HTTP errors |
| 07 | [`07_stateful_todo_list.py`](07_stateful_todo_list.py) | [md](07_stateful_todo_list.md) | Several tools sharing a locked JSON file under `data\` |
| 08 | [`08_mcp_server/server.py`](08_mcp_server/server.py) | [md](08_mcp_server/README.md) | An MCP server Bob connects to over stdio or Streamable HTTP |
| 09 | [`09_testing_registry.py`](09_testing_registry.py) | [md](09_testing_registry.md) | Using `ToolRegistry` and `spec_from_function` as a test library |
| 10 | [`10_speech_mood.py`](10_speech_mood.py) | [md](10_speech_mood.md) | `ctx.set_mood`, built-in `set_speech_mood`, `[mood:]` tags |
| — | [`sample_tools/`](sample_tools/README.md) | [md](sample_tools/README.md) | Drop-in plugins that *use* mood: jokes, luck, breath, whisper notes, hurry |

## Running an example

All commands are run from the repository root with the project's virtual environment. The harness, [`run_example.py`](run_example.py), loads one example the same way Bob loads `data\tools\` at boot and then lets you poke at it.

```powershell
# Show the JSON the model will see for the example's tools (default action)
.venv\Scripts\python.exe sdk_examples\run_example.py 02_typed_arguments.py

# Call one tool directly. Values are parsed as JSON when possible, else kept as strings.
.venv\Scripts\python.exe sdk_examples\run_example.py 02_typed_arguments.py --call split_bill total=84.5 people=3

# Text chat with your Ollama model, tools enabled. Tool calls are printed as they happen.
.venv\Scripts\python.exe sdk_examples\run_example.py 07_stateful_todo_list.py --chat

# Launch an MCP server over stdio and use its tools
.venv\Scripts\python.exe sdk_examples\run_example.py --mcp kitchen=sdk_examples/08_mcp_server/server.py --schema

# Connect to an MCP server that is already running over HTTP
.venv\Scripts\python.exe sdk_examples\run_example.py --mcp-url kitchen=http://127.0.0.1:8765/mcp --chat
```

Other flags:

| Flag | Effect |
|------|--------|
| `--all` | Include Bob's built-ins and `data\tools\` in `--schema` output (chat always has them) |
| `--timeout N` | Tool timeout in seconds, default `tool_timeout_sec` from `config.yaml` |
| `--memory` | Load long-term memory so `ctx.memory` works (slower start) |

### Passing JSON on PowerShell

PowerShell strips inner double quotes before Python sees them. Escape them inside a single-quoted string:

```powershell
.venv\Scripts\python.exe sdk_examples\run_example.py 04_errors_cancel_and_limits.py --call pick_from_list 'options=[\"tea\",\"coffee\"]'
.venv\Scripts\python.exe sdk_examples\run_example.py 05_explicit_schema.py --call speak_json 'payload={\"city\":\"Oslo\",\"temp\":12}'
```

Plain scalars need no quoting: `people=3`, `on=false`, `city=Seattle`. A value containing a space can be double-quoted normally: `task="buy coffee"`.

## Making Bob use a tool for real

Copy the file into `data\tools\` and restart Bob (or toggle **Tools enabled** off and on in settings). Files whose names start with `_` are ignored, which is how [`data\tools\_example.py`](../data/tools/_example.py) ships as an inert template. Everything decorated with `@tool` in the file is registered; nothing else is needed.

Two rules of thumb before you ship one:

* The tool's docstring summary is an instruction to a 7B model. "Get the current weather for a city" beats "Weather helper".
* Whatever you return is spoken aloud. One or two sentences with rounded numbers, no JSON, no lists of twenty items.

## What each example demonstrates

### 01 - Hello tool

The smallest tool is a function with a docstring and `@tool`. Two tools show that a bare word (`"heads"`) and a full sentence (`"The lucky number is 42."`) are both fine, but the sentence is repeated more reliably by small models.

### 02 - Typed arguments

`convert_temperature` uses a `Literal` for units, which becomes an `enum` so the model cannot invent "centigrade". `split_bill` mixes required and defaulted parameters of every scalar type. `shopping_total` takes `list[float]` and an optional `float | None`. Run it with `--schema` and compare the output with the source: that mapping is the whole of the schema system. Then call `shopping_total "prices=3, 4, 5"` to see the coercion layer turn a comma-separated string into a list, which is what saves you when a model sends a string for an array.

### 03 - Using the context

Tools that need Bob itself ask for `ctx: ToolContext`. The example reads live settings, keeps a favorites file under `data\`, queries long-term memory (gracefully degrading when it is offline), and shows a slow tool pushing progress to the overlay with `ctx.status()` while sleeping on `ctx.cancel.wait()` so the hotkey interrupts it instantly. The context is stripped from the schema; run `--schema` to confirm the model never sees it.

### 04 - Errors, cancellation and limits

Bob's contract is that a tool can never break a voice turn. This file triggers every failure path on purpose: `ToolError` for expected problems, an unexpected exception, a timeout (`--call count_slowly seconds=3 --timeout 1`, notice the function keeps counting after the model already got its error), a 20 000 character result that is clipped, and a dict result that is JSON-encoded.

### 05 - Explicit schema

When inference is not enough, `@tool(name=..., description=..., parameters=...)` takes over. `home_scene` uses `enum`, `minItems`, `minimum`/`maximum` and a nested array that type hints cannot express, and receives the model's arguments through `**kwargs`. `speak_json` accepts a free-form object. The `Args:` docstring descriptions are still harvested even when `description=` replaces the summary.

### 06 - External API

Real network calls with `httpx`, which Bob already depends on. `current_weather` chains a geocoding request into a forecast request, checks `ctx.cancelled` between them, and turns every HTTP failure mode into a sentence. Both APIs are free and keyless, so this runs unmodified: `--call current_weather city=Seattle`.

### 07 - Stateful to-do list

A feature is usually several small tools rather than one tool with a `mode` parameter. Four tools share a JSON file guarded by a `threading.Lock`, because Bob runs tools on a thread pool. `todo_done` accepts either a position or words from the task, and the list is capped at seven spoken items. This is the best example to try with `--chat`: say "add buy coffee to my list", "what's on my list", "the coffee one is done".

### 08 - MCP server

For tools that live in another process or language. The server uses the official `mcp` package with the same decorator style; [08_mcp_server/README.md](08_mcp_server/README.md) has the `config.yaml` entries for both transports. Its tools appear to the model as `kitchen_start_timer` and so on, since the server id becomes a prefix. Note that MCP servers pass the whole docstring through as the description, `Args:` section included, so keep it short.

### 09 - Testing with ToolRegistry

How to assert on a tool from a script: `spec_from_function`, a clean `ToolRegistry` with no built-ins, a fake `ctx.memory`, and a temp `data_dir`. Run the file itself (`python sdk_examples/09_testing_registry.py`); it is not a plugin.

### 10 - Speech mood

`ctx.set_mood("excited")` colours Kokoro for the rest of the turn (rate, pitch, loudness, pauses). The same mood can come from the built-in `set_speech_mood` tool or a leading `[mood:excited]` tag, which Bob strips so it is never spoken.

## Where things live

```
sdk_examples/
  README.md                   this file
  SDK_REFERENCE.md            API reference
  run_example.py              harness: --schema / --call / --chat
  01_hello_tool.py + .md ...  07_*.py + .md
  08_mcp_server/              MCP server example + README
  09_testing_registry.py + .md
  10_speech_mood.py + .md
bob/tools/                    the SDK itself (base.py, schema.py, registry.py, mcp_hub.py)
bob/tools/builtin/            Bob's own tools, written with the same SDK
data/tools/                   your tools; loaded at boot
```
