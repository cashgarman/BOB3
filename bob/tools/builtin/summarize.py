from __future__ import annotations

import re

import httpx

from bob.tools.base import ToolContext, ToolError
from bob.tools.registry import tool

HTTP_TIMEOUT = httpx.Timeout(60.0)
MAX_SOURCE_CHARS = 6000
# Give the model enough room to finish a multi-item list without truncation,
# but not so much that a runaway monologue burns the whole budget.
SUMMARIZE_NUM_PREDICT = 2048
SUMMARIZE_REPAIR_NUM_PREDICT = 1536

_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_MONOLOGUE_START_RE = re.compile(
    r"^(?:okay,?|so,?|hmm,?|well,?|alright,?)\b.{0,40}\b(user|asked|instructions?|"
    r"source material|remember|supposed to|need to)\b",
    re.IGNORECASE,
)
_MONOLOGUE_MARKERS_RE = re.compile(
    r"\b(the user asked|i need to|the instructions say|no planning|no preamble|"
    r"looking at the source|source material provided|reply with only|"
    r"i(?:['\u2019]ll| will) (?:turn|summarize)|let me|speak aloud|what to speak|"
    r"two sentences|no extra words|let me make sure|avoid mentioning|exactly what|"
    r"source material|output only|these instructions)\b",
    re.IGNORECASE,
)
_STRONG_MONOLOGUE_RE = re.compile(
    r"\b(speak aloud|what to speak|source material|no extra words|let me make sure|"
    r"avoid mentioning|output only|these instructions|two sentences)\b",
    re.IGNORECASE,
)


def _strip_think(text: str) -> str:
    return _THINK_BLOCK_RE.sub("", text or "").strip()


def _looks_like_monologue(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _MONOLOGUE_START_RE.search(t):
        return True
    if _STRONG_MONOLOGUE_RE.search(t):
        return True
    hits = len(_MONOLOGUE_MARKERS_RE.findall(t))
    return hits >= 2


def _extract_answer_after_monologue(text: str) -> str:
    """If a monologue trails off into the real answer, keep only that tail."""
    t = (text or "").strip()
    # Split on a line that looks like a transition into the actual list/answer.
    parts = re.split(r"\n\s*\n", t)
    for part in reversed(parts):
        part = part.strip()
        if part and not _looks_like_monologue(part) and len(part) >= 10:
            return part
    return ""


def _post_ollama(host: str, model: str, system: str, user: str, num_predict: int) -> str:
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"num_predict": num_predict, "temperature": 0.2},
        # Disabling "think" keeps reasoning out of the spoken answer entirely
        # for models that support it; harmless no-op for models that don't.
        "think": False,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(f"{host}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
    except httpx.TimeoutException as exc:
        raise ToolError("summarization took too long") from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"summarization failed: {exc}") from exc
    except ValueError as exc:
        raise ToolError("summarization returned invalid JSON") from exc
    message = body.get("message") or {}
    return _strip_think(str(message.get("content") or "")).strip()


def summarize_text(
    host: str,
    model: str,
    text: str,
    question: str = "",
    style: str = "brief",
) -> str:
    """Call Ollama to turn long source text into a short spoken answer.

    Retries once with a stricter repair prompt if the first pass leaks
    planning/monologue instead of a clean answer, so callers never have to
    speak raw "the user asked me to..." narration.
    """
    source = (text or "").strip()
    if not source:
        raise ToolError("nothing to summarize")
    host = (host or "http://127.0.0.1:11434").rstrip("/")
    model = (model or "qwen3:4b").strip()
    style_name = (style or "brief").strip().lower()
    bullets = style_name in {"bullets", "bullet", "list"}
    system = (
        "You turn source material into a short spoken answer for a voice assistant. "
        "Output ONLY the final answer text — the exact words to speak aloud. "
        "Never mention the user's request, tools, searches, or these instructions. "
        "Never explain what you are about to do. Start directly with the answer."
    )
    if bullets:
        system += " Use three to five short bullet points."
    else:
        system += " Use two or three natural sentences."
    user = f"Question: {(question or 'Summarize this.').strip()}\n\nSource material:\n{source[:MAX_SOURCE_CHARS]}"

    content = _post_ollama(host, model, system, user, SUMMARIZE_NUM_PREDICT)
    if content and not _looks_like_monologue(content) and content.rstrip()[-1:] in ".!?-\n":
        return content

    tail = _extract_answer_after_monologue(content)
    if tail and not _looks_like_monologue(tail):
        return tail

    # Repair pass: point out the exact failure and ask again with a harder rule.
    repair_system = (
        system
        + " Do not narrate your reasoning. Do not start with words like "
        "'Okay', 'So', or 'The user asked'. Respond with the answer only."
    )
    repair_user = user
    content = _post_ollama(host, model, repair_system, repair_user, SUMMARIZE_REPAIR_NUM_PREDICT)
    if content and not _looks_like_monologue(content) and content.rstrip()[-1:] in ".!?-\n":
        return content
    tail = _extract_answer_after_monologue(content)
    if tail and not _looks_like_monologue(tail):
        return tail
    if content.strip():
        raise ToolError("summarization kept narrating instead of answering")
    raise ToolError("summarization returned an empty answer")


@tool
def summarize_for_speech(
    text: str,
    question: str = "",
    style: str = "brief",
    *,
    ctx: ToolContext,
) -> str:
    """Summarize long text into a short spoken answer.

    Args:
        text: Material to summarize, such as web search results or notes.
        question: What the user asked, so the summary stays on topic.
        style: ``brief`` for sentences (default) or ``bullets`` for a short list.
    """
    if ctx.cancelled:
        raise ToolError("summarization was cancelled")
    settings = ctx.settings
    if settings is None:
        raise ToolError("summarization is not available")
    host = getattr(settings, "ollama_host", "http://127.0.0.1:11434")
    model = getattr(settings, "llm_model", "qwen3:4b")
    ctx.status("summarizing")
    return summarize_text(host, model, text, question=question, style=style)
