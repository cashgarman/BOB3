"""Sandboxed read/write tools for prompt templates and user-chosen folders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bob.paths import project_root
from bob.prompts import PROMPTS_DIR, save_system_prompt
from bob.settings import CONFIG_PATH
from bob.tools.base import ToolContext, ToolError
from bob.tools.registry import tool

MAX_READ_BYTES = 32 * 1024
MAX_WRITE_BYTES = 64 * 1024
_BLOCKED_DIR_NAMES = frozenset({".git", ".venv", "__pycache__", "models", "node_modules"})
_BLOCKED_SUFFIXES = frozenset({".db", ".lance", ".wal", ".shm", ".pyc"})
_BLOCKED_BASENAMES = frozenset({".env"})

_PROMPT_CATALOG: tuple[tuple[str, str], ...] = (
    ("prompts/system.txt", "Live personality / system prompt for tool rounds"),
    ("prompts/answer.txt", "Spoken chitchat answer template"),
    ("prompts/tool_guidance.txt", "When and how to call tools"),
    ("prompts/tool_synthesis.txt", "Spoken answer after tools run"),
    ("prompts/session_title.txt", "Chat sidebar title generation"),
    ("config.yaml", "BOB settings including llm_model (read-only)"),
    ("data/notes.md", "User notes shortcut (also via notes_read / notes_write)"),
)

_INLINE_PROMPTS_NOTE = (
    "Some prompts live only in Python source (not editable as files): "
    "prompt_lab scorer/improver, memory extract, session compression, summarize_for_speech."
)


@dataclass(frozen=True)
class _Root:
    path: Path
    read_only: bool = False


def _file_roots(settings: object | None) -> list[str]:
    raw = getattr(settings, "file_roots", None) if settings is not None else None
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [line.strip() for line in raw.splitlines()]
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def _allowed_roots(settings: object | None, data_dir: Path) -> list[_Root]:
    root = project_root()
    roots = [
        _Root(PROMPTS_DIR.resolve()),
        _Root(CONFIG_PATH.resolve(), read_only=True),
        _Root((data_dir / "notes.md").resolve()),
    ]
    for item in _file_roots(settings):
        try:
            path = Path(item).expanduser().resolve()
        except OSError as exc:
            raise ToolError(f"invalid file root {item!r}: {exc}") from exc
        if not path.exists():
            raise ToolError(f"file root does not exist: {path}")
        if not path.is_dir():
            raise ToolError(f"file root is not a directory: {path}")
        roots.append(_Root(path))
    seen = set()
    unique: list[_Root] = []
    for entry in roots:
        key = str(entry.path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _is_blocked(path: Path) -> bool:
    for part in path.parts:
        if part in _BLOCKED_DIR_NAMES:
            return True
    name = path.name.lower()
    if name in _BLOCKED_BASENAMES:
        return True
    if any(name.endswith(suffix) for suffix in _BLOCKED_SUFFIXES):
        return True
    return False


def _matching_root(path: Path, roots: list[_Root]) -> _Root | None:
    for entry in roots:
        try:
            if path == entry.path or path.is_relative_to(entry.path):
                return entry
        except ValueError:
            continue
    return None


def _resolve_path(raw: str, ctx: ToolContext, *, for_write: bool = False) -> Path:
    text = (raw or "").strip()
    if not text:
        raise ToolError("path is required")
    roots = _allowed_roots(ctx.settings, ctx.data_dir)
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = project_root() / candidate
    try:
        path = candidate.resolve()
    except OSError as exc:
        raise ToolError(f"cannot resolve path: {exc}") from exc
    if _is_blocked(path):
        raise ToolError("that path is not allowed")
    entry = _matching_root(path, roots)
    if entry is None:
        raise ToolError("path is outside allowed file roots")
    if for_write and entry.read_only:
        raise ToolError("that file is read-only")
    return path


def _read_text_file(path: Path, offset: int = 0, limit: int | None = None) -> str:
    if not path.exists():
        raise ToolError("file not found")
    if not path.is_file():
        raise ToolError("not a file")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ToolError(f"cannot read file: {exc}") from exc
    if len(data) > MAX_READ_BYTES and limit is None:
        raise ToolError(
            f"file is too large ({len(data)} bytes); use offset and limit to read a slice"
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError("file is not UTF-8 text")
    if "\x00" in text:
        raise ToolError("binary files are not supported")
    lines = text.splitlines()
    start = max(0, int(offset))
    if limit is None:
        chunk = lines[start:]
    else:
        chunk = lines[start : start + max(0, int(limit))]
    body = "\n".join(chunk)
    if start > 0 or (limit is not None and start + int(limit) < len(lines)):
        body = f"[lines {start + 1}-{start + len(chunk)} of {len(lines)}]\n{body}"
    return body or "(empty file)"


def _write_text_file(path: Path, content: str, ctx: ToolContext) -> str:
    text = content if content is not None else ""
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ToolError(f"content exceeds {MAX_WRITE_BYTES} bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    system_prompt = (PROMPTS_DIR / "system.txt").resolve()
    if path.resolve() == system_prompt:
        save_system_prompt(text)
        if ctx.settings is not None and hasattr(ctx.settings, "system_prompt"):
            ctx.settings.system_prompt = text.strip()
            if hasattr(ctx.settings, "save"):
                ctx.settings.save()
        return "System prompt saved."
    path.write_text(text, encoding="utf-8")
    return f"Wrote {path.name}."


def _default_list_dir(ctx: ToolContext) -> Path:
    for item in _file_roots(ctx.settings):
        try:
            path = Path(item).expanduser().resolve()
        except OSError:
            continue
        if path.is_dir():
            return path
    return PROMPTS_DIR.resolve()


def _version_prompt_entries() -> list[tuple[str, str]]:
    versions_dir = PROMPTS_DIR / "versions"
    if not versions_dir.is_dir():
        return []
    rows: list[tuple[str, str]] = []
    for path in sorted(versions_dir.glob("system.v*.txt")):
        rel = path.relative_to(project_root()).as_posix()
        rows.append((rel, "Prompt-lab snapshot of system.txt"))
    return rows


@tool
def list_prompts(ctx: ToolContext) -> str:
    """List BOB prompt template files with their paths and purpose."""
    root = project_root()
    lines = ["BOB prompt files:"]
    for rel, purpose in _PROMPT_CATALOG:
        path = (root / rel).resolve()
        lines.append(f"- {rel} | {path} | {purpose}")
    for rel, purpose in _version_prompt_entries():
        path = (root / rel).resolve()
        lines.append(f"- {rel} | {path} | {purpose}")
    lines.append(_INLINE_PROMPTS_NOTE)
    user_roots = _file_roots(ctx.settings)
    if user_roots:
        lines.append("User file roots:")
        for item in user_roots:
            lines.append(f"- {item}")
    else:
        lines.append("No extra file_roots configured; only BOB prompt files are writable.")
    return "\n".join(lines)


@tool
def list_files(path: str = ".", *, ctx: ToolContext) -> str:
    """List files and folders under an allowed directory.

    Args:
        path: Directory path under an allowed root. Defaults to the first user file root,
            or the prompts folder when no file roots are configured.
    """
    text = (path or "").strip()
    if not text or text == ".":
        target = _default_list_dir(ctx)
    else:
        target = _resolve_path(text, ctx)
    if not target.exists():
        raise ToolError("directory not found")
    if target.is_file():
        return f"file: {target.name}"
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if _is_blocked(child):
            continue
        kind = "dir" if child.is_dir() else "file"
        entries.append(f"{kind}: {child.name}")
    if not entries:
        return f"(empty directory: {target})"
    header = f"Contents of {target}:"
    return header + "\n" + "\n".join(entries)


@tool
def read_file(path: str, offset: int = 0, limit: int | None = None, *, ctx: ToolContext) -> str:
    """Read a UTF-8 text file under an allowed root.

    Args:
        path: File path under prompts/, config.yaml, notes.md, or a configured file root.
        offset: Zero-based line offset for large files.
        limit: Maximum number of lines to return.
    """
    target = _resolve_path(path, ctx)
    return _read_text_file(target, offset=offset, limit=limit)


@tool
def write_file(path: str, content: str, *, ctx: ToolContext) -> str:
    """Create or overwrite a UTF-8 text file under an allowed root.

    Args:
        path: Destination path. config.yaml is read-only.
        content: Full file contents.
    """
    target = _resolve_path(path, ctx, for_write=True)
    return _write_text_file(target, content, ctx)


@tool
def edit_file(path: str, old_text: str, new_text: str, *, ctx: ToolContext) -> str:
    """Replace exactly one occurrence of old_text with new_text in a file.

    Args:
        path: File to edit under an allowed root.
        old_text: Exact text to find once.
        new_text: Replacement text.
    """
    target = _resolve_path(path, ctx, for_write=True)
    if not target.exists():
        raise ToolError("file not found")
    body = target.read_text(encoding="utf-8")
    count = body.count(old_text)
    if count == 0:
        raise ToolError("old_text not found")
    if count > 1:
        raise ToolError("old_text matched multiple times; be more specific")
    updated = body.replace(old_text, new_text, 1)
    return _write_text_file(target, updated, ctx)
