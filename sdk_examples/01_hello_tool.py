"""Example 01 - The smallest possible Bob tool.

What this shows
---------------
* The `@tool` decorator is all it takes to make a function callable by Bob.
* The docstring's first paragraph becomes the description the language model
  reads when deciding whether to call the tool. Write it as an instruction
  aimed at the model, not at a human reader.
* Whatever the function returns is handed back to the model as text, and the
  model then says it aloud in its own words, so keep results short and plain.

How to try it
-------------
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 01_hello_tool.py --call coin_flip

or start a text chat that uses the tool:

    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 01_hello_tool.py --chat

To make Bob load it for real, copy this file into `data\\tools\\` and restart.
"""

from __future__ import annotations

import random

# `tool` is the only import a basic tool needs.
from bob.tools import tool


@tool
def coin_flip() -> str:
    """Flip a coin. Use it whenever the user asks for a coin toss or heads-or-tails."""
    # No parameters means the model calls this with `{}`. The registry runs
    # the function on a worker thread, so even slow tools never freeze the
    # audio pipeline, and the result is delivered as a string to the model.
    return random.choice(["heads", "tails"])


@tool
def lucky_number() -> str:
    """Pick a random lucky number between 1 and 100 for the user."""
    # Returning a plain sentence (rather than a bare number) gives the model a
    # ready-made phrase, which local models repeat more reliably.
    return f"The lucky number is {random.randint(1, 100)}."
