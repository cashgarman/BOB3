# Bob tool SDK reference

This is the compact API for everything under `bob.tools`. The numbered files in this folder are worked examples of the same surface.

Public import:

```python
from bob.tools import (
    tool,               # decorator that registers a function as a tool
    ToolContext,        # injected at call time; never shown to the model
    ToolError,          # raise this for expected failures
    ToolRegistry,       # loads, lists, and invokes tools
    ToolSpec,           # one registered tool (name, schema, runner)
    spec_from_function, # build a ToolSpec without registering it
    declared_tools,     # every ToolSpec created by @tool since last load()
    MAX_RESULT_CHARS,   # 8000; longer returns are clipped
)
```

## How a tool reaches the model

1. You write a Python function and decorate it with `@tool`.
2. On boot (or in the harness), `ToolRegistry.load()` imports built-ins, then every `data/tools/*.py` that does not start with `_`.
3. Each function becomes a JSON Schema tool definition and is sent to Ollama on every voice turn.
4. If the model replies with `tool_calls`, Bob runs `registry.invoke(...)` and feeds the text result back.
5. After at most `max_tool_rounds` rounds, the model has to answer in words. That answer is what is spoken.

SDK tools and MCP tools look identical to the model. Only `ToolSpec.source` (`sdk` vs `mcp:<server_id>`) tells them apart.

## `@tool`

```python
@tool
def coin_flip() -> str:
    """Flip a coin. Use it whenever the user asks for a coin toss."""
    ...

@tool(name="home_set_light", description="Turn a room light on or off.")
def set_light(room: str, on: bool = True) -> str:
    ...

@tool(parameters={...})  # raw JSON Schema, skip type-hint inference
def apply_scene(**arguments) -> str:
    ...
```

| Keyword | Default | Effect |
|---|---|---|
| `name` | the function name | Identifier the model calls. Only `A-Za-z0-9_-` survive; other characters become `_`. |
| `description` | first paragraph of the docstring | Instruction the model reads when deciding whether to call the tool. |
| `parameters` | inferred from type hints | JSON Schema object (`type`, `properties`, `required`). Passed to the model as-is when you supply it. |

The decorator both **registers** the function (so `ToolRegistry.load()` can find it) and leaves it callable as ordinary Python.

### Schema inference

Type hints become JSON types:

| Hint | Schema |
|---|---|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list[T]` / `set` / `tuple` | `"array"` of `T` |
| `dict` | `"object"` |
| `Literal["a", "b"]` | `"enum": ["a", "b"]` |
| `T \| None` | schema of `T`, and the argument is not required |
| untyped | `"string"` |

Defaults make a parameter optional and are copied into the schema as `"default"`. A Google-style `Args:` block supplies per-parameter descriptions:

```python
def split_bill(total: float, people: int = 2) -> str:
    """Split a restaurant bill.

    Args:
        total: The bill amount before tip.
        people: How many people are sharing.
    """
```

`Args:`, `Arguments:`, and `Parameters:` all work. `Returns:` / `Raises:` / `Notes:` / `Examples:` stop the harvest so they do not leak into argument docs.

### Argument coercion

Models often send strings. Before your function runs, Bob converts:

- `"3"` → `int` / `float`
- `"true"` / `"yes"` / `"1"` / `"on"` → `bool`
- `"[1, 2]"` or `"1, 2"` → `list`
- a JSON object string → `dict`

Missing required arguments raise `ToolError("missing required argument '...'")`.

### `ToolContext` injection

A parameter is treated as the context (and **stripped from the schema**) when:

- its annotation is `ToolContext` (including `ToolContext | None`), or
- it is untyped and named `ctx` or `context`.

Put it last and keyword-only so it never collides with model arguments:

```python
def notes_write(text: str, append: bool = True, *, ctx: ToolContext) -> str:
    ...
