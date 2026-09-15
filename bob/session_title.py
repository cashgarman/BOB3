from __future__ import annotations

import logging
import re

import httpx

from bob.prompts import load_session_title_prompt

log = logging.getLogger(__name__)

TITLE_MAX = 80
TITLE_NUM_PREDICT = 64
_SNIPPET_MAX = 500

_LEAK_RE = re.compile(
    r"\b(output only|the title should|conversation title|no quotes|"
    r"3 to 8 words|descriptive title|session title|no preamble|no markdown)\b",
    re.IGNORECASE,
)
_PREFIX_RE = re.compile(r"^(?:title|chat|conversation)\s*:\s*", re.IGNORECASE)
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)


def sanitize_session_title(text: str) -> str:
    cleaned = _THINK_BLOCK_RE.sub("", text or "").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.splitlines()[0].strip()
    cleaned = cleaned.strip("\"'`“”‘’ ")
    cleaned = _PREFIX_RE.sub("", cleaned).strip()
    cleaned = cleaned.strip("*#_` ")
    cleaned = cleaned.rstrip(" .")
    if not cleaned or _LEAK_RE.search(cleaned):
        return ""
    if len(cleaned) > TITLE_MAX:
        trimmed = cleaned[:TITLE_MAX].rsplit(" ", 1)[0].strip()
        cleaned = trimmed or cleaned[:TITLE_MAX].rstrip()
    return cleaned


def fallback_session_title(user_text: str) -> str:
    return (user_text or "").strip()[:TITLE_MAX]


def generate_session_title(host: str, model: str, user_text: str, assistant_text: str) -> str:
    """Ask the local LLM for a short chat-list title; fall back to the first user line."""
    user = (user_text or "").strip()
    assistant = (assistant_text or "").strip()
    fallback = fallback_session_title(user)
    if not user:
        return fallback
    system = load_session_title_prompt()
    prompt = (
        f"User: {user[:_SNIPPET_MAX]}\n"
        f"BOB: {assistant[:_SNIPPET_MAX] or '(no reply yet)'}\n"
        "Title:"
    )
    try:
        raw = _post_title(host, model, system, prompt)
    except Exception as exc:
        log.warning("Session title generation failed: %s", exc)
        return fallback
    title = sanitize_session_title(raw)
    return title or fallback


def _post_title(host: str, model: str, system: str, user: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "options": {
            "num_predict": TITLE_NUM_PREDICT,
            "temperature": 0.3,
        },
    }
    url = f"{(host or 'http://127.0.0.1:11434').rstrip('/')}/api/chat"
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        body = response.json()
    message = body.get("message") or {}
    return _THINK_BLOCK_RE.sub("", str(message.get("content") or "")).strip()
