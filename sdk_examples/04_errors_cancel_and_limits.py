"""Example 04 - Failure modes: errors, timeouts, cancellation, and big results.

What this shows
---------------
Bob's rule is that a tool can never break a voice turn. Every failure becomes a
text result that starts with "Error:" so the model can recover or apologise:

* **Raise `ToolError`** for problems you expect (bad arguments, nothing found).
  The message is passed through verbatim, so write it for the model.
* **Any other exception** is caught too and reported as
  "Error: tool 'name' failed: <exception>". Prefer ToolError for cleaner text.
* **Timeouts.** Each call has a budget (`tool_timeout_sec`, default 20s). When
  it expires the model receives an error and moves on; your function keeps
  running on its worker thread until it returns, so check `ctx.cancelled`
  in loops to stop wasting CPU.
* **Cancellation.** The user's hotkey sets `ctx.cancel`. Long tools should wait
  on it (`ctx.cancel.wait(seconds)`) instead of `time.sleep`.
* **Size limits.** Results longer than `MAX_RESULT_CHARS` (8000) are clipped so
  they cannot crowd the model's context window. Return summaries, not dumps.
* **Return types.** Returning a dict or list is fine: it is JSON-encoded. But
  a sentence is easier for the model to speak, so prefer strings.

How to try it
-------------
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 04_errors_cancel_and_limits.py --call pick_from_list options=
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 04_errors_cancel_and_limits.py --call pick_from_list 'options=[\\"tea\\",\\"coffee\\"]'
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 04_errors_cancel_and_limits.py --call count_slowly seconds=3 --timeout 1
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 04_errors_cancel_and_limits.py --call huge_output

(The escaped quotes are for PowerShell, which otherwise strips them before
Python sees the argument.)
"""

from __future__ import annotations

import random

from bob.tools import MAX_RESULT_CHARS, ToolContext, ToolError, tool


@tool
def pick_from_list(options: list[str]) -> str:
    """Pick one option at random from a list the user gives you.

    Args:
        options: The choices to pick from, at least two of them.
    """
    # Expected failure -> ToolError with a message the model can relay.
    cleaned = [opt.strip() for opt in options if opt and opt.strip()]
    if len(cleaned) < 2:
        raise ToolError("give me at least two options to choose from")
    return f"I pick {random.choice(cleaned)}."


@tool
def divide(numerator: float, denominator: float) -> str:
    """Divide one number by another.

    Args:
        numerator: The number being divided.
        denominator: The number to divide by.
    """
    # Unexpected exceptions are caught by the registry as well. The model
    # would receive: "Error: tool 'divide' failed: float division by zero".
    # Converting to ToolError gives it a friendlier sentence instead.
    if denominator == 0:
        raise ToolError("cannot divide by zero")
    return f"{numerator:g} divided by {denominator:g} is {numerator / denominator:g}."


@tool
def count_slowly(seconds: int = 5, *, ctx: ToolContext) -> str:
    """Count seconds out loud on the overlay; a demonstration of a slow tool.

    Args:
        seconds: How many seconds to count.
    """
    # This loop is timeout- and cancel-aware:
    #  * `ctx.cancel.wait(1)` sleeps one second but returns early on cancel.
    #  * If the registry's timeout fires first, the model already got an
    #    "Error: ... timed out" result; we notice via `ctx.cancelled` only when
    #    the user cancels, so keep individual steps short.
    for elapsed in range(1, max(1, seconds) + 1):
        if ctx.cancel.wait(1):
            return f"Cancelled after {elapsed - 1} seconds."
        ctx.status(f"counting: {elapsed}")
    return f"Counted to {seconds}."


@tool
def huge_output() -> str:
    """Return a deliberately enormous result to demonstrate clipping."""
    # 20k characters go in; the model sees the first MAX_RESULT_CHARS plus a
    # "(truncated)" marker. In a real tool, summarise instead.
    lines = [f"line {index}: the quick brown fox jumps over the lazy dog" for index in range(400)]
    text = "\n".join(lines)
    assert len(text) > MAX_RESULT_CHARS
    return text


@tool
def structured_result(city: str) -> dict:
    """Return made-up weather for a city as structured data.

    Args:
        city: The city to describe.
    """
    # Dicts are JSON-encoded before the model sees them. Useful when the model
    # needs several fields, but expect it to paraphrase, not read JSON aloud.
    return {
        "city": city,
        "condition": random.choice(["sunny", "cloudy", "rainy"]),
        "temperature_c": random.randint(-5, 35),
    }
