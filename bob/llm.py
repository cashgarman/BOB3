from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from bob.prompts import load_answer_prompt, load_system_prompt, load_tool_guidance

log = logging.getLogger(__name__)

LARGE_MODEL_BYTES = 6 * 1024 * 1024 * 1024

_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</think\s*>", re.IGNORECASE)
_PARTIAL_THINK_OPEN = ("<think>", "<think", "<thin", "<thi", "<th", "<t", "<")
_PREAMBLE_RE = re.compile(
    r"\b(let me check|i(?:['’]ll| will) (?:check|look|find)|give me a (?:moment|second))\b",
    re.IGNORECASE,
)
_MONOLOGUE_RE = re.compile(
    r"(?:^|\n)\s*(?:okay,?\s+)?(?:the user is|let me think|let me recall|first,?\s+i need to|"
    r"looking at the tools|the tools (?:list|provided|say)|from the known information|"
    r"the instructions say|the tool response|previous response|in previous interactions|"
    r"so bob should|(?:wait|hmm),?\s+(?:the|but|maybe|so)\b)",
    re.IGNORECASE,
)
_META_REPLY_RE = re.compile(
    r"\b(should say|should respond|should call|needs to call|the user|the tool|bob should|"
    r"main point is|key here is|i(?:['’]ll| will)|better not|best to|"
    r"they(?:['’]ve| have) been|without overthinking|without caveats|"
    r"universally (?:acceptable|accepted)|pretend i|overthinking|no_think)\b",
    re.IGNORECASE,
)
_QUOTED_ANSWER_RE = re.compile(r'"([^"\n]{5,160})"')
_TIME_TOOL_RE = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s.+?\s+at\s+"
    r"(\d{1,2}:\d{2}\s+(?:AM|PM))\s+(.+)$",
    re.IGNORECASE,
)
# Voice replies should stay short; qwen3 tool rounds often ramble when thinking leaks.
_CHAT_NUM_PREDICT = 256
_THINKING_CHAT_NUM_PREDICT = 128
_THINKING_FINAL_NUM_PREDICT = 512
_TOOL_ROUND_MONOLOGUE_CHARS = 520
_SPOKEN_REPLY_MAX_CHARS = 420
_NO_THINK_RE = re.compile(r"\s*/no_think\b", re.IGNORECASE)
_MATH_TIMES_RE = re.compile(
    r"(?:what(?:'s| is|s)?)\s*(\d+)\s*(?:times|multiplied by|x|\*)\s*(\d+)",
    re.IGNORECASE,
)
_MATH_PLUS_RE = re.compile(
    r"(?:what(?:'s| is|s)?)\s*(\d+)\s*(?:plus|\+)\s*(\d+)",
    re.IGNORECASE,
)
_FEELING_RE = re.compile(r"\bhow (?:are you feeling|do you feel|you feeling)\b", re.IGNORECASE)


def needs_conversation_log(user_text: str) -> bool:
    t = (user_text or "").lower()
    keys = (
        "first question",
        "first prompt",
        "how many prompt",
        "how many question",
        "when was my",
        "what time was",
        "what time did",
        "earlier in this",
        "conversation today",
        "conversation log",
        "in our conversation",
        "in this conversation",
    )
    return any(k in t for k in keys)


def needs_agentic_tools(user_text: str) -> bool:
    """Only run tool-selection rounds when the user likely needs a tool."""
    if needs_current_time(user_text) or needs_conversation_log(user_text):
        return True
    if _needs_web_search(user_text) or needs_chat_context(user_text):
        return True
    t = (user_text or "").lower()
    keys = (
        "weather",
        "note",
        "remember that",
        "remind me",
        "timer",
        "alarm",
        "conversation log",
        "what did i say",
        "save this",
    )
    return any(k in t for k in keys)


def needs_chat_context(user_text: str) -> bool:
    """Follow-ups that refer to earlier turns in this chat."""
    t = (user_text or "").lower()
    keys = (
        "rephrase",
        "say that again",
        "say it again",
        "bullet point",
        "bullets",
        "didn't get",
        "didnt get",
        "don't get",
        "dont get",
        "what do you mean",
        "summarize that",
        "that again",
        "you just said",
        "your last",
        "previous answer",
        "as opposed to",
        "instead of",
        "can you repeat",
        "repeat that",
        "didn't receive",
        "didnt receive",
        "specific question yet",
    )
    return any(k in t for k in keys)


def _user_wants_bullets(question: str) -> bool:
    t = (question or "").lower()
    return any(k in t for k in ("bullet", "bullets", "as a list", "list format"))


