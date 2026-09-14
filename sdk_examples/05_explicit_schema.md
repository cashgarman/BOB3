# Example 05 — Explicit schema

**File:** [`05_explicit_schema.py`](05_explicit_schema.py)

When type-hint inference is not enough, pass `name`, `description`, and `parameters` to `@tool`.

## What you learn

```python
@tool(name="home_set_light", description="Turn a room's light on or off.")
def set_light(room: str, on: bool = True, brightness: int = 100) -> str:
    ...
```

| Keyword | When to use it |
|---|---|
| `name=` | The Python name is awkward, or you want a namespace (`home_set_light`). Only `A-Za-z0-9_-` survive. |
| `description=` | The docstring is for developers and you want a different instruction for the model. `Args:` is still harvested. |
| `parameters=` | Nested objects, `enum`, `minItems`, `minimum`/`maximum`, `additionalProperties`, `oneOf`. Bob does **not** rewrite a schema you supply. |

With `parameters=` the model's arguments often arrive through `**kwargs`. Validate them yourself — the schema is a hint to the model, not a guarantee, especially with small local models.

## The tools

| Name | Pattern |
|---|---|
| `home_set_light` | `name=` + `description=` override; arguments still inferred from type hints. In-memory stub of a smart-home light. |
| `home_scene` | Full JSON Schema: `enum`, nested array with `minItems`, integer with `minimum`/`maximum`. Body is `**arguments`. |
| `home_status` | Explicit metadata **and** an injected `ctx`. Confirms `ctx` is still stripped from the schema. |
| `speak_json` | A free-form `object` with `additionalProperties: true`, which type hints cannot express. |

## Run it

```powershell
.venv\Scripts\python.exe sdk_examples\run_example.py 05_explicit_schema.py --schema

.venv\Scripts\python.exe sdk_examples\run_example.py 05_explicit_schema.py --call home_set_light room=kitchen brightness=40

.venv\Scripts\python.exe sdk_examples\run_example.py 05_explicit_schema.py --call home_scene 'scene=movie' 'rooms=[\"living room\",\"kitchen\"]' transition_seconds=3

.venv\Scripts\python.exe sdk_examples\run_example.py 05_explicit_schema.py --call home_status

.venv\Scripts\python.exe sdk_examples\run_example.py 05_explicit_schema.py --call speak_json 'payload={\"city\":\"Oslo\",\"temp\":12}'
```

`home_status` only knows about lights set **in this process**. Restarting the harness (or Bob) clears the in-memory dict. Example 07 shows how to persist state to disk instead.

## Next

[06_external_api.md](06_external_api.md) — real HTTP calls with timeouts and cancellation.
