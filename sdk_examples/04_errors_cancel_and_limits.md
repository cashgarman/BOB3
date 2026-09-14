# Example 04 — Errors, cancel, and limits

**File:** [`04_errors_cancel_and_limits.py`](04_errors_cancel_and_limits.py)

A tool is not allowed to break a voice turn. Every failure becomes a string starting with `Error:` so the model can recover or apologise.

## What you learn

| Failure | What to do | What the model sees |
|---|---|---|
| Bad arguments, nothing found | `raise ToolError("…")` | `Error: tool 'name' failed: …` |
| Unexpected exception | avoid; it is still caught | `Error: tool 'name' failed: <exception>` |
| Slow work | check `ctx.cancelled`; keep steps short | `Error: tool 'name' timed out after Ns.` after `tool_timeout_sec` |
| User hits the hotkey | `ctx.cancel.wait(1)` instead of `time.sleep` | your function should return a short "Cancelled…" string |
| Huge return value | summarise | first 8000 characters + ` … (truncated)` |
| Structured data | returning a `dict` is JSON-encoded | JSON, which the model must then paraphrase |

The timeout is enforced by the registry, not by your function. After a timeout the model already moved on; your worker keeps running until it returns. That is why `count_slowly` waits on `ctx.cancel` one second at a time.

## The tools

| Name | Demonstrates |
|---|---|
| `pick_from_list` | `ToolError` when fewer than two options. |
| `divide` | converting a crash (`/ 0`) into a sentence. |
| `count_slowly` | timeout + cancel + `ctx.status`. |
| `huge_output` | clipping at `MAX_RESULT_CHARS` (8000). |
| `structured_result` | returning a `dict` (JSON-encoded). |

## Run it

PowerShell strips inner double quotes. Put JSON inside a *single-quoted* string and escape the quotes:

```powershell
# Expected failure
.venv\Scripts\python.exe sdk_examples\run_example.py 04_errors_cancel_and_limits.py --call pick_from_list options=

# JSON list (PowerShell)
.venv\Scripts\python.exe sdk_examples\run_example.py 04_errors_cancel_and_limits.py --call pick_from_list 'options=[\"tea\",\"coffee\"]'

# Timeout: the function counts to 3, the budget is 1 second
.venv\Scripts\python.exe sdk_examples\run_example.py 04_errors_cancel_and_limits.py --call count_slowly seconds=3 --timeout 1

.venv\Scripts\python.exe sdk_examples\run_example.py 04_errors_cancel_and_limits.py --call huge_output

.venv\Scripts\python.exe sdk_examples\run_example.py 04_errors_cancel_and_limits.py --call structured_result city=Oslo

.venv\Scripts\python.exe sdk_examples\run_example.py 04_errors_cancel_and_limits.py --call divide numerator=10 denominator=0
```

`--timeout 1` on `count_slowly seconds=3` should print `Error: tool 'count_slowly' timed out after 1s.` about one second later. The worker is still counting; that is expected.

## Next

[05_explicit_schema.md](05_explicit_schema.md) — custom names, descriptions, and hand-written JSON Schema.
