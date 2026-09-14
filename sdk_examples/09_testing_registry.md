# Example 09 — Testing tools with `ToolRegistry`

**File:** [`09_testing_registry.py`](09_testing_registry.py)

How to exercise a tool from a script or unit test **without** Bob, Ollama, or the example harness. The file is both the lesson and a small assertion suite.

## What you learn

- `spec_from_function(fn)` builds a `ToolSpec` without touching the process-global `@tool` table. That is what you want in tests: no leftover tools from other modules.
- `ToolRegistry.add(spec)` publishes it. Skip `registry.load()` unless you *want* built-ins and `data/tools/`.
- `registry.context(cancel=, status=)` lets you pass a `threading.Event` you control and a `status` callback that records overlay messages.
- `registry.invoke(...)` always returns a string. Assert on that string — including the `Error: …` paths.
- Swap `ctx.memory` for a tiny fake that implements `ready` and `retrieve`. You do not need LanceDB in unit tests.
- Use a `tempfile.TemporaryDirectory` as `data_dir` so tests never write into Bob's real `data/`.

Do **not** copy this file into `data/tools/`. It is not a plugin.

## Run it

```powershell
.venv\Scripts\python.exe sdk_examples\09_testing_registry.py
```

Expected ending: `all checks passed`.

The same file can be driven through the harness if you only want to inspect schemas:

```powershell
.venv\Scripts\python.exe sdk_examples\run_example.py 09_testing_registry.py --schema
```

(`memory_blurb` is the only `@tool`-decorated function in the file, so it is the only one the harness will list. `ping` and `greet` are registered only when you run the file as a script.)

## Pattern to copy

```python
from bob.tools import ToolRegistry, spec_from_function

registry = ToolRegistry(tmp_path)
registry.add(spec_from_function(my_tool))
ctx = registry.context()
assert "pong" in registry.invoke("ping", {}, ctx)
registry.close()
```

That is the whole test surface. See [SDK_REFERENCE.md](SDK_REFERENCE.md) for `invoke` return-value rules, coercion, and timeouts.

## Back to the index

[README.md](README.md)
