"""Example 03 - Reaching Bob through `ToolContext`.

What this shows
---------------
Add a parameter annotated `ToolContext` and Bob injects it at call time. The
model never sees it: it is stripped from the schema, so the model cannot pass
or tamper with it. Through the context a tool can reach:

    ctx.data_dir   Path to Bob's `data\\` folder. Store tool files here.
    ctx.settings   The live `Settings` object (model name, voice, hotkey...).
    ctx.memory     The `MemoryService`, or None when memory is offline.
    ctx.status()   Push a short status string to Bob's overlay while working.
    ctx.set_mood() Colour this turn's spoken reply (see example 10).
    ctx.cancel     A threading.Event set when the user cancels the turn.
    ctx.cancelled  Shortcut for `ctx.cancel.is_set()`.

Conventions
-----------
* Put `ctx` last, ideally keyword-only (`*, ctx: ToolContext`), so it never
  collides with positional model arguments.
* Treat `ctx.memory` as optional: memory can fail to load and Bob still runs.
* Keep tool files inside `ctx.data_dir` so everything Bob owns lives in one
  place and never touches arbitrary paths on disk.

How to try it
-------------
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 03_using_context.py --call describe_setup
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 03_using_context.py --call remember_favorite thing=color value=green
"""

from __future__ import annotations

import json
from datetime import datetime

from bob.tools import ToolContext, ToolError, tool


@tool
def describe_setup(*, ctx: ToolContext) -> str:
    """Describe which language model, voice, and wake word Bob is currently using."""
    # `ctx.settings` is the same object the settings dialog edits, so this is
    # always current even if the user changed something a second ago.
    settings = ctx.settings
    if settings is None:
        # The standalone harness passes real settings, but be defensive: a
        # tool should never crash on a missing dependency.
        return "Settings are not available right now."
    wake = settings.wake_word if settings.wake_word_enabled else "off"
    return (
        f"Bob is using the {settings.llm_model} model with the {settings.tts_voice} voice. "
        f"The wake word is {wake} and the hotkey is {settings.hotkey}."
    )


@tool
def remember_favorite(thing: str, value: str, *, ctx: ToolContext) -> str:
    """Save one of the user's favorites, such as their favorite color or food.

    Args:
        thing: What kind of favorite this is, for example "color" or "movie".
        value: The favorite itself, for example "green" or "Blade Runner".
    """
    # A small JSON file under data_dir keeps state between turns and restarts.
    path = ctx.data_dir / "favorites.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    favorites: dict[str, str] = {}
    if path.exists():
        try:
            favorites = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            favorites = {}
    favorites[thing.strip().lower()] = value.strip()
    path.write_text(json.dumps(favorites, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"Saved: the user's favorite {thing} is {value}."


@tool
def recall_favorite(thing: str, *, ctx: ToolContext) -> str:
    """Look up one of the user's saved favorites.

    Args:
        thing: What kind of favorite to look up, for example "color".
    """
    path = ctx.data_dir / "favorites.json"
    if not path.exists():
        raise ToolError("no favorites have been saved yet")
    favorites = json.loads(path.read_text(encoding="utf-8"))
    value = favorites.get(thing.strip().lower())
    if value is None:
        known = ", ".join(sorted(favorites)) or "nothing"
        return f"No favorite {thing} is saved. Saved favorites: {known}."
    return f"The user's favorite {thing} is {value}."


@tool
def what_does_bob_know(topic: str, *, ctx: ToolContext) -> str:
    """Check Bob's long-term memory for facts about a topic, person, or place.

    Args:
        topic: The subject to search memory for.
    """
    # Long-term memory is a vector + graph store. `retrieve` returns a ready
    # formatted block, or an empty string when nothing relevant is stored.
    memory = ctx.memory
    if memory is None or not getattr(memory, "ready", False):
        return "Long-term memory is offline right now."
    found = memory.retrieve(topic, limit=5)
    return found or f"Nothing is stored about {topic}."


@tool
def slow_report(*, ctx: ToolContext) -> str:
    """Produce a short progress demonstration that takes a few seconds."""
    # `ctx.status` puts text on the overlay next to the THINKING state, so the
    # user can see a long tool is still alive. Check `ctx.cancelled` between
    # steps so the hotkey can abort the work immediately.
    for step in range(1, 4):
        if ctx.cancelled:
            return "Stopped early because the user cancelled."
        ctx.status(f"working, step {step} of 3")
        # Use the cancel event as a sleep that wakes up instantly on cancel.
        ctx.cancel.wait(0.5)
    return f"Finished all three steps at {datetime.now():%H:%M:%S}."
