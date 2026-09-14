# Example 03 — Using `ToolContext`

**File:** [`03_using_context.py`](03_using_context.py)

How a tool reaches Bob itself: settings, the `data/` folder, long-term memory, overlay status, and the cancel event.

## What you learn

- Annotate a parameter `ToolContext` and Bob injects it. The model never sees it in the schema and cannot pass or overwrite it.
- Put `ctx` last and keyword-only (`*, ctx: ToolContext`) so it cannot collide with a model argument of the same name.
- Treat `ctx.settings` and `ctx.memory` as optional. Memory can fail to load; Bob still runs.
- Keep files you write under `ctx.data_dir`. That is the folder Bob owns.
- `ctx.status("…")` updates the overlay during a slow tool.
- `ctx.cancel.wait(seconds)` sleeps but wakes immediately when the user hits the hotkey.

## The tools

| Name | Uses |
|---|---|
| `describe_setup` | `ctx.settings` — live model, voice, wake word, hotkey. |
| `remember_favorite` / `recall_favorite` | `ctx.data_dir / "favorites.json"` — tiny persistent store. |
| `what_does_bob_know` | `ctx.memory.retrieve(...)`, with a graceful fallback when memory is offline. |
| `slow_report` | `ctx.status` + `ctx.cancel.wait` + `ctx.cancelled`. |

Run `--schema` and confirm none of the schemas list a `ctx` property.

## Run it

```powershell
.venv\Scripts\python.exe sdk_examples\run_example.py 03_using_context.py --schema

.venv\Scripts\python.exe sdk_examples\run_example.py 03_using_context.py --call describe_setup

.venv\Scripts\python.exe sdk_examples\run_example.py 03_using_context.py --call remember_favorite thing=color value=green

.venv\Scripts\python.exe sdk_examples\run_example.py 03_using_context.py --call recall_favorite thing=color

# Loads the LanceDB + Kuzu memory store so ctx.memory.ready is True
.venv\Scripts\python.exe sdk_examples\run_example.py 03_using_context.py --memory --call what_does_bob_know topic=user
```

`remember_favorite` writes `data/favorites.json`. That file is safe to delete.

## Field cheat sheet

See [SDK_REFERENCE.md](SDK_REFERENCE.md#toolcontext) for the full table. The ones this file exercises:

```python
ctx.data_dir    # Path("…/data")
ctx.settings    # Settings dataclass, or None
ctx.memory      # MemoryService, or None
ctx.status(msg) # overlay line
ctx.cancel      # threading.Event
ctx.cancelled   # bool
```

## Next

[04_errors_cancel_and_limits.md](04_errors_cancel_and_limits.md) — every failure path, on purpose.
