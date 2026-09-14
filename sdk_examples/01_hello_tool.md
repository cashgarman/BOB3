# Example 01 — Hello tool

**File:** [`01_hello_tool.py`](01_hello_tool.py)

The smallest thing that is still a real Bob tool: a Python function, a docstring, and `@tool`.

## What you learn

- `@tool` with no keywords is enough.
- The docstring's first paragraph is the description the model reads. Write it as an instruction to the model, not a comment for yourself.
- The return value is spoken (after the model paraphrases it), so keep it short.
- One file can register several tools. Everything decorated with `@tool` is offered; helpers without the decorator are not.

## The tools

| Name | Arguments | Returns |
|---|---|---|
| `coin_flip` | none | `"heads"` or `"tails"` |
| `lucky_number` | none | `"The lucky number is 42."` |

`lucky_number` returns a full sentence on purpose. Local 7B models repeat a ready-made phrase more reliably than a bare `"42"`.

## Run it

From the repository root, with the project venv:

```powershell
# Inspect the JSON Schema the model will see
.venv\Scripts\python.exe sdk_examples\run_example.py 01_hello_tool.py

# Call it the way Bob would
.venv\Scripts\python.exe sdk_examples\run_example.py 01_hello_tool.py --call coin_flip

# Text chat against your Ollama model, this file's tools enabled
.venv\Scripts\python.exe sdk_examples\run_example.py 01_hello_tool.py --chat
```

Expected `--call` output looks like:

```
loaded 01_hello_tool.py
example tools: coin_flip, lucky_number

coin_flip({})
-> tails
```

## Install it in Bob

Copy the file into `data\tools\` (any name that does **not** start with `_`) and restart Bob, or toggle **Tools enabled** off and on. Ask Bob to flip a coin.

## Next

[02_typed_arguments.md](02_typed_arguments.md) — parameters, types, defaults, and `Args:` docs.