def _looks_like_bullet_list(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    marked = sum(
        1
        for line in lines
        if line.startswith(("-", "•", "*")) or re.match(r"^\d+[.)]\s", line)
    )
    return marked >= 2


def _spoken_max_chars(question: str) -> int:
    return 900 if _user_wants_bullets(question) else _SPOKEN_REPLY_MAX_CHARS


def needs_current_time(user_text: str) -> bool:
    t = (user_text or "").lower()
    keys = (
        "what time is it",
        "what's the time",
        "whats the time",
        "what time is",
        "current time",
        "time is it now",
        "tell me the time",
    )
    return any(k in t for k in keys)


def _try_direct_answer(user_text: str) -> str:
    """Answer simple deterministic questions without calling the LLM."""
    t = (user_text or "").strip()
    if not t:
        return ""
    match = _MATH_TIMES_RE.search(t)
    if match:
        return str(int(match.group(1)) * int(match.group(2)))
    match = _MATH_PLUS_RE.search(t)
    if match:
        return str(int(match.group(1)) + int(match.group(2)))
    if _FEELING_RE.search(t):
        return "I'm doing well and ready to help."
    return ""


_BAD_ANSWER_START_RE = re.compile(
    r"^(?:it covers|i recall(?: that)?|first,?|as bob,?|hmm,?|okay,?|the user|let me|"
    r"we are given|i need to|no extra|since|so,?|wait,?|better not|best to)\b",
    re.IGNORECASE,
)
_INSTRUCTION_ECHO_RE = re.compile(
    r"\b(no extra commentary|direct answer only|spoken sentence|short natural sentence|"
    r"natural sentence ending|give the direct answer|no planning|meta commentary|"
    r"i must answer|i need to respond|need to respond|"
    r"respond as bob|one short natural sentence|"
    r"keep answers concise|background notes|must phrase it naturally|"
    r"shouldn't repeat|do not summarize aloud|for your use only|"
    r"meant to be heard aloud|say only the answer)\b",
    re.IGNORECASE,
)
_PROMPT_ECHO_PHRASES = (
    "keep answers concise",
    "background notes",
    "never repeat",
    "must phrase it naturally",
    "shouldn't repeat",
    "do not summarize aloud",
    "for your use only",
    "short natural sentence",
    "no extra commentary",
    "meant to be heard aloud",
    "say only the answer",
    "no rules, no commentary",
)


def _echoes_prompt(text: str) -> bool:
    lower = (text or "").lower()
    return any(phrase in lower for phrase in _PROMPT_ECHO_PHRASES)


def _looks_like_spoken_answer(text: str, question: str = "") -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _echoes_prompt(t) or _INSTRUCTION_ECHO_RE.search(t) or _BAD_ANSWER_START_RE.search(t):
        return False
    if _looks_like_meta_reply(t):
        return False
    if question and _is_useless_reply(t, question):
        return False
    if re.fullmatch(r"\d+", t):
        return True
    if _is_internal_monologue(t):
        return False
    max_chars = _spoken_max_chars(question)
    if _user_wants_bullets(question) and _looks_like_bullet_list(t) and len(t) <= max_chars:
        return True
    if t[-1] in ".!?" and len(t) <= max_chars:
        return bool(re.findall(r"[a-z0-9']+", t.lower()))
    words = re.findall(r"[a-z0-9']+", t.lower())
    return len(t) <= max_chars and len(words) >= 2 and not t.endswith(",")


def _looks_complete_answer(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _BAD_ANSWER_START_RE.search(t):
        return False
    if re.fullmatch(r"\d+", t):
        return True
    if t[-1] in ".!?":
        return len(t) >= 10
    return False


def _normalize_for_compare(text: str) -> str:
    cleaned = _NO_THINK_RE.sub("", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned.rstrip("?.! ")


def _strip_control_tokens(text: str) -> str:
    return _NO_THINK_RE.sub("", text or "").strip()


def _is_useless_reply(reply: str, user_text: str) -> bool:
    spoken = _normalize_for_compare(reply)
    asked = _normalize_for_compare(user_text)
    if not spoken:
        return True
    if asked and spoken == asked:
        return True
    if asked and spoken.endswith(asked) and len(spoken) <= len(asked) + 16:
        return True
    if "/no_think" in (reply or "").lower() and len(spoken) <= max(len(asked) + 12, 24):
        return True
    return False


def _is_tool_preamble(text: str) -> bool:
    return bool(_PREAMBLE_RE.search(text or ""))


def _is_internal_monologue(text: str) -> bool:
    """Detect planning narration that should never be spoken to the user."""
    t = (text or "").strip()
    if not t:
        return False
    if _MONOLOGUE_RE.search(t):
        return True
    if _META_REPLY_RE.search(t) and len(t) > 80:
        return True
    return len(t) > _TOOL_ROUND_MONOLOGUE_CHARS


def _looks_like_meta_reply(text: str) -> bool:
    return bool(_META_REPLY_RE.search(text or ""))


def _extract_quoted_answer(text: str) -> str:
    for match in _QUOTED_ANSWER_RE.finditer(text or ""):
        candidate = match.group(1).strip()
        if (
            candidate
            and len(candidate) <= _SPOKEN_REPLY_MAX_CHARS
            and not _is_internal_monologue(candidate)
            and not _looks_like_meta_reply(candidate)
        ):
            return candidate
    return ""


def _extract_last_short_line(text: str) -> str:
    for para in reversed(re.split(r"\n\s*\n", (text or "").strip())):
        line = " ".join(para.split())
        if (
            5 <= len(line) <= _SPOKEN_REPLY_MAX_CHARS
            and not _is_internal_monologue(line)
            and not _looks_like_meta_reply(line)
        ):
            return line
    return ""


def _format_time_tool_result(raw: str) -> str:
    text = (raw or "").strip()
    match = _TIME_TOOL_RE.search(text)
    if match:
        zone = match.group(2).strip()
        short_zone = zone.replace("Daylight Time", "time").replace("Standard Time", "time")
        return f"It's {match.group(1)}, {short_zone}."
    if text:
        return f"It's {text}."
    return ""


def _fallback_from_tool_history(history: list[dict[str, Any]], user_text: str = "") -> str:
    if not needs_current_time(user_text):
        return ""
    for msg in reversed(history):
        if msg.get("role") != "tool":
            continue
        name = str(msg.get("tool_name") or "").strip()
        content = str(msg.get("content") or "").strip()
        if name == "get_current_time" and content:
            return _format_time_tool_result(content)
    return ""


def _spoken_question(history: list[dict[str, Any]] | None, spoken_user: str = "") -> str:
    question = (spoken_user or "").strip()
    if question:
        return question
    for msg in reversed(history or []):
        if msg.get("role") != "user":
            continue
        lines = [line.strip() for line in str(msg.get("content") or "").splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return ""


def _compose_internal_thought(
    thinking_field: str,
    raw_content: str,
    spoken_content: str,
    spoken_user: str = "",
) -> str:
    parts: list[str] = []
    thinking = _strip_control_tokens(_strip_think_blocks(thinking_field or "")).strip()
    if thinking:
        parts.append(thinking)
    raw = _strip_control_tokens(_strip_think_blocks(raw_content or "")).strip()
    spoken = _strip_control_tokens(_strip_think_blocks(spoken_content or "")).strip()
    if raw:
        if spoken and raw == spoken:
            pass
        elif spoken_user and _is_useless_reply(raw, spoken_user):
            if not thinking:
                parts.append("Evaluated the prompt internally (echo suppressed).")
        elif _is_internal_monologue(raw) or (spoken and raw != spoken):
            if raw not in parts:
                parts.append("Planned the reply internally.")
        elif not spoken:
            parts.append(raw)
    return "\n\n".join(part for part in parts if part).strip()


def _pick_spoken_answer(raw: str, question: str) -> str:
    text = _strip_control_tokens(_strip_think_blocks(raw or "")).strip()
    if not text:
        return ""
    max_chars = _spoken_max_chars(question)
    if (
        len(text) <= max_chars
        and not _is_internal_monologue(text)
        and _looks_like_spoken_answer(text, question)
    ):
        return text
    quoted = _extract_quoted_answer(text)
    if quoted and _looks_like_spoken_answer(quoted, question):
        return quoted
    return ""


def _finalize_spoken_reply(
    text: str,
    history: list[dict[str, Any]] | None,
    spoken_user: str = "",
) -> str:
    question = _spoken_question(history, spoken_user)
    cleaned = _sanitize_spoken_reply(text, history, question)
    if cleaned and (not question or not _is_useless_reply(cleaned, question)):
        return cleaned
    raw = _strip_control_tokens(_strip_think_blocks(text or ""))
    if question and raw and _is_useless_reply(raw, question):
        fallback = _fallback_from_tool_history(history or [], question)
        if fallback:
            return fallback
        return ""
    return cleaned


def _sanitize_spoken_reply(
    text: str,
    history: list[dict[str, Any]] | None = None,
    user_text: str = "",
) -> str:
    """Keep only the short answer meant to be heard aloud."""
    t = _strip_control_tokens(_strip_think_blocks(text or ""))
    if not t:
        return _fallback_from_tool_history(history or [], user_text) if history else ""
    if user_text and _is_useless_reply(t, user_text):
        if history:
            fallback = _fallback_from_tool_history(history, user_text)
            if fallback:
                return fallback
        return ""
    if not _is_internal_monologue(t):
        if len(t) <= _SPOKEN_REPLY_MAX_CHARS:
            return t
        short = _extract_last_short_line(t)
        return short or t[:_SPOKEN_REPLY_MAX_CHARS].rsplit(" ", 1)[0].strip()
    for extractor in (_extract_quoted_answer,):
        hit = extractor(t)
        if hit:
            return hit
    if history:
        return _fallback_from_tool_history(history, user_text)
    return ""


def _strip_think_blocks(text: str) -> str:
    """Drop complete … sections and any unclosed think tail."""
    raw = text or ""
    visible = _THINK_RE.sub("", raw)
    match = _THINK_OPEN_RE.search(visible)
    if match:
        visible = visible[: match.start()]
    if visible != raw:
        return visible.strip()
    return visible


def _hold_partial_open(text: str) -> str:
    lower = text.lower()
    for prefix in _PARTIAL_THINK_OPEN:
        if lower.endswith(prefix):
            return text[: -len(prefix)]
    return text


def _visible_llm_prefix(raw: str) -> str:
    """Spoken text so far, holding back an unfinished <think> block."""
    out: list[str] = []
    i = 0
    n = len(raw)
    in_think = False
    while i < n:
        if in_think:
            close = _THINK_CLOSE_RE.search(raw, i)
            if not close:
                return "".join(out)
            i = close.end()
            in_think = False
            continue
        open_tag = _THINK_OPEN_RE.search(raw, i)
        if open_tag:
            out.append(raw[i : open_tag.start()])
            i = open_tag.end()
            in_think = True
            continue
        out.append(_hold_partial_open(raw[i:]))
        break
    return "".join(out)


class _ThinkGate:
    """Yield only non-think content while tokens stream in."""

    def __init__(self) -> None:
        self.raw = ""
        self._emitted = 0

    def add(self, chunk: str) -> str:
        if not chunk:
            return ""
        self.raw += chunk
        visible = _visible_llm_prefix(self.raw)
        extra = visible[self._emitted :]
        self._emitted = len(visible)
        return extra

    def visible(self) -> str:
        return _strip_think_blocks(self.raw)


def _needs_web_search(user_text: str) -> bool:
    t = (user_text or "").lower()
    keys = (
        "search",
        "look up",
        "lookup",
        "web",
        "online",
        "news",
        "headline",
        "latest",
        "current events",
    )
    return any(k in t for k in keys)


def _fresh_web_search(user_text: str) -> bool:
    """True when the user is asking for a new lookup, not reformatting prior results."""
    if not _needs_web_search(user_text):
        return False
    if not needs_chat_context(user_text):
        return True
    t = (user_text or "").lower()
    fresh_keys = (
        "search",
        "look up",
        "lookup",
        "search online",
        "look online",
        "find online",
        "latest",
        "current",
        "right now",
        "today",
    )
    return any(k in t for k in fresh_keys)


def _web_search_query(user_text: str) -> str:
    text = (user_text or "").strip()
    lower = text.lower()
    for prefix in ("can you ", "could you ", "please ", "would you ", "will you "):
        if lower.startswith(prefix):
            text = text[len(prefix) :].strip()
            lower = text.lower()
    for verb in (
        "look up ",
        "search the web for ",
        "search online for ",
        "search for ",
        "find ",
        "check ",
    ):
        if lower.startswith(verb):
            text = text[len(verb) :].strip()
            break
    return text.strip().rstrip("?.!")


def _deferral_tool_name(preamble: str, user_text: str) -> str | None:
    p = (preamble or "").lower()
    if "conversation" in p or needs_conversation_log(user_text):
        return "conversation_log"
    if needs_chat_context(user_text) and not _fresh_web_search(user_text):
        return "conversation_log"
    if _fresh_web_search(user_text):
        return "web_search"
    return None


def _deferral_tool_args(tool_name: str, user_text: str) -> dict[str, Any]:
    if tool_name == "conversation_log":
        return {"limit": 40}
    if tool_name == "web_search":
        return {"query": _web_search_query(user_text) or user_text}
    return {}


def _invoke_web_search(on_tool: Callable[[str, Any], str], user_text: str) -> str:
    try:
        return on_tool("web_search", _deferral_tool_args("web_search", user_text))
    except Exception as exc:
        return f"Error: tool 'web_search' failed: {exc}"


def _invoke_conversation_log(on_tool: Callable[[str, Any], str], limit: int = 20) -> str:
    try:
        return on_tool("conversation_log", {"limit": limit})
    except Exception as exc:
        return f"Error: tool 'conversation_log' failed: {exc}"


def _invoke_summarize(
    on_tool: Callable[[str, Any], str],
    text: str,
    question: str,
    *,
    bullets: bool = False,
) -> str:
    style = "bullets" if bullets else "brief"
    try:
        return on_tool(
            "summarize_for_speech",
            {"text": text, "question": question, "style": style},
        )
    except Exception as exc:
        return f"Error: tool 'summarize_for_speech' failed: {exc}"


def _spoken_from_tool_text(text: str, question: str, history: list[dict[str, Any]] | None = None) -> str:
    """Extract a clean spoken answer from a tool result, or "" if none is safe.

    Never falls back to raw/truncated text: speaking partial internal
    monologue is worse than saying nothing and letting the caller retry.
    """
    raw = (text or "").strip()
    if not raw or raw.startswith("Error"):
        return ""
    picked = _pick_spoken_answer(raw, question)
    if picked:
        return picked
    cleaned = _sanitize_spoken_reply(raw, history, question)
    if cleaned and _looks_like_spoken_answer(cleaned, question):
        return cleaned
    if _looks_like_spoken_answer(raw, question):
        return raw
    return ""


def _fallback_headlines_from_search(search_text: str, limit: int = 3) -> str:
    """Best-effort deterministic summary when the LLM summarizer fails outright."""
    titles: list[str] = []
    for line in (search_text or "").splitlines():
        line = line.strip()
        match = re.match(r"^\d+\.\s*(.+)", line)
        if not match:
            continue
        rest = match.group(1)
        # Drop the trailing " — snippet (url)" tail, keep just the title.
        title = re.split(r"\s+—\s+|\s+\(https?://", rest)[0].strip()
        if title:
            titles.append(title)
        if len(titles) >= limit:
            break
    if not titles:
        return ""
    if len(titles) == 1:
        return f"Here's what I found: {titles[0]}."
    if len(titles) == 2:
        return f"Here's what I found: {titles[0]}, and {titles[1]}."
    return "Here's what I found: " + ", ".join(titles[:-1]) + f", and {titles[-1]}."


def _is_tools_unsupported_error(message: str) -> bool:
    lower = (message or "").lower()
    return "does not support tools" in lower


def _ollama_error(exc: Exception, model: str) -> str:
    """Turn httpx/Ollama failures into something a user can act on."""
    if isinstance(exc, httpx.HTTPStatusError):
        return _ollama_error_body(exc.response.text, model) or str(exc)
    if isinstance(exc, RuntimeError):
        text = str(exc)
        parsed = _ollama_error_body(text, model)
        if parsed:
            return parsed
    return str(exc)


def _ollama_error_body(raw: str, model: str) -> str | None:
    msg: str | None = None
    if raw.strip():
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = raw.strip()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
            elif isinstance(err, str):
                msg = err
        elif isinstance(body, str):
            msg = body
    if isinstance(msg, str) and msg.strip():
        text = msg.strip()
        if "not found" in text.lower():
            return (
                f"Ollama model '{model}' is not installed ({text}). "
                f"Run: ollama pull {model} — or pick another model in BOB's tray menu."
            )
        return text
    return None
# Streaming replies: never hang forever on a dead socket, but allow a slow
# first token while Ollama pages the model in.
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


class OllamaChat:
    def __init__(self, host: str, model: str, num_ctx: int, system_prompt: str, max_turns: int) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.history: list[dict[str, Any]] = []
        self.session_summary = ""
        self._summary_lock = threading.Lock()
        self.last_prompt_eval_count: int | None = None
        self.last_prompt_eval_ms: float | None = None
        self.last_eval_count: int | None = None
        self.last_eval_ms: float | None = None
        self.last_ttft_ms: float | None = None
        self._tools_unsupported = False
        self.last_internal_thought = ""

    def _append_internal_thought(self, piece: str, on_thought: Callable[[str], None] | None = None) -> None:
        text = (piece or "").strip()
        if not text:
            return
        if self.last_internal_thought:
            if text in self.last_internal_thought:
                return
            self.last_internal_thought = f"{self.last_internal_thought}\n\n{text}"
        else:
            self.last_internal_thought = text
        if on_thought:
            on_thought(self.last_internal_thought)

    def reset_tools_support(self) -> None:
        self._tools_unsupported = False

    def ping(self) -> None:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{self.host}/api/tags")
            r.raise_for_status()

    def list_models(self) -> list[dict]:
        # Called while building the tray menu, so keep the worst case short.
        with httpx.Client(timeout=3.0) as client:
            r = client.get(f"{self.host}/api/tags")
            r.raise_for_status()
            return list(r.json().get("models") or [])

    def is_large_model(self, name: str) -> bool:
        for item in self.list_models():
            model_name = item.get("name") or item.get("model") or ""
            if model_name == name or model_name.startswith(name):
                return int(item.get("size") or 0) > LARGE_MODEL_BYTES
        return False

    def snapshot(self) -> tuple[list[dict[str, Any]], str]:
        return [dict(msg) for msg in self.history], self.session_summary

    def restore(self, history: list[dict[str, Any]], summary: str) -> None:
        self.history = [dict(msg) for msg in history]
        self.session_summary = summary

    def _thinks(self) -> bool:
        name = (self.model or "").lower()
        return any(tag in name for tag in ("qwen3", "deepseek-r1", "gpt-oss"))

    def _apply_think(self, payload: dict[str, Any]) -> None:
        if not self._thinks():
            return
        payload["think"] = False
        payload["reasoning_effort"] = "none"
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return
        cleaned: list[dict[str, Any]] = []
        for msg in messages:
            item = dict(msg)
            if item.get("role") == "assistant":
                item["content"] = _strip_think_blocks(str(item.get("content") or ""))
            cleaned.append(item)
        payload["messages"] = cleaned

    def _system(self, with_tools: bool = False, memory_block: str = "") -> str:
        parts = [load_system_prompt()]
        if with_tools:
            parts.append(load_tool_guidance())
        context_bits: list[str] = []
        if self.session_summary.strip():
            context_bits.append(
                "Earlier in this chat (background only — do not read aloud):\n"
                f"{self.session_summary.strip()}"
            )
        if (memory_block or "").strip():
            context_bits.append(memory_block.strip())
        if context_bits:
            parts.append(
                "Background (for your use only — never read aloud):\n\n"
                + "\n\n".join(context_bits)
            )
        return "\n\n".join(p for p in parts if p)

    def _history_for_answer(self, question: str) -> list[dict[str, str]]:
        """Recent user/assistant turns for follow-up questions."""
        prior: list[dict[str, str]] = []
        for msg in self.history:
            role = msg.get("role")
            if role == "user":
                content = str(msg.get("content") or "").strip()
                if content:
                    prior.append({"role": "user", "content": content})
            elif role == "assistant":
                content = str(msg.get("content") or "").strip()
                if content:
                    prior.append({"role": "assistant", "content": content})
        if prior and prior[-1]["role"] == "user" and prior[-1]["content"].strip() == question.strip():
            prior = prior[:-1]
        max_msgs = max(2, self.max_turns * 2)
        return prior[-max_msgs:]

    def _answer_messages(
        self,
        question: str,
        memory_block: str = "",
        history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        question = (question or "").strip()
        system = load_answer_prompt()
        if _user_wants_bullets(question):
            system += " Use short bullet points when the user asked for bullets."
        if (memory_block or "").strip():
            system += (
                "\n\nBackground (for your use only — never read aloud):\n\n"
                + memory_block.strip()
            )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": question})
        return messages

    def preload(self, tools: list[dict[str, Any]] | None = None) -> None:
        try:
            self._preload_request(tools)
        except RuntimeError as exc:
            if tools and _is_tools_unsupported_error(str(exc)):
                self._tools_unsupported = True
                log.warning("Model %s does not support tools; preload without tools", self.model)
                self._preload_request(None)
            else:
                raise

    def _preload_request(self, tools: list[dict[str, Any]] | None = None) -> None:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": self._system(with_tools=bool(tools))}],
            "stream": False,
            "keep_alive": -1,
            "options": {"num_ctx": self.num_ctx, "num_predict": 1},
        }
        self._apply_think(payload)
        if tools:
            payload["tools"] = tools
        with httpx.Client(timeout=180.0) as client:
            r = client.post(f"{self.host}/api/chat", json=payload)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(_ollama_error(exc, self.model)) from exc

    def reset(self) -> None:
        self.history.clear()
        self.session_summary = ""

    def _post_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        num_predict: int = 256,
        temperature: float = 0.2,
        think: bool | None = None,
    ) -> tuple[str, str, dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": {
                "num_ctx": self.num_ctx,
                "num_predict": num_predict,
                "temperature": temperature,
            },
        }
        if think is True:
            payload["think"] = True
        else:
            self._apply_think(payload)
        with httpx.Client(timeout=120.0) as client:
            r = client.post(f"{self.host}/api/chat", json=payload)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(_ollama_error(exc, self.model)) from exc
            body = r.json()
            message = body.get("message") or {}
            content = _strip_think_blocks(str(message.get("content") or ""))
            thinking = str(message.get("thinking") or message.get("reasoning") or "")
            meta = {
                "eval_count": body.get("eval_count"),
                "done_reason": body.get("done_reason"),
                "num_predict": num_predict,
            }
            return content, thinking, meta

    def generate(self, instruction: str, user_text: str, num_predict: int = 256) -> str:
        content, _thinking, _meta = self._post_chat(
            [
                {"role": "system", "content": instruction},
                {"role": "user", "content": user_text or " "},
            ],
            num_predict=num_predict,
            temperature=0.2,
        )
        return content

    def _answer_from_web_search(
        self,
        spoken_user: str,
        on_tool: Callable[[str, Any], str],
        on_thought: Callable[[str], None] | None = None,
    ) -> str:
        search = _invoke_web_search(on_tool, spoken_user)
        if not search.strip() or search.startswith("Error"):
            return ""
        summary = _invoke_summarize(
            on_tool,
            search,
            spoken_user,
            bullets=_user_wants_bullets(spoken_user),
        )
        self.history.append({"role": "tool", "tool_name": "web_search", "content": search})
        reply = ""
        if summary.strip() and not summary.startswith("Error"):
            self.history.append({"role": "tool", "tool_name": "summarize_for_speech", "content": summary})
            reply = _spoken_from_tool_text(summary, spoken_user, self.history)
        if not reply:
            # The summarizer either errored or kept narrating; fall back to a
            # deterministic answer built straight from the search titles
            # rather than risk speaking leftover monologue.
            reply = _fallback_headlines_from_search(search)
        if reply:
            self._append_internal_thought(
                "Searched the web and summarized the results for speech.",
                on_thought,
            )
            self.history.append({"role": "assistant", "content": reply})
        return reply

    def _generate_spoken_answer(
        self,
        question: str,
        memory_block: str = "",
        on_tool: Callable[[str, Any], str] | None = None,
    ) -> str:
        question = (question or "").strip()
        if not question:
            return "Sorry, I didn't catch that."
        if on_tool and (memory_block or "").strip():
            summary = _invoke_summarize(
                on_tool,
                memory_block,
                question,
                bullets=_user_wants_bullets(question),
            )
            if summary.strip() and not summary.startswith("Error"):
                reply = _spoken_from_tool_text(summary, question, self.history)
                if reply:
                    return reply
        messages = self._answer_messages(
            question,
            memory_block=memory_block,
            history=self._history_for_answer(question),
        )
        use_think = self._thinks()
        for attempt in range(2):
            predict = 160
            if use_think:
                predict = 512 if attempt == 0 else 768
            try:
                content, _thinking, _meta = self._post_chat(
                    messages,
                    num_predict=predict,
                    temperature=0.3,
                    think=True if use_think else False,
                )
            except Exception as exc:
                log.warning("Spoken answer failed: %s", exc)
                return "Sorry, I got stuck for a moment."
            raw = _strip_control_tokens(_strip_think_blocks(content or "")).strip()
            picked = _pick_spoken_answer(raw, question)
            if picked:
                return picked
            if raw and not _is_internal_monologue(raw):
                line = _extract_last_short_line(raw)
                if line and _looks_like_spoken_answer(line, question):
                    return line
        return "Sorry, I didn't get that."

    def _recover_reply(
        self,
        spoken_user: str,
        memory_block: str = "",
        on_tool: Callable[[str, Any], str] | None = None,
    ) -> str:
        question = (spoken_user or "").strip() or _spoken_question(self.history, spoken_user)
        if not question:
            return "Sorry, I didn't catch that."
        direct = _try_direct_answer(question)
        if direct:
            return direct
        if _fresh_web_search(question) and on_tool:
            reply = self._answer_from_web_search(question, on_tool)
            if reply:
                return reply
        return self._generate_spoken_answer(question, memory_block=memory_block, on_tool=on_tool)

    def chat(
        self,
        user_text: str,
        memory_block: str = "",
        tools: list[dict[str, Any]] | None = None,
        on_tool: Callable[[str, Any], str] | None = None,
        on_thought: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
        max_rounds: int = 1,
    ) -> Iterator[str]:
        """Stream a spoken reply, running any tool the model asks for first."""
        spoken_user = user_text
        self.last_internal_thought = ""
        if self._tools_unsupported:
            tools = None
            on_tool = None
        self.history.append({"role": "user", "content": spoken_user})
        self._trim()
        if tools and on_tool and self._thinks() and not needs_agentic_tools(spoken_user) and not _try_direct_answer(spoken_user):
            tools = None
            on_tool = None
        agentic = bool(tools) and on_tool is not None
        tool_rounds = max(1, int(max_rounds)) if agentic else 0
        if needs_current_time(spoken_user) and on_tool:
            try:
                result = on_tool("get_current_time", {})
            except Exception as exc:
                result = f"Error: tool 'get_current_time' failed: {exc}"
            reply = _format_time_tool_result(result)
            if reply:
                self._append_internal_thought("Called get_current_time directly (skipped LLM).", on_thought)
                self.history.append({"role": "tool", "tool_name": "get_current_time", "content": result})
                self.history.append({"role": "assistant", "content": reply})
                yield reply
                return
        if _fresh_web_search(spoken_user) and on_tool:
            reply = self._answer_from_web_search(spoken_user, on_tool, on_thought)
            if reply:
                yield reply
                return
        direct = _try_direct_answer(spoken_user)
        if direct:
            self._append_internal_thought("Answered directly.", on_thought)
            self.history.append({"role": "assistant", "content": direct})
            yield direct
            return
        if self._thinks() and not agentic:
            reply = self._generate_spoken_answer(spoken_user, memory_block=memory_block, on_tool=on_tool)
            self._append_internal_thought("Answered with a direct generation pass.", on_thought)
            self.history.append({"role": "assistant", "content": reply})
            yield reply
            return
        force_final = False
        streamed_to_user = False
        for index in range(tool_rounds + 1):
                if cancel is not None and cancel.is_set():
                    return
                # The last pass drops the tools so the model has to answer in words.
                offered = None if force_final or index >= tool_rounds else tools
                system = self._system(with_tools=bool(offered), memory_block=memory_block)
                spoken: list[str] = []
                round_tools = offered
                spoken_before = 0
                try:
                    content, calls = yield from self._round(
                        system, round_tools, cancel, spoken, spoken_user, on_thought
                    )
                    if len(spoken) > spoken_before:
                        streamed_to_user = True
                except GeneratorExit:
                    # Caller stopped consuming (barge-in / hotkey). Keep what was
                    # already said so the next turn knows what Bob got through.
                    partial = "".join(spoken).strip()
                    if partial and not self._history_ends_with_assistant(partial):
                        self.history.append({"role": "assistant", "content": partial})
                    raise
                except RuntimeError as exc:
                    if offered and _is_tools_unsupported_error(str(exc)):
                        self._tools_unsupported = True
                        log.warning(
                            "Model %s does not support tools; continuing without tools",
                            self.model,
                        )
                        system = self._system(with_tools=False, memory_block=memory_block)
                        round_tools = None
                        content, calls = yield from self._round(
                            system, round_tools, cancel, spoken, spoken_user, on_thought
                        )
                    else:
                        raise
                if not calls and offered and on_tool and (
                    _is_tool_preamble(content) or _is_internal_monologue(content)
                ):
                    hinted = _deferral_tool_name(content, spoken_user)
                    if hinted:
                        try:
                            args = _deferral_tool_args(hinted, spoken_user)
                            result = on_tool(hinted, args)
                        except Exception as exc:
                            result = f"Error: tool '{hinted}' failed: {exc}"
                        if content.strip():
                            self.history.append({"role": "assistant", "content": content})
                        self.history.append({"role": "tool", "tool_name": hinted, "content": result})
                        continue
                if not calls and offered:
                    probe = _strip_control_tokens(_strip_think_blocks(content))
                    if probe and _is_useless_reply(probe, spoken_user):
                        if needs_current_time(spoken_user) and on_tool:
                            try:
                                result = on_tool("get_current_time", {})
                            except Exception as exc:
                                result = f"Error: tool 'get_current_time' failed: {exc}"
                            self.history.append({"role": "tool", "tool_name": "get_current_time", "content": result})
                            continue
                        if needs_chat_context(spoken_user) and not _fresh_web_search(spoken_user) and on_tool:
                            result = _invoke_conversation_log(on_tool)
                            self.history.append({"role": "tool", "tool_name": "conversation_log", "content": result})
                            continue
                        if _fresh_web_search(spoken_user) and on_tool:
                            result = _invoke_web_search(on_tool, spoken_user)
                            self.history.append({"role": "tool", "tool_name": "web_search", "content": result})
                            continue
                        continue
                if not calls and offered and content.strip() and _is_internal_monologue(content):
                    log.warning(
                        "Discarding internal monologue from tool round (%d chars, model=%s)",
                        len(content),
                        self.model,
                    )
                    if needs_current_time(spoken_user) and on_tool:
                        try:
                            result = on_tool("get_current_time", {})
                        except Exception as exc:
                            result = f"Error: tool 'get_current_time' failed: {exc}"
                        self.history.append({"role": "tool", "tool_name": "get_current_time", "content": result})
                        continue
                    if needs_chat_context(spoken_user) and not _fresh_web_search(spoken_user) and on_tool:
                        result = _invoke_conversation_log(on_tool)
                        self.history.append({"role": "tool", "tool_name": "conversation_log", "content": result})
                        continue
                    if _fresh_web_search(spoken_user) and on_tool:
                        result = _invoke_web_search(on_tool, spoken_user)
                        self.history.append({"role": "tool", "tool_name": "web_search", "content": result})
                        continue
                    direct = _try_direct_answer(spoken_user)
                    if direct:
                        self._append_internal_thought(
                            "Answered directly (skipped tool planning).",
                            on_thought,
                        )
                        yield direct
                        self.history.append({"role": "assistant", "content": direct})
                        break
                    force_final = True
                    self._append_internal_thought(
                        "Skipped tool planning; answering directly.",
                        on_thought,
                    )
                    continue
                if not calls and content.strip():
                    content = _finalize_spoken_reply(content, self.history, spoken_user)
                spoken_ok = bool(
                    content.strip()
                    and not _is_useless_reply(content, spoken_user)
                    and _looks_like_spoken_answer(content, spoken_user)
                )
                if not calls and not spoken_ok:
                    if needs_current_time(spoken_user) and on_tool:
                        try:
                            result = on_tool("get_current_time", {})
                        except Exception as exc:
                            result = f"Error: tool 'get_current_time' failed: {exc}"
                        self.history.append({"role": "tool", "tool_name": "get_current_time", "content": result})
                        content = _format_time_tool_result(result)
                    elif offered:
                        continue
                    else:
                        content = self._recover_reply(
                            spoken_user,
                            memory_block=memory_block,
                            on_tool=on_tool,
                        )
                        self._append_internal_thought(
                            "Initial model reply was unusable; regenerated a short answer.",
                            on_thought,
                        )
                    if content.strip() and not streamed_to_user:
                        yield content
                elif not calls and spoken_ok and round_tools:
                    yield content
                    streamed_to_user = True
                if content.strip() or calls:
                    message: dict[str, Any] = {"role": "assistant", "content": content}
                    if calls:
                        message["tool_calls"] = calls
                    self.history.append(message)
                if not calls:
                    break
                for call in calls:
                    if cancel is not None and cancel.is_set():
                        return
                    function = call.get("function") or {}
                    name = str(function.get("name") or "").strip()
                    if not name:
                        continue
                    try:
                        result = on_tool(name, function.get("arguments"))
                    except Exception as exc:
                        result = f"Error: tool '{name}' failed: {exc}"
                    self.history.append({"role": "tool", "tool_name": name, "content": result})
        self._trim()

    def _history_ends_with_assistant(self, content: str) -> bool:
        if not self.history:
            return False
        last = self.history[-1]
        return last.get("role") == "assistant" and (last.get("content") or "").strip() == content.strip()

    def _record_eval(self, data: dict[str, Any]) -> None:
        count = data.get("prompt_eval_count")
        dur = data.get("prompt_eval_duration")
        self.last_prompt_eval_count = int(count) if count is not None else None
        self.last_prompt_eval_ms = (float(dur) / 1e6) if dur is not None else None
        ntok = data.get("eval_count")
        edur = data.get("eval_duration")
        self.last_eval_count = int(ntok) if ntok is not None else None
        self.last_eval_ms = (float(edur) / 1e6) if edur is not None else None

    def _round(
        self,
        system: str,
        tools: list[dict[str, Any]] | None,
        cancel: threading.Event | None,
        spoken: list[str] | None = None,
        spoken_user: str = "",
        on_thought: Callable[[str], None] | None = None,
    ) -> Iterator[str]:
        """Stream one request. Returns (content, tool_calls) to the caller.

        Every chunk handed to the caller is also appended to `spoken` so an
        interrupted reply can still be recorded.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *[dict(msg) for msg in self.history]],
            "stream": True,
            "keep_alive": -1,
            "options": {
                "num_ctx": self.num_ctx,
                "num_predict": (
                    _THINKING_FINAL_NUM_PREDICT
                    if self._thinks() and not tools
                    else (_THINKING_CHAT_NUM_PREDICT if self._thinks() else _CHAT_NUM_PREDICT)
                ),
                "temperature": 0.4 if self._thinks() else 0.7,
            },
        }
        self._apply_think(payload)
        if tools:
            payload["tools"] = tools
        gate = _ThinkGate()
        calls: list[dict[str, Any]] = []
        first_token = True
        streamed = False
        thinking_chunks: list[str] = []
        t0 = time.perf_counter()
        with httpx.Client(timeout=STREAM_TIMEOUT) as client:
            with client.stream("POST", f"{self.host}/api/chat", json=payload) as resp:
                if resp.is_error:
                    detail = resp.read().decode("utf-8", errors="replace")
                    parsed = _ollama_error_body(detail, self.model)
                    raise RuntimeError(parsed or f"Ollama HTTP {resp.status_code}")
                for line in resp.iter_lines():
                    if cancel is not None and cancel.is_set():
                        break
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("error"):
                        raise RuntimeError(str(data["error"]))
                    message = data.get("message") or {}
                    thinking = message.get("thinking") or message.get("reasoning") or ""
                    if thinking:
                        thinking_chunks.append(str(thinking))
                    requested = message.get("tool_calls") or []
                    if requested:
                        calls.extend(requested)
                    piece = gate.add(message.get("content") or "")
                    if piece and not calls and not tools:
                        if first_token:
                            self.last_ttft_ms = (time.perf_counter() - t0) * 1000.0
                            first_token = False
                    if data.get("done"):
                        self._record_eval(data)
                        break
        raw_content = gate.visible()
        content = _finalize_spoken_reply(raw_content, self.history, spoken_user) if not tools else raw_content
        round_thought = _compose_internal_thought(
            "".join(thinking_chunks),
            raw_content,
            content,
            spoken_user,
        )
        if round_thought:
            self._append_internal_thought(round_thought, on_thought)
        cancelled = cancel is not None and cancel.is_set()
        leftover = ""
        if not streamed:
            leftover = content
            if not leftover.strip() and raw_content.strip() and not tools:
                leftover = _strip_control_tokens(_strip_think_blocks(raw_content)).strip()
        # Hold back tool-round narration while tools are offered.
        if not streamed and not calls and leftover:
            if tools and not cancelled:
                return raw_content, calls
            if first_token and leftover:
                self.last_ttft_ms = (time.perf_counter() - t0) * 1000.0
            if cancelled:
                if spoken is not None:
                    spoken.append(leftover)
                yield leftover
            elif leftover and not _is_useless_reply(leftover, spoken_user):
                speakable = (
                    not _is_internal_monologue(leftover)
                    and not _looks_like_meta_reply(leftover)
                    and _looks_like_spoken_answer(leftover, spoken_user)
                )
                if speakable:
                    if spoken is not None:
                        spoken.append(leftover)
                    streamed = True
                    yield leftover
        return content, calls

    def _trim(self) -> None:
        max_msgs = max(2, self.max_turns * 2)
        if len(self.history) <= max_msgs:
            return
        keep = self.history[-max_msgs:]
        # A tool result without the assistant turn that asked for it confuses Ollama.
        while keep and keep[0].get("role") == "tool":
            keep.pop(0)
        self.history, overflow = keep, self.history[: len(self.history) - len(keep)]
        self._fold_summary(overflow)

    def _fold_summary(self, overflow: list[dict[str, Any]]) -> None:
        """Fold trimmed history into the rolling summary on a background thread.

        This used to run synchronously inside chat(), so once the history hit
        max_turns every single reply waited on an extra LLM round-trip.
        """
        lines = [_transcript_line(msg) for msg in overflow]
        lines = [line for line in lines if line]
        if not lines:
            return
        threading.Thread(target=self._fold_worker, args=(lines,), name="summary", daemon=True).start()

    def _fold_worker(self, lines: list[str]) -> None:
        # Serialize folds so each one builds on the previous summary.
        with self._summary_lock:
            blob = "\n".join(([self.session_summary] if self.session_summary else []) + lines)[:4000]
            # Keep a compact rolling transcript. LLM summarization leaked its
            # instruction into live qwen3 replies ("summarize in 2-3 sentences").
            self.session_summary = blob[-800:]


def _transcript_line(msg: dict[str, Any]) -> str:
    role = msg.get("role")
    content = str(msg.get("content") or "").strip()
    if role == "user":
        return f"User: {content}"
    if role == "tool":
        return f"Tool {msg.get('tool_name') or 'result'}: {content}"
    used = [str((call.get("function") or {}).get("name") or "") for call in msg.get("tool_calls") or []]
    used = [name for name in used if name]
    if content and used:
        return f"BOB: {content} (used {', '.join(used)})"
    if used:
        return f"BOB used {', '.join(used)}"
    return f"BOB: {content}"
