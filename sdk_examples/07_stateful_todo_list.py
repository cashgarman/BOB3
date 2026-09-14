"""Example 07 - Several tools sharing persistent state: a spoken to-do list.

What this shows
---------------
* A small feature is usually **several tools**, not one tool with a `mode`
  argument. Separate `todo_add`, `todo_list`, `todo_done`, `todo_clear`
  functions give the model clear choices and simple schemas.
* State lives in a JSON file under `ctx.data_dir`, so it survives restarts and
  stays inside the folder Bob owns.
* Tools run on a **thread pool**, so anything that mutates shared state needs
  a lock. `threading.Lock` around read-modify-write keeps the file consistent
  even if the model calls two tools in one round.
* Results are phrased for the ear: item numbers are spoken as "first" and
  "second", and lists are capped so Bob does not read twenty lines aloud.

How to try it
-------------
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 07_stateful_todo_list.py --call todo_add task="buy coffee"
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 07_stateful_todo_list.py --call todo_list
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 07_stateful_todo_list.py --call todo_done number=1
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 07_stateful_todo_list.py --chat
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from bob.tools import ToolContext, ToolError, tool

# One lock for the whole module. Every tool below takes it before touching the
# file, which makes add/done/clear safe against concurrent calls.
_LOCK = threading.Lock()
_MAX_SPOKEN = 7
_ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh"]


def _path(ctx: ToolContext) -> Path:
    path = ctx.data_dir / "todo.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load(ctx: ToolContext) -> list[dict]:
    path = _path(ctx)
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [item for item in items if isinstance(item, dict) and item.get("task")]


def _save(ctx: ToolContext, items: list[dict]) -> None:
    _path(ctx).write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def _ordinal(index: int) -> str:
    return _ORDINALS[index] if index < len(_ORDINALS) else f"number {index + 1}"


@tool
def todo_add(task: str, *, ctx: ToolContext) -> str:
    """Add a task to the user's to-do list.

    Args:
        task: The task to remember, phrased as the user said it.
    """
    text = task.strip().rstrip(".")
    if not text:
        raise ToolError("the task is empty")
    with _LOCK:
        items = _load(ctx)
        if any(item["task"].lower() == text.lower() and not item.get("done") for item in items):
            return f"'{text}' is already on the list."
        items.append({"task": text, "done": False})
        _save(ctx, items)
    open_count = sum(1 for item in items if not item.get("done"))
    return f"Added '{text}'. There are now {open_count} open tasks."


@tool
def todo_list(include_done: bool = False, *, ctx: ToolContext) -> str:
    """Read out the user's to-do list.

    Args:
        include_done: Whether to also mention tasks that are already finished.
    """
    with _LOCK:
        items = _load(ctx)
    visible = [item for item in items if include_done or not item.get("done")]
    if not visible:
        return "The to-do list is empty." if include_done else "There are no open tasks."
    # Speak at most a handful; mention how many more there are.
    spoken = []
    for index, item in enumerate(visible[:_MAX_SPOKEN]):
        suffix = " (done)" if item.get("done") else ""
        spoken.append(f"{_ordinal(index)}, {item['task']}{suffix}")
    more = len(visible) - len(spoken)
    tail = f", and {more} more" if more > 0 else ""
    return f"You have {len(visible)} tasks: " + "; ".join(spoken) + tail + "."


@tool
def todo_done(number: int = 0, task: str = "", *, ctx: ToolContext) -> str:
    """Mark a task as finished, either by its position or by naming it.

    Args:
        number: The task's position in the open list, starting at 1. Use 0 when naming the task instead.
        task: Words from the task to mark done, used when the number is not known.
    """
    with _LOCK:
        items = _load(ctx)
        open_items = [item for item in items if not item.get("done")]
        target = None
        if number >= 1:
            if number > len(open_items):
                raise ToolError(f"there are only {len(open_items)} open tasks")
            target = open_items[number - 1]
        elif task.strip():
            needle = task.strip().lower()
            matches = [item for item in open_items if needle in item["task"].lower()]
            if not matches:
                raise ToolError(f"no open task mentions '{task.strip()}'")
            if len(matches) > 1:
                names = "; ".join(item["task"] for item in matches)
                raise ToolError(f"several tasks match, which one: {names}")
            target = matches[0]
        else:
            raise ToolError("say which task is done, by number or by name")
        target["done"] = True
        _save(ctx, items)
    remaining = len(open_items) - 1
    return f"Marked '{target['task']}' as done. {remaining} tasks remain."


@tool
def todo_clear(only_done: bool = True, *, ctx: ToolContext) -> str:
    """Remove finished tasks from the list, or wipe the whole list.

    Args:
        only_done: True to remove only finished tasks, False to delete everything.
    """
    with _LOCK:
        items = _load(ctx)
        kept = [item for item in items if not item.get("done")] if only_done else []
        removed = len(items) - len(kept)
        _save(ctx, kept)
    if only_done:
        return f"Removed {removed} finished tasks. {len(kept)} remain."
    return f"Cleared the whole list, {removed} tasks removed."
