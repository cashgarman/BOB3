from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

COMPACT_TOOL_MAX = 320
SESSION_SUMMARY_MAX = 1200
COMPRESS_NUM_PREDICT = 420

_SESSION_LEAK_RE = re.compile(
    r"\b(session memory|compress the transcript|output only the memory|"
    r"updated session memory|prior session memory)\b",
    re.IGNORECASE,
)
_WEB_HIT_RE = re.compile(r"^\d+\.\s+(.+?)(?:\s+—|\s+\(|$)")


def compact_tool_content(tool_name: str, content: str) -> str:
    raw = (content or "").strip()
    name = (tool_name or "").strip().lower()
    if name == "web_search" and _looks_like_web_search(raw):
        compact = _compact_web_search(raw)
        if compact != raw:
            return compact
    if len(raw) <= COMPACT_TOOL_MAX:
        return raw
    if name == "web_search":
        return _compact_web_search(raw)
    if name == "summarize_for_speech":
        return raw[:COMPACT_TOOL_MAX]
    if name == "conversation_log":
        return raw[:COMPACT_TOOL_MAX]
    return raw[:COMPACT_TOOL_MAX].rstrip() + " … (compressed)"


def _looks_like_web_search(content: str) -> bool:
    return bool(_WEB_HIT_RE.search(content))


def _compact_web_search(content: str) -> str:
    titles: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("no results"):
            continue
        match = _WEB_HIT_RE.match(line)
        title = match.group(1).strip() if match else line[:120].strip()
        if title and title not in titles:
            titles.append(title)
    if titles:
        joined = "; ".join(titles[:8])
        note = f"Web search (compressed): {joined}"
        return note[:COMPACT_TOOL_MAX]
    return content[:COMPACT_TOOL_MAX].rstrip() + " … (compressed)"


def compact_history(
    history: list[dict[str, Any]],
    *,
    keep_recent_tools: int = 2,
) -> list[dict[str, Any]]:
    """Shrink old tool payloads while keeping the most recent tool turns intact."""
    tool_indices = [index for index, msg in enumerate(history) if msg.get("role") == "tool"]
    compact_through = max(0, len(tool_indices) - max(0, int(keep_recent_tools)))
    compact_set = set(tool_indices[:compact_through])
    out: list[dict[str, Any]] = []
    for index, msg in enumerate(history):
        item = dict(msg)
        if index in compact_set:
            name = str(item.get("tool_name") or "")
            raw = str(item.get("content") or "")
            compacted = compact_tool_content(name, raw)
            if compacted != raw:
                item["content"] = compacted
        out.append(item)
    return out


def transcript_lines(messages: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for msg in messages:
        line = transcript_line(msg)
        if line:
            lines.append(line)
    return lines


def transcript_line(msg: dict[str, Any]) -> str:
    role = msg.get("role")
    content = str(msg.get("content") or "").strip()
    if role == "user":
        return f"User: {content}"
    if role == "tool":
        name = str(msg.get("tool_name") or "result")
        compact = compact_tool_content(name, content)
        return f"Tool {name}: {compact}"
    used = [str((call.get("function") or {}).get("name") or "") for call in msg.get("tool_calls") or []]
    used = [name for name in used if name]
    if content and used:
        return f"BOB: {content} (used {', '.join(used)})"
    if used:
        return f"BOB used {', '.join(used)}"
    return f"BOB: {content}"


def history_char_weight(history: list[dict[str, Any]]) -> int:
    total = 0
    for msg in history:
        total += len(str(msg.get("content") or ""))
        for call in msg.get("tool_calls") or []:
            total += len(str(call))
    return total


def should_compress(usage: float | None, threshold: float, history: list[dict[str, Any]], num_ctx: int) -> bool:
    if usage is not None and usage >= threshold:
        return True
    # Rough fallback before the first prompt_eval_count is recorded.
    budget = max(1024, int(num_ctx * 1.1))
    return history_char_weight(history) >= budget


def fallback_compress_summary(prior: str, lines: list[str]) -> str:
    blob = "\n".join(([prior.strip()] if prior.strip() else []) + lines)
    blob = re.sub(r"\s+", " ", blob).strip()
    if len(blob) <= SESSION_SUMMARY_MAX:
        return blob
    return blob[-SESSION_SUMMARY_MAX:]


def compress_session_transcript(host: str, model: str, prior: str, lines: list[str]) -> str:
    """Fold trimmed transcript lines into a rolling session memory note."""
    if not lines:
        return prior.strip()
    from bob.tools.builtin.summarize import _post_ollama

    transcript = "\n".join(lines).strip()
    if not transcript:
        return prior.strip()
    system = (
        "You maintain private session memory for a voice assistant. "
        "Compress the transcript into short notes the assistant can use later. "
        "Output ONLY the memory notes. No preamble, no markdown fences, no instruction text. "
        "Preserve topics discussed, facts already given, search headlines or topics, user preferences, "
        "and answers already delivered. Use tight bullet points or short sentences. "
        f"Stay under {SESSION_SUMMARY_MAX} characters."
    )
    user = (
        f"Prior session memory:\n{(prior or '').strip() or '(none)'}\n\n"
        f"New transcript to fold in:\n{transcript[:5000]}\n\n"
        "Updated session memory:"
    )
    content = _post_ollama(host, model, system, user, COMPRESS_NUM_PREDICT)
    cleaned = _clean_session_summary(content)
    if cleaned:
        return cleaned
    return fallback_compress_summary(prior, lines)


def _clean_session_summary(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    if _SESSION_LEAK_RE.search(cleaned):
        return ""
    if len(cleaned) > SESSION_SUMMARY_MAX:
        cleaned = cleaned[:SESSION_SUMMARY_MAX].rstrip()
    return cleaned


def pairs_from_messages(messages: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Extract user/assistant pairs plus optional tool notes from message blocks."""
    pairs: list[tuple[str, str, str]] = []
    index = 0
    while index < len(messages):
        msg = messages[index]
        if msg.get("role") != "user":
            index += 1
            continue
        user = str(msg.get("content") or "").strip()
        if not user:
            index += 1
            continue
        tool_notes: list[str] = []
        assistant = ""
        scan = index + 1
        while scan < len(messages):
            item = messages[scan]
            role = item.get("role")
            if role == "user":
                break
            if role == "tool":
                name = str(item.get("tool_name") or "tool")
                note = compact_tool_content(name, str(item.get("content") or ""))
                if note:
                    tool_notes.append(f"{name}: {note[:180]}")
            elif role == "assistant":
                content = str(item.get("content") or "").strip()
                if content:
                    assistant = content
            scan += 1
        if assistant:
            pairs.append((user, assistant, " | ".join(tool_notes[:3])))
        index += 1
    return pairs
