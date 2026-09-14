from __future__ import annotations

from bob.tools.base import ToolContext, ToolError
from bob.tools.registry import tool

MAX_NOTE_CHARS = 20000


def _notes_path(ctx: ToolContext):
    path = ctx.data_dir / "notes.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@tool
def notes_read(ctx: ToolContext) -> str:
    """Read the user's notes file."""
    path = _notes_path(ctx)
    if not path.exists():
        return "The notes file is empty."
    text = path.read_text(encoding="utf-8").strip()
    return text or "The notes file is empty."


@tool
def notes_write(text: str, append: bool = True, *, ctx: ToolContext) -> str:
    """Save text to the user's notes file.

    Args:
        text: The note to store.
        append: True to add to the end of the notes, False to replace them.
    """
    note = text.strip()
    if not note:
        raise ToolError("nothing to write")
    path = _notes_path(ctx)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    body = f"{existing.rstrip()}\n{note}\n" if (append and existing.strip()) else f"{note}\n"
    if len(body) > MAX_NOTE_CHARS:
        body = body[-MAX_NOTE_CHARS:]
    path.write_text(body, encoding="utf-8")
    return "Added to notes." if append else "Notes replaced."
