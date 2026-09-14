# Example 07 — Stateful to-do list

**File:** [`07_stateful_todo_list.py`](07_stateful_todo_list.py)

A feature is usually **several small tools**, not one tool with a `mode` argument. This file is a spoken to-do list that survives restarts.

## What you learn

- Split the verbs: `todo_add`, `todo_list`, `todo_done`, `todo_clear`. Each schema stays tiny, which 7B models handle better than a kitchen-sink `todo(action=...)`.
- Persist under `ctx.data_dir` (`data/todo.json`). Bob owns that folder.
- Tools run on a **thread pool**. Guard read-modify-write with `threading.Lock` so two calls in one model round cannot corrupt the file.
- Phrase results for the ear: `"first, buy coffee; second, call the dentist"` and cap the list so Bob does not read twenty items.

## The tools

| Name | Does |
|---|---|
| `todo_add` | Append an open task. Dedupes case-insensitively. |
| `todo_list` | Read out open tasks (or all, if `include_done=true`). Speaks at most 7, then `"and N more"`. |
| `todo_done` | Mark done by 1-based position **or** by a substring of the name. Ambiguous matches error instead of guessing. |
| `todo_clear` | Drop finished tasks, or wipe the list (`only_done=false`). |

Shared helpers (`_load`, `_save`, `_path`) are ordinary functions. Because they are not decorated, the model never sees them.

## Run it

```powershell
.venv\Scripts\python.exe sdk_examples\run_example.py 07_stateful_todo_list.py --call todo_add task="buy coffee"
.venv\Scripts\python.exe sdk_examples\run_example.py 07_stateful_todo_list.py --call todo_add "task=call the dentist"
.venv\Scripts\python.exe sdk_examples\run_example.py 07_stateful_todo_list.py --call todo_list
.venv\Scripts\python.exe sdk_examples\run_example.py 07_stateful_todo_list.py --call todo_done number=1
.venv\Scripts\python.exe sdk_examples\run_example.py 07_stateful_todo_list.py --call todo_done task=dentist

# Best example to try as a conversation
.venv\Scripts\python.exe sdk_examples\run_example.py 07_stateful_todo_list.py --chat
```

In `--chat`, try: `add buy coffee to my list`, `what's on my list`, `the coffee one is done`.

State lives in `data/todo.json`. Delete that file to start over.

## Why not one tool?

A single `todo(action, task, number)` schema forces the model to fill fields that do not apply (`number` when adding, `task` when listing). Four tools mean four small schemas and four obvious names, which is how the built-in `notes_read` / `notes_write` pair is written too.

## Next

[08_mcp_server/README.md](08_mcp_server/README.md) — the same idea, running in another process over MCP.