```

## `ToolContext`

Injected at call time. The model cannot see or set any of these fields.

| Field | Type | Purpose |
|---|---|---|
| `ctx.data_dir` | `Path` | Bob's `data/` folder. Store tool files here, never arbitrary disk paths. |
| `ctx.settings` | `Settings` or `None` | Live settings (`llm_model`, `tts_voice`, `hotkey`, ...). |
| `ctx.memory` | `MemoryService` or `None` | Long-term memory. Check `ctx.memory.ready` before calling `retrieve`. |
| `ctx.status(msg)` | `Callable[[str], None]` | Short overlay text while a long tool runs. |
| `ctx.set_mood(name)` | method | Colour this turn's spoken reply. See [Speech moods](#speech-moods). |
| `ctx.mood` | `str` | Canonical mood currently in effect (`neutral` if unset). |
| `ctx.cancel` | `threading.Event` | Set when the user cancels the turn (hotkey). Prefer `ctx.cancel.wait(seconds)` over `time.sleep`. |
| `ctx.cancelled` | `bool` | Shortcut for `ctx.cancel.is_set()`. |

## `ToolError`

Raise this for problems you expect (bad arguments, nothing found, a remote API 404). The registry turns it into a tool result the model can read:

```
Error: tool 'open_url' failed: only full http:// or https:// addresses can be opened
```

Any other exception is caught the same way, with a less tidy message. Prefer `ToolError` for text you wrote for the model.

A tool **must not** raise out of the voice turn. `registry.invoke()` always returns a string.

## `ToolRegistry`

```python
registry = ToolRegistry(data_dir, settings=settings, memory=memory)
registry.load()                              # built-ins + data/tools/*.py
registry.load_mcp(settings.mcp_servers)      # optional MCP servers
registry.schemas()                           # list of Ollama tool objects
registry.invoke("coin_flip", {}, ctx=ctx, timeout=20)
registry.close()                             # stop MCP subprocesses and the worker pool
```

| Method | Role |
|---|---|
| `load()` | Re-import built-ins and `data/tools/*.py`. Clears previously declared SDK tools first, so a deleted plugin disappears. Files starting with `_` are skipped. |
| `load_mcp(servers, timeout=)` | Connect enabled MCP servers and register their tools as `serverid_toolname`. Failed servers are skipped; look at `registry.errors`. |
| `add(spec)` | Register one `ToolSpec`. SDK tools win over MCP tools of the same name. |
| `names()` / `specs()` / `schemas()` | Inventory. `schemas()` is what Ollama receives. |
| `context(cancel=, status=)` | Build a `ToolContext` wired to this registry's settings, memory, and `data_dir`. |
| `invoke(name, arguments, ctx=, timeout=)` | Run a tool. Always returns a string. Times out after `timeout` seconds (minimum 1). Results longer than `MAX_RESULT_CHARS` are clipped. |
| `close_mcp()` / `close()` | Tear down MCP sessions and the worker thread pool. |

Duplicate names: later SDK modules overwrite earlier ones. An MCP tool whose name collides with an SDK tool is skipped and logged.

## `spec_from_function` and `declared_tools`

Use these when you want a `ToolSpec` without going through the decorator's global registry, typically in tests:

```python
from bob.tools import spec_from_function, ToolRegistry

spec = spec_from_function(my_function, name="demo_ping")
registry = ToolRegistry(data_dir)
registry.add(spec)
```

`declared_tools()` returns every spec `@tool` has created since the last `registry.load()` (which clears the table before re-importing).

## `ToolSpec`

| Field | Meaning |
|---|---|
| `name` | Sanitized identifier. |
| `description` | Model-facing instruction. |
| `parameters` | JSON Schema object. |
| `run(arguments, ctx)` | The wrapper that injects context, coerces args, and calls your function. |
| `source` | `"sdk"` or `"mcp:<server_id>"`. |
| `schema()` | Ollama payload: `{"type": "function", "function": {...}}`. |

## Return values

Whatever you return is turned into text for the model:

| You return | The model sees |
|---|---|
| `str` | the string, stripped |
| `None` / empty | `"done"` |
| `dict` / `list` | JSON |
| anything else | `str(value)` |
| more than 8000 characters | first 8000 plus ` … (truncated)` |

Write for the ear. One or two sentences with rounded numbers beat JSON, markdown, and lists of twenty items.

## Timeouts, cancel, and threads

- Tools run on a 4-worker thread pool, so they never freeze capture or playback.
- Each call is capped by `tool_timeout_sec` (default 20). On timeout the model already has an error; your function keeps running until it returns, so check `ctx.cancelled` in loops.
- The listen hotkey sets `ctx.cancel`. `ctx.cancel.wait(1)` sleeps up to one second but wakes immediately on cancel.
- Shared files need a `threading.Lock`. The model can fire several tools in one round.

## MCP servers

Configured in `config.yaml`, not the settings dialog:

```yaml
mcp_servers:
  - id: kitchen
    enabled: true
    command: C:/path/to/.venv/Scripts/python.exe
    args: ["C:/path/to/sdk_examples/08_mcp_server/server.py"]
    # optional: env: {KEY: value}, cwd: C:/path
  - id: remote
    enabled: true
    url: http://127.0.0.1:8765/mcp
```

- `command` + `args` → stdio subprocess Bob launches and kills on quit.
- `url` → Streamable HTTP to a server you started yourself.
- Tool names are prefixed with the sanitized `id`: `start_timer` on server `kitchen` is `kitchen_start_timer`.
- Set `enabled: false` to keep the entry without connecting.

See [08_mcp_server](08_mcp_server/README.md).

## Loading rules for `data/tools/`

| File | Loaded? |
|---|---|
| `data/tools/dice.py` | yes |
| `data/tools/_example.py` | no (`_` prefix) |
| `data/tools/helpers.py` | yes, if it exists; only `@tool` functions become tools |
| anything else | ignored |

A plugin that fails to import is skipped; the error is stored on `registry.errors` and printed by `python -m bob --check`. Other tools still load.

## Settings that affect tools

| Setting | Default | Role |
|---|---|---|
| `tools_enabled` | `true` | Master switch. Off means the model is not offered any tools. |
| `tool_timeout_sec` | `20` | Per-call budget. |
| `max_tool_rounds` | `4` | How many tool-calling rounds one turn may take. |
| `mcp_servers` | `[]` | List of MCP server dicts, edited in `config.yaml`. |
| `tts_mood` | `neutral` | Default spoken delivery. A tool can override it for one turn. |

## Speech moods

Kokoro has no emotion input. A mood is a named bundle of speaking rate, pitch, loudness, and pause length applied on top of the user's voice and `tts_speed`. Canonical names:

`neutral`, `calm`, `warm`, `upbeat`, `excited`, `serious`, `sad`, `sorry`, `whisper`, `hurried`

Three ways to set it, all equivalent by the time TTS runs:

1. **SDK:** `ctx.set_mood("excited")` inside any tool. Unknown names raise `ToolError`.
2. **Built-in tool:** the model calls `set_speech_mood` before it answers.
3. **Reply tag:** the spoken text may start with `[mood:excited]`. Bob strips the tag (it is never spoken or stored) and applies the mood. Incomplete tags are held until the `]` arrives so they cannot leak into TTS.

The mood lasts until the turn ends, then Bob returns to `tts_mood`. Helpers: `from bob.tools import list_moods, parse_mood, resolve_mood`.

## Built-in tools (same SDK)

| Name | Module | Does |
|---|---|---|
| `get_current_time` | `bob.tools.builtin.clock` | Local date and time |
| `open_url` | `bob.tools.builtin.web` | Default browser, `http`/`https` only |
| `notes_read` / `notes_write` | `bob.tools.builtin.notes` | `data/notes.md`, capped at 20 000 characters |
| `memory_search` | `bob.tools.builtin.recall` | On-demand long-term memory |
| `set_speech_mood` / `list_speech_moods` | `bob.tools.builtin.mood` | Colour the spoken reply for this turn |

They are ordinary `@tool` functions. Read them after the examples if you want to see the same patterns in production code. Speech mood is walked through in [`10_speech_mood.md`](10_speech_mood.md).
