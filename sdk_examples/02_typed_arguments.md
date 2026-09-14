# Example 02 — Typed arguments

**File:** [`02_typed_arguments.py`](02_typed_arguments.py)

How Bob turns type hints, defaults, and a Google-style `Args:` block into the JSON Schema the model sees — and how it coerces the strings a model typically sends.

## What you learn

1. **Type hints** decide the JSON type (`str`, `int`, `float`, `bool`, `list[T]`, `Literal`, `T | None`).
2. **Defaults** make a parameter optional and show up as `"default"` in the schema.
3. **`Args:`** supplies the per-parameter descriptions. On a 7B model those descriptions matter more than the summary.
4. **Coercion** saves you when the model sends `"3"` for an `int` or `"3, 4, 5"` for a `list[float]`.
5. **`ToolError`** is the right way to reject bad input without crashing the turn.

## The tools

| Name | Interesting types |
|---|---|
| `convert_temperature` | `Literal["celsius", "fahrenheit", "kelvin"]` becomes an `enum`, so the model cannot invent `"centigrade"`. `unit_to` defaults to `"celsius"`. |
| `split_bill` | required `float`, defaulted `int` / `float` / `bool`. Validates `people >= 1`. |
| `shopping_total` | `list[float]` and `float | None`. Omitting `tax_percent` is allowed. |

The schema Bob produces for `convert_temperature` looks like this (abbreviated):

```json
{
  "name": "convert_temperature",
  "parameters": {
    "type": "object",
    "properties": {
      "value": {"type": "number"},
      "unit_from": {"type": "string", "enum": ["celsius", "fahrenheit", "kelvin"]},
      "unit_to": {"type": "string", "enum": ["celsius", "fahrenheit", "kelvin"], "default": "celsius"}
    },
    "required": ["value", "unit_from"]
  }
}
```

## Run it

```powershell
.venv\Scripts\python.exe sdk_examples\run_example.py 02_typed_arguments.py --schema

.venv\Scripts\python.exe sdk_examples\run_example.py 02_typed_arguments.py --call convert_temperature value=72 unit_from=fahrenheit

.venv\Scripts\python.exe sdk_examples\run_example.py 02_typed_arguments.py --call split_bill total=84.5 people=3 tip_percent=20

# Coercion: a comma-separated string becomes list[float]
.venv\Scripts\python.exe sdk_examples\run_example.py 02_typed_arguments.py --call shopping_total prices=3,4,5 tax_percent=10
```

`convert_temperature value=72 unit_from=fahrenheit` should print something like `72 degrees fahrenheit is 22.2 degrees celsius.`

## Common mistakes

- Forgetting `Args:` — the model sees parameter *names* but no hint what they mean.
- Using `Optional[str] = None` when you wanted a required string. `T | None` is optional in the schema.
- Returning a Python `float` with ten decimal places. Round for speech (`:.1f`, `:g`).

## Next

[03_using_context.md](03_using_context.md) — reaching Bob's settings, files, memory, overlay, and cancel flag.
