from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import httpx

from bob.prompts import load_answer_prompt, load_system_prompt, load_tool_guidance, load_tool_synthesis_prompt

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
    r"we are in the middle|middle of a conversation|"
    r"so bob should|(?:wait|hmm),?\s+(?:the|but|maybe|so)\b)",
    re.IGNORECASE,
)
_META_REPLY_RE = re.compile(
    r"\b(should say|should respond|should call|needs to call|the user|the tool|bob should|"
    r"the answer should be|answer should be|i should make sure|should make sure|"
    r"main point is|key here is|"
    r"in the background|perfect to share|matches their expectations|"
    r"explanation is in the background|share as the|"
    r"they(?:['’]ve| have) been|without overthinking|without caveats|"
    r"universally (?:acceptable|accepted)|pretend i|overthinking|no_think)\b",
    re.IGNORECASE,
)
_PLANNING_REPLY_RE = re.compile(
    r"\b(the answer should be|answer should be|i should make sure|should make sure|"
    r"in the background|perfect to share|that's perfect to|matches their expectations|"
    r"their actual need|they could be|they might be|deeper need might be|"
    r"explanation is in the background|share as the|for your use only|"
    r"background too|planned the reply|meant to be heard|design limitations|"
    r"reasoning process|i(?:'|')?m thinking about|let me think|i need to think|"
    r"might need improvement|would need improvement|still thinking about|"
    r"might improve later|improve later|answer later|will answer later)\b",
    re.IGNORECASE,
)
_THIRD_PERSON_SPOKEN_RE = re.compile(
    r"^(?:they|their|the user)\b",
    re.IGNORECASE,
)
_FRAGMENT_START_RE = re.compile(r"^(?:but|and|or|also)\b", re.IGNORECASE)
_META_SPOKEN_RE = re.compile(
    r"\bsince (?:i am|i'm) an ai\b|\bas an ai,? i\b|\bai model\b|\blanguage model\b|"
    r"\bin this role\b|\b(?:the )?persona\b|\bas bob\b|\(as bob\)|\(a character\)|"
    r"\bthe instruction\b|\binstruction says\b|\bgive the fact first\b|\bone extra detail\b|"
    r'\buse ["\']i["\'] and ["\']you["\']|\bresponded with\b|\bshould be consistent\b|'
    r"\bno planning\b|\bbackground notes\b|\bcharacter\),|\brole i am\b|"
    r"\bbut in this role\b|\bmeant to be heard\b",
    re.IGNORECASE,
)
_SPOKEN_OPENER_RE = re.compile(
    r"^(?:i\b|you\b|that|the|it|this|those|these|there|here|"
    r"well|sure|yeah|yes|no|nope|sorry|thanks|thank you|hmm|oh|right|maybe|probably|"
    r"hello|hi|hey|because|honestly|absolutely|not really|good question|let(?:'s| us)|lets|"
    r"got it|sounds like|fair point|i hear you|i understand|fair enough)\b",
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
_COUNT_BACK_RE = re.compile(r"\bcount\s+(?:down\s+|back\s+)?from\s+(\d+)\b", re.IGNORECASE)
_LOCATION_STATED_RE = re.compile(
    r"^\s*(?:i(?:['’]m| am) (?:in|from)|i live in)\s+(.+?)\s*$",
    re.IGNORECASE,
)


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


def _recent_prompt_edit_context(history: list[dict[str, Any]] | None) -> bool:
    recent: list[dict[str, Any]] = []
    for msg in reversed(history or []):
        if str(msg.get("role") or "") in {"user", "assistant"}:
            recent.append(msg)
        if len(recent) >= 6:
            break
    markers = (
        "system prompt",
        "background-notes",
        "background notes",
        "prompt file",
        "prompt files",
        "i'd trim",
        "i would trim",
        "i'd change",
        "i would change",
        "if i changed",
        "make one small edit",
        "trim the background",
        "edit my system prompt",
        "change your prompt",
    )
    for msg in recent:
        content = str(msg.get("content") or "").lower()
        if any(marker in content for marker in markers):
            return True
    return False


def wants_prompt_edit_followup(user_text: str, history: list[dict[str, Any]] | None = None) -> bool:
    """User approved a prompt change discussed in the previous turn."""
    t = (user_text or "").lower().strip()
    if not t or not _recent_prompt_edit_context(history):
        return False
    approval_phrases = (
        "go ahead",
        "do it",
        "do that",
        "make those changes",
        "make that change",
        "make the change",
        "apply that",
        "apply those",
        "apply the change",
        "yes please",
        "please do",
        "go for it",
        "sounds good",
        "update it",
        "change it now",
        "make the edit",
        "take those changes",
    )
    return any(phrase in t for phrase in approval_phrases)


def needs_prompt_files(user_text: str, history: list[dict[str, Any]] | None = None) -> bool:
    """User is asking about BOB's prompt templates or instructions on disk."""
    if wants_prompt_edit_followup(user_text, history):
        return True
    t = (user_text or "").lower()
    keys = (
        "system prompt",
        "system point",
        "system part",
        "your prompt",
        "your instructions",
        "tool guidance",
        "prompt file",
        "prompt files",
        "list prompt",
        "full prompt",
        "entire prompt",
        "my prompt",
        "edit my prompt",
        "change your prompt",
        "personality file",
        "instructions file",
    )
    if any(k in t for k in keys):
        return True
    return "prompt" in t and any(
        phrase in t for phrase in ("what is", "what's", "show", "read", "list", "tell me", "display")
    )


PROMPT_FILES_FOR_CONTEXT: tuple[str, ...] = (
    "prompts/system.txt",
    "prompts/answer.txt",
    "prompts/tool_guidance.txt",
    "prompts/tool_synthesis.txt",
    "prompts/session_title.txt",
)
PROMPT_FILE_FOR_REFLECT: tuple[str, ...] = ("prompts/system.txt",)


def wants_prompt_reflection(user_text: str) -> bool:
    t = (user_text or "").lower()
    if "prompt" not in t:
        return False
    keys = (
        "how do you feel",
        "what do you think",
        "would you change",
        "anything you would change",
        "your opinion",
        "reflect on",
        "critique",
        "improve",
        "feel about",
        "think about",
        "focus on",
        "your ideas",
        "those system",
        "those prompt",
        "main system prompt",
        "ideas of improving",
    )
    return any(k in t for k in keys)


def wants_prompt_edit(user_text: str, history: list[dict[str, Any]] | None = None) -> bool:
    """User wants BOB to change a prompt file on disk, not just discuss it."""
    if wants_prompt_edit_followup(user_text, history):
        return True
    t = (user_text or "").lower()
    if wants_prompt_reflection(user_text):
        return False
    edit_verbs = ("edit", "update", "change", "modify", "rewrite", "revise", "apply")
    if not any(verb in t for verb in edit_verbs):
        return False
    prompt_markers = (
        "system prompt",
        "your prompt",
        "my prompt",
        "prompt file",
        "instructions file",
        "instructions",
        "personality file",
        "tool guidance",
    )
    if any(marker in t for marker in prompt_markers):
        return True
    return "prompt" in t and any(word in t for word in ("your", "my", "the"))


def wants_prompt_catalog_list(user_text: str) -> bool:
    t = (user_text or "").lower()
    if wants_prompt_reflection(user_text) or wants_prompt_edit(user_text):
        return False
    return ("list" in t or "all my" in t or "all your" in t or "full system prompts" in t) and "prompt" in t


def wants_verbatim_system_prompt(user_text: str) -> bool:
    t = (user_text or "").lower()
    if wants_prompt_reflection(user_text) or wants_prompt_catalog_list(user_text) or wants_prompt_edit(user_text):
        return False
    if not any(marker in t for marker in ("system prompt", "system point", "system part")):
        return False
    return any(
        phrase in t
        for phrase in (
            "what is",
            "what's",
            "exact",
            "read your",
            "read the",
            "read my",
            "by reading",
            "show me your",
            "show your",
            "tell me your",
            "tell me what",
            "display",
            "contents",
        )
    )


def wants_full_prompt_content(user_text: str) -> bool:
    """Backward-compatible alias for callers that load system.txt."""
    return wants_verbatim_system_prompt(user_text)


def _prompt_reflect_has_substance(text: str) -> bool:
    """Reflection answers must state an opinion or concrete change, not defer."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if _PLANNING_REPLY_RE.search(t):
        return False
    if any(phrase in t for phrase in ("might improve", "improve later", "answer later")):
        return False
    opinion_markers = (
        "i think",
        "i like",
        "i'd",
        "i would",
        "works well",
        "helpful",
        "i'd change",
        "i would change",
        "if i changed",
        "shorter",
        "longer",
        "better",
        "add ",
        "remove ",
        "tone",
        "concise",
        "direct",
    )
    return any(marker in t for marker in opinion_markers)


_BACKGROUND_NOTES_RULE = (
    "Background notes and memory are for your use only — never repeat, summarize, "
    "or mention them unless the user explicitly asks."
)
_BACKGROUND_NOTES_RULE_SHORT = (
    "Background notes are for your use only — do not mention them unless the user asks."
)


def format_prompt_edit_fallback(system_text: str) -> tuple[str, str]:
    """Deterministic system-prompt edit when LLM synthesis fails."""
    body = (system_text or "").strip()
    if not body or body.startswith("Error"):
        return "", ""
    if _BACKGROUND_NOTES_RULE in body:
        updated = body.replace(_BACKGROUND_NOTES_RULE, _BACKGROUND_NOTES_RULE_SHORT, 1)
        return updated, "Done — I trimmed the background-notes rule in my system prompt."
    return body, ""


def _parse_prompt_edit_response(content: str) -> tuple[str, str]:
    text = _strip_think_blocks(content or "").strip()
    if not text:
        return "", ""
    if "\n---\n" in text:
        prompt, spoken = text.split("\n---\n", 1)
        return prompt.strip(), spoken.strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[1].strip(), parts[2].strip()
    return text, ""


def format_prompt_reflect_fallback(system_text: str) -> str:
    body = (system_text or "").strip()
    if body.startswith("Error") or not body:
        return (
            "I think my system prompt keeps me concise and spoken-friendly. "
            "I'd shorten the background-notes rule a little if I could."
        )
    if "two or three" in body.lower() or "spoken" in body.lower():
        return (
            "I think it's clear about keeping answers short and natural for voice. "
            "If I changed one thing, I'd trim the background-notes warning slightly."
        )
    return (
        "I think the prompt sets a helpful tone. "
        "I'd make one small edit to keep the spoken-answer rules even tighter."
    )


def format_prompt_catalog_reply(catalog: str) -> str:
    items: list[str] = []
    for line in (catalog or "").splitlines():
        if "|" not in line or "prompts/" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3:
            continue
        name = parts[0].lstrip("- ").replace("prompts/", "")
        purpose = parts[2]
        items.append(f"{name} ({purpose})")
    if items:
        return "My prompt files are " + "; ".join(items[:6]) + "."
    return "I could not load my prompt catalog."


def format_prompt_spoken_reply(user_text: str, catalog: str, system_text: str = "") -> str:
    body = (system_text or "").strip()
    if body and not body.startswith("Error"):
        lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("[")]
        spoken = " ".join(lines[:4])
        if len(spoken) > 500:
            spoken = spoken[:497].rsplit(" ", 1)[0] + "..."
        if spoken:
            return spoken
    names: list[str] = []
    for line in (catalog or "").splitlines():
        if "|" not in line or "prompts/" not in line:
            continue
        part = line.split("|", 1)[0].strip().lstrip("- ").strip()
        if part.startswith("prompts/"):
            names.append(part.replace("prompts/", ""))
    if names:
        return f"My prompt templates include {', '.join(names[:6])}."
    return "I could not load my prompt catalog."


def needs_agentic_tools(user_text: str) -> bool:
    """Only run tool-selection rounds when the user likely needs a tool."""
    if needs_prompt_files(user_text):
        return True
    if needs_current_time(user_text) or needs_conversation_log(user_text) or needs_calendar_context(user_text):
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
        "read file",
        "read the file",
        "write file",
        "create file",
        "create a file",
        "edit file",
        "open file",
        "save file",
        "list files",
        "system prompt",
        "your prompt",
        "your instructions",
        "personality",
        "tool guidance",
        "prompt file",
        "edit my prompt",
        "change your prompt",
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
        "doesn't include",
        "doesnt include",
        "didn't include",
        "didnt include",
        "that's not",
        "thats not",
        "that isn't",
        "that isnt",
        "that is not",
        "not what i",
        "not the right",
        "not correct",
        "you didn't",
        "you didnt",
        "you gave me",
        "last question",
        "last thing i asked",
        "previous question",
        "wrong answer",
        "that's wrong",
        "thats wrong",
        "try again",
        "do that again",
        "missing",
        "not include",
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


_CALENDAR_RE = re.compile(
    r"\b(season|what date|what's the date|whats the date|what day is it|"
    r"what month|what year is it|today's date|todays date|day of the week|"
    r"date today|today's day)\b",
    re.IGNORECASE,
)
_SORRY_FALLBACK_RE = re.compile(
    r"^sorry,?\s+i didn't (?:get|catch) that\.?$|^sorry,?\s+i got stuck for a moment\.?$",
    re.IGNORECASE,
)


def needs_calendar_context(user_text: str) -> bool:
    """Season/date questions need the clock, then a spoken interpretation."""
    return bool(_CALENDAR_RE.search(user_text or ""))


def is_failure_reply(text: str) -> bool:
    return bool(_SORRY_FALLBACK_RE.match((text or "").strip()))


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
    count = _COUNT_BACK_RE.search(t)
    if count:
        n = int(count.group(1))
        if 1 <= n <= 20:
            return ", ".join(str(i) for i in range(n, 0, -1)) + "."
    loc = _LOCATION_STATED_RE.search(t)
    if loc:
        place = loc.group(1).strip().rstrip(".!?")
        if 2 <= len(place) <= 80:
            return f"Got it, you're in {place}."
    return ""


_BAD_ANSWER_START_RE = re.compile(
    r"^(?:it covers|i recall(?: that)?|first,?|as bob,?|hmm,?|okay,?|the user|let me|"
    r"the extra detail|the sky being|i should|we are given|we are in|i need to|no extra|"
    r"since they\b|since the user\b|since we are\b|"
    r"so,?|wait,?|better not|best to|\"?\s*so the answer)\b",
    re.IGNORECASE,
)
_INSTRUCTION_ECHO_RE = re.compile(
    r"\b(no extra commentary|no extra words|direct answer only|spoken sentence|short natural sentence|"
    r"natural sentence ending|give the direct answer|no planning|meta commentary|"
    r"i must answer|i must reply|i need to respond|need to respond|"
    r"respond as bob|as bob,? i|one short natural sentence|one or two short sentences?|"
    r"reply aloud|middle of a conversation|"
    r"keep answers concise|background notes|must phrase it naturally|"
    r"shouldn't repeat|do not summarize aloud|for your use only|"
    r"meant to be heard aloud|say only the answer|speak aloud|what to speak|"
    r"two sentences|source material|let me make sure|avoid mentioning|exactly what)\b",
    re.IGNORECASE,
)
_INSTRUCTION_MONOLOGUE_RE = re.compile(
    r"\b(speak aloud|what to speak|two sentences|source material|no extra words|"
    r"let me make sure|exactly what|avoid mentioning|turn the source|short spoken answer|"
    r"output only|reply with only|never mention the user|these instructions|"
    r"the info from it)\b",
    re.IGNORECASE,
)
_INCOMPLETE_TAIL_WORDS = frozenset(
    {"also", "and", "but", "so", "then", "or", "just", "like", "with", "without", "plus"}
)
_SHORT_SPOKEN_WORDS = frozenset(
    {
        "yes",
        "no",
        "ok",
        "okay",
        "sure",
        "hello",
        "hi",
        "hey",
        "thanks",
        "sorry",
        "maybe",
        "right",
        "yep",
        "nope",
        "correct",
        "exactly",
        "indeed",
        "absolutely",
    }
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


def _is_instruction_monologue(text: str) -> bool:
    return bool(_INSTRUCTION_MONOLOGUE_RE.search(text or ""))


def _contains_unspoken_meta(text: str) -> bool:
    return bool(_META_SPOKEN_RE.search(text or ""))


def _looks_like_quoted_fragment(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t[0] in "\"'“‘":
        return True
    if re.search(r'\s-\sUse ["\']I["\']', t, re.IGNORECASE):
        return True
    return False


def _starts_like_spoken_reply(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SPOKEN_OPENER_RE.match(t):
        return True
    if re.match(r"^\d", t):
        return True
    if re.match(r"^[A-Z][a-z]+ (?:is|are|was|were|has|have|means)\b", t):
        return True
    return False


def _fallback_spoken_reply(question: str) -> str:
    """Short safe replies when the model only produces planning text."""
    t = (question or "").strip().lower()
    if re.search(r"\bhow (?:are you feeling|do you feel|you feeling)\b", t):
        return "I'm doing well, thanks for asking."
    if re.search(r"\bwhat does that mean\b", t):
        return "I meant I'm here to help you, not talk about how I work."
    if re.search(r"\b(?:bad responses?|not helpful|terrible|awful|useless|still responding)\b", t):
        return "You're right — sorry about that. I'll keep it simpler."
    return ""


def _looks_incomplete_spoken(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if t[-1] in ".!?":
        return False
    if _looks_like_bullet_list(t):
        return False
    words = t.split()
    if words and words[-1].lower().rstrip(",") in _INCOMPLETE_TAIL_WORDS:
        return True
    return len(t) > 40


def _looks_like_spoken_answer(text: str, question: str = "") -> bool:
    t = (text or "").strip()
    if not t or is_failure_reply(t):
        return False
    if (
        _echoes_prompt(t)
        or _contains_unspoken_meta(t)
        or _looks_like_quoted_fragment(t)
        or _INSTRUCTION_ECHO_RE.search(t)
        or _BAD_ANSWER_START_RE.search(t)
        or _is_instruction_monologue(t)
        or _is_planning_reply(t)
        or _looks_like_fragment_tail(t)
        or _looks_incomplete_spoken(t)
        or _looks_like_meta_reply(t)
        or _is_internal_monologue(t)
    ):
        return False
    if question and _is_useless_reply(t, question):
        return False
    if re.fullmatch(r"\d+\.?", t):
        return bool(
            question and (_MATH_PLUS_RE.search(question) or _MATH_TIMES_RE.search(question))
        )
    max_chars = _spoken_max_chars(question)
    if len(t) > max_chars:
        return False
    if _user_wants_bullets(question) and _looks_like_bullet_list(t):
        return True
    words = re.findall(r"[a-z0-9']+", t.lower())
    if len(words) == 1 and words[0] in _SHORT_SPOKEN_WORDS and len(t) <= 24:
        return True
    if t[-1] not in ".!?":
        return False
    if len(words) < 2 and not re.fullmatch(r"\d+\.?", t):
        return False
    if _starts_like_spoken_reply(t):
        return True
    return not re.match(r"^(?:since|first|okay|hmm|wait|so)\b", t, re.IGNORECASE)


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


def _echoes_user_text(reply: str, user_text: str) -> bool:
    """True when the reply mostly repeats what the user just said."""
    spoken = _normalize_for_compare(reply)
    asked = _normalize_for_compare(user_text)
    if not spoken or not asked:
        return False
    user_words = asked.split()
    for size in range(min(10, len(user_words)), 3, -1):
        for i in range(len(user_words) - size + 1):
            phrase = " ".join(user_words[i : i + size])
            if len(phrase) >= 18 and phrase in spoken:
                return True
    return False


def _is_useless_reply(reply: str, user_text: str) -> bool:
    spoken = _normalize_for_compare(reply)
    asked = _normalize_for_compare(user_text)
    if not spoken:
        return True
    if asked and spoken == asked:
        return True
    if asked and _echoes_user_text(reply, user_text):
        return True
    if asked and spoken.endswith(asked) and len(spoken) <= len(asked) + 16:
        return True
    if "/no_think" in (reply or "").lower() and len(spoken) <= max(len(asked) + 12, 24):
        return True
    if "season" in asked and not any(
        name in spoken for name in ("spring", "summer", "autumn", "fall", "winter")
    ):
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
    if _THIRD_PERSON_SPOKEN_RE.search(t):
        return True
    if _PLANNING_REPLY_RE.search(t):
        return True
    if _looks_like_meta_reply(t) and len(t) > 80:
        return True
    return len(t) > _TOOL_ROUND_MONOLOGUE_CHARS


def _looks_like_meta_reply(text: str) -> bool:
    return bool(_META_REPLY_RE.search(text or ""))


def _looks_like_fragment_tail(text: str) -> bool:
    return bool(_FRAGMENT_START_RE.search((text or "").strip()))


def _is_planning_reply(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _contains_unspoken_meta(t):
        return True
    if _THIRD_PERSON_SPOKEN_RE.search(t):
        return True
    return bool(_PLANNING_REPLY_RE.search(t)) or _looks_like_meta_reply(t)


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


def _extract_declared_answer(text: str) -> str:
    """Pull the spoken clause out of planning like 'the answer should be that ...'."""
    match = re.search(
        r"(?:the answer should be|i should say|bob should say|so the answer is)\s+(?:that\s+)?(.+)",
        text or "",
        re.IGNORECASE,
    )
    if not match:
        return ""
    answer = match.group(1).strip().strip('"').strip("'")
    return answer.rstrip(".,; ")


def _ensure_spoken_punctuation(text: str) -> str:
    t = (text or "").strip()
    if not t or t[-1] in ".!?" or _looks_like_bullet_list(t) or re.fullmatch(r"\d+", t):
        return t
    return f"{t}."


def _extract_first_person_sentence(text: str) -> str:
    for sentence in re.findall(r"[^.!?]+[.!?]", text or ""):
        line = sentence.strip().lstrip("\"' ")
        if re.match(r"^I\b", line, re.IGNORECASE) and not _is_planning_reply(line):
            return line
    return ""


def _coalesce_spoken_reply(raw: str, question: str) -> str:
    """Join consecutive spoken sentences instead of keeping a trailing fragment."""
    text = re.sub(r"\s+", " ", _strip_control_tokens(_strip_think_blocks(raw or "")).strip())
    sentences = [part.strip() for part in re.findall(r"[^.!?]+[.!?]", text) if part.strip()]
    if not sentences:
        return ""
    kept: list[str] = []
    for sentence in sentences:
        if _is_planning_reply(sentence) or _is_internal_monologue(sentence):
            continue
        if not kept and _looks_like_fragment_tail(sentence):
            continue
        kept.append(sentence)
        if len(kept) >= 3:
            break
    if not kept:
        return ""
    combined = " ".join(kept).strip()
    if _looks_like_spoken_answer(combined, question):
        return combined
    return ""


def _spoken_answer_candidates(raw: str, question: str) -> list[str]:
    text = _strip_control_tokens(_strip_think_blocks(raw or "")).strip()
    if not text:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in (
        _coalesce_spoken_reply(text, question),
        re.sub(r"\s+", " ", text).strip(),
        _extract_first_person_sentence(text),
        _extract_declared_answer(text),
        _extract_quoted_answer(text),
        _extract_best_spoken_sentence(text, question),
        _extract_last_short_line(text),
    ):
        item = (candidate or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    for sentence in reversed(re.findall(r"[^.!?]+[.!?]", text)):
        item = sentence.strip().lstrip("\"' ")
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _extract_best_spoken_sentence(text: str, question: str = "") -> str:
    """Pick the last sentence that looks like a spoken answer."""
    declared = _extract_declared_answer(text)
    if declared:
        if declared[-1] not in ".!?":
            declared += "."
        if _looks_like_spoken_answer(declared, question):
            return declared
    for sentence in reversed(re.findall(r"[^.!?]+[.!?]", text or "")):
        line = sentence.strip()
        if not line or len(line) > _SPOKEN_REPLY_MAX_CHARS:
            continue
        if _is_internal_monologue(line) or _is_instruction_monologue(line):
            continue
        if question and not _looks_like_spoken_answer(line, question):
            continue
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


_MONTH_TO_SEASON = {
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
    12: "winter",
}
_CALENDAR_STAMP_RE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),\s+(\d{4})",
    re.IGNORECASE,
)
_MONTH_INDEX = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _format_calendar_tool_result(question: str, raw: str) -> str:
    """Turn a clock tool stamp into a season/date answer, never a clock-only reply."""
    text = (raw or "").strip()
    match = _CALENDAR_STAMP_RE.search(text)
    if match:
        weekday, month_name, day, year = match.groups()
        month = _MONTH_INDEX[month_name.lower()]
    else:
        now = datetime.now()
        weekday, month_name, day, year, month = (
            now.strftime("%A"),
            now.strftime("%B"),
            str(now.day),
            str(now.year),
            now.month,
        )
    season = _MONTH_TO_SEASON[month]
    q = (question or "").lower()
    if "season" in q:
        return f"It's {season}."
    if "month" in q:
        return f"It's {month_name}."
    if "year" in q:
        return f"It's {year}."
    if "day" in q:
        return f"It's {weekday}, {month_name} {day}."
    return f"Today is {weekday}, {month_name} {day}, {year}."


def _fallback_from_tool_history(history: list[dict[str, Any]], user_text: str = "") -> str:
    calendar = needs_calendar_context(user_text)
    clock = needs_current_time(user_text)
    if not calendar and not clock:
        return ""
    for msg in reversed(history):
        if msg.get("role") != "tool":
            continue
        name = str(msg.get("tool_name") or "").strip()
        content = str(msg.get("content") or "").strip()
        if name == "get_current_time" and content:
            if calendar:
                return _format_calendar_tool_result(user_text, content)
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
    raw = _strip_control_tokens(_strip_think_blocks(raw_content or "")).strip()
    spoken = _strip_control_tokens(_strip_think_blocks(spoken_content or "")).strip()
    if thinking or (
        raw
        and (
            _is_internal_monologue(raw)
            or (spoken and raw != spoken)
            or (not spoken and not _looks_like_spoken_answer(raw, spoken_user))
        )
    ):
        parts.append("Planned the reply internally.")
    elif raw and spoken and raw == spoken and _looks_like_spoken_answer(raw, spoken_user):
        parts.append(raw)
    elif spoken_user and raw and _is_useless_reply(raw, spoken_user):
        parts.append("Evaluated the prompt internally (echo suppressed).")
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
    if _is_instruction_monologue(text):
        return ""
    declared = _extract_declared_answer(text)
    if declared:
        if declared[-1] not in ".!?":
            declared += "."
        if _looks_like_spoken_answer(declared, question):
            return declared
    quoted = _extract_quoted_answer(text)
    if quoted and _looks_like_spoken_answer(quoted, question):
        return quoted
    sentences = [part.strip() for part in re.findall(r"[^.!?]+[.!?]", text) if part.strip()]
    if sentences:
        joined = " ".join(sentences[:3]).strip()
        if joined and _looks_like_spoken_answer(joined, question):
            return joined
    return _extract_best_spoken_sentence(text, question)


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
    picked = _pick_spoken_answer(t, user_text)
    if picked:
        return picked
    if _looks_like_spoken_answer(t, user_text):
        if len(t) <= _SPOKEN_REPLY_MAX_CHARS:
            return t
        short = _extract_last_short_line(t)
        if short and _looks_like_spoken_answer(short, user_text):
            return short
        return t[:_SPOKEN_REPLY_MAX_CHARS].rsplit(" ", 1)[0].strip()
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


_SEARCH_COMPLAINT_KEYS = (
    "doesn't include",
    "doesnt include",
    "didn't include",
    "didnt include",
    "that's not",
    "thats not",
    "that isn't",
    "that isnt",
    "not what i",
    "wrong",
    "not the right",
    "not correct",
    "you didn't",
    "you didnt",
    "missing",
    "not include",
    "those aren't",
    "those are not",
    "that's not what",
    "thats not what",
)
_GENERIC_SEARCH_TITLES = (
    "bbc news - breaking news",
    "bbc home",
    "world | latest news",
    "bbc news - home",
    "breaking news, video and the latest top stories",
    "uk | latest news",
    "newspaper headlines:",
)
_ROUNDUP_HEADLINE_RE = re.compile(r"""['"]([^'"]{8,120})['"]""")


def _refine_web_search_query(query: str, user_text: str = "") -> str:
    q = (query or "").strip()
    context = f"{q} {user_text}".lower()
    if "bbc" in context and any(k in context for k in ("headline", "article", "news", "top", "story")):
        return "BBC News top headlines site:bbc.co.uk/news"
    if any(k in context for k in ("headline", "top story", "breaking news", "top news")):
        base = q or user_text.strip()
        return f"{base} top headlines today".strip()
    return q


def _prior_web_search_turn(history: list[dict[str, Any]]) -> tuple[str, str]:
    prior_user = ""
    search_results = ""
    for index in range(len(history) - 1, -1, -1):
        msg = history[index]
        if msg.get("role") != "tool" or msg.get("tool_name") != "web_search":
            continue
        search_results = str(msg.get("content") or "")
        for prev in range(index - 1, -1, -1):
            prior = history[prev]
            if prior.get("role") == "user":
                prior_user = str(prior.get("content") or "")
                break
        break
    return prior_user, search_results


def _is_web_search_followup(user_text: str, history: list[dict[str, Any]]) -> bool:
    prior_user, search_results = _prior_web_search_turn(history)
    if not prior_user or not search_results:
        return False
    t = (user_text or "").lower()
    if _user_wants_bullets(user_text) or any(
        k in t for k in ("rephrase", "say that again", "say it again", "bullet point")
    ):
        return False
    if any(k in t for k in _SEARCH_COMPLAINT_KEYS):
        return True
    if needs_chat_context(user_text) and any(
        k in t for k in ("headline", "article", "news", "result", "include", "stories")
    ):
        return True
    return False


def _web_search_followup_query(history: list[dict[str, Any]], user_text: str) -> str:
    prior_user, _ = _prior_web_search_turn(history)
    base = _web_search_query(prior_user) if prior_user else _web_search_query(user_text)
    return _refine_web_search_query(base or user_text, user_text)


def _is_generic_search_title(title: str) -> bool:
    t = title.lower().strip()
    if any(fragment in t for fragment in _GENERIC_SEARCH_TITLES):
        return True
    if t.startswith("bbc news -") and "headline" not in t:
        return True
    if "| latest news" in t and "updates" in t:
        return True
    return False


def _headlines_from_search_title(title: str) -> list[str]:
    t = (title or "").strip()
    if not t:
        return []
    if "newspaper headlines" in t.lower():
        parsed = [part.strip() for part in _ROUNDUP_HEADLINE_RE.findall(t) if part.strip()]
        parsed.sort(key=len, reverse=True)
        return parsed or [t]
    return [t]


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
        query = _refine_web_search_query(_web_search_query(user_text) or user_text, user_text)
        return {"query": query}
    return {}


def _invoke_web_search(
    on_tool: Callable[[str, Any], str],
    user_text: str = "",
    *,
    query: str | None = None,
) -> str:
    q = (query or _refine_web_search_query(_web_search_query(user_text) or user_text, user_text)).strip()
    try:
        return on_tool("web_search", {"query": q})
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
    if _is_internal_monologue(raw) or _is_instruction_monologue(raw):
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


def _search_result_titles(search_text: str, limit: int = 5) -> list[str]:
    titles: list[str] = []
    for line in (search_text or "").splitlines():
        line = line.strip()
        match = re.match(r"^\d+\.\s*(.+)", line)
        if not match:
            continue
        rest = match.group(1)
        title = re.split(r"\s+—\s+|\s+\(https?://", rest)[0].strip()
        for headline in _headlines_from_search_title(title):
            if not headline or _is_generic_search_title(headline):
                continue
            titles.append(headline)
            if len(titles) >= limit:
                return titles
    return titles


def _fallback_headlines_from_search(search_text: str, limit: int = 3) -> str:
    """Best-effort deterministic summary when the LLM summarizer fails outright."""
    titles = _search_result_titles(search_text, limit=limit)
    if not titles:
        return ""
    if len(titles) == 1:
        return f"Here's what I found: {titles[0]}."
    if len(titles) == 2:
        return f"Here's what I found: {titles[0]}, and {titles[1]}."
    return "Here's what I found: " + ", ".join(titles[:-1]) + f", and {titles[-1]}."


def _fallback_bullets_from_search(search_text: str, limit: int = 5) -> str:
    titles = _search_result_titles(search_text, limit=limit)
    if not titles:
        return ""
    return "\n".join(f"- {title}" for title in titles)


def _format_tool_results_block(tool_results: list[tuple[str, str]]) -> str:
    blocks: list[str] = []
    for name, content in tool_results:
        text = (content or "").strip()
        if not text:
            continue
        label = (name or "tool").replace("_", " ").strip()
        blocks.append(f"[{label}]\n{text[:_TOOL_SYNTHESIS_RESULT_CHARS]}")
    return "\n\n".join(blocks)


def _tool_synthesis_user_message(question: str, tool_block: str, memory_block: str = "") -> str:
    parts = [f"User question:\n{(question or '').strip()}"]
    if (memory_block or "").strip():
        parts.append(f"Background (for your use only — never read aloud):\n{memory_block.strip()}")
    parts.append(f"Tool results:\n{tool_block.strip()}")
    parts.append("Spoken answer:")
    return "\n\n".join(parts)


def _current_turn_tool_results(history: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Collect tool outputs appended since the latest user message."""
    results: list[tuple[str, str]] = []
    for msg in reversed(history):
        role = msg.get("role")
        if role == "user":
            break
        if role == "tool":
            name = str(msg.get("tool_name") or "tool")
            content = str(msg.get("content") or "").strip()
            if content:
                results.append((name, content))
    results.reverse()
    return results


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
_TOOL_SYNTHESIS_RESULT_CHARS = 2400
# Old qwen synthesis used a hard 320-token output cap and truncated mid-monologue.
_TOOL_SYNTHESIS_MIN_PREDICT = 1024
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
        self.compress_threshold = 0.40
        self.on_index_overflow: Callable[[list[dict[str, Any]]], None] | None = None
        self.last_turn_scores: dict[str, Any] = {}

    def context_usage(self) -> float | None:
        """Last prompt token count as a fraction of the configured context window."""
        count = self.last_prompt_eval_count
        if count is None or self.num_ctx <= 0:
            return None
        return min(1.0, max(0.0, count / float(self.num_ctx)))

    def _tool_synthesis_num_predict(self, *, bullets: bool = False, repair: bool = False) -> int:
        """Output token budget for tool-synthesis passes, scaled to num_ctx."""
        # Use up to half the context window for generation, never below 1024.
        budget = max(_TOOL_SYNTHESIS_MIN_PREDICT, min(int(self.num_ctx * 0.5), self.num_ctx - 512))
        if bullets:
            budget = max(budget, 1536)
        if repair:
            budget = max(_TOOL_SYNTHESIS_MIN_PREDICT, int(budget * 0.8))
        return budget

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

    def _answer_system(self, memory_block: str = "") -> str:
        """Answer-focused system prompt for one-shot chitchat generation."""
        parts = [load_answer_prompt()]
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

    def _tool_synthesis_messages(
        self,
        question: str,
        tool_results: list[tuple[str, str]],
        *,
        memory_block: str = "",
        history: list[dict[str, str]] | None = None,
        strict: bool = False,
    ) -> list[dict[str, str]]:
        tool_block = _format_tool_results_block(tool_results)
        system = load_tool_synthesis_prompt()
        if _user_wants_bullets(question):
            system += " Use three to five short bullet points."
        if strict:
            system += (
                " Do not narrate your reasoning. Do not mention tools, searches, or instructions. "
                "Respond with the answer only."
            )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append(
            {
                "role": "user",
                "content": _tool_synthesis_user_message(question, tool_block, memory_block),
            }
        )
        return messages

    def _synthesize_from_tools(
        self,
        question: str,
        tool_results: list[tuple[str, str]],
        *,
        memory_block: str = "",
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Turn tool outputs plus the user's question into one spoken answer."""
        question = (question or "").strip()
        usable = [(name, content) for name, content in tool_results if (content or "").strip()]
        if not question or not usable:
            return ""
        prior = history if history is not None else self._history_for_answer(question)
        bullets = _user_wants_bullets(question)
        for strict in (False, True):
            try:
                content, _thinking, _meta = self._post_chat(
                    self._tool_synthesis_messages(
                        question,
                        usable,
                        memory_block=memory_block,
                        history=prior,
                        strict=strict,
                    ),
                    num_predict=self._tool_synthesis_num_predict(bullets=bullets, repair=strict),
                    temperature=0.2,
                    think=False,
                )
            except Exception as exc:
                log.warning("Tool synthesis failed: %s", exc)
                return ""
            if _is_internal_monologue(content) or _is_instruction_monologue(content):
                continue
            reply = _spoken_from_tool_text(content, question, self.history)
            if reply:
                return reply
        return ""

    def _try_synthesize_current_tools(
        self,
        question: str,
        memory_block: str = "",
    ) -> str:
        tool_results = _current_turn_tool_results(self.history)
        if not tool_results:
            return ""
        return self._synthesize_from_tools(
            question,
            tool_results,
            memory_block=memory_block,
            history=self._history_for_answer(question),
        )

    def _prompt_reply_is_usable(self, reply: str, question: str, *, reflect: bool = False) -> bool:
        text = (reply or "").strip()
        if not text or text.startswith("Sorry"):
            return False
        if re.fullmatch(r"\d+\.?", text):
            return False
        if len(text) < 15:
            return False
        if _is_planning_reply(text):
            return False
        if reflect:
            return _prompt_reflect_has_substance(text) and not _contains_unspoken_meta(text)
        return _looks_like_spoken_answer(text, question)

    def synthesize_prompt_reply(
        self,
        question: str,
        tool_results: list[tuple[str, str]],
        *,
        reflect: bool,
        on_thought: Callable[[str], None] | None = None,
    ) -> str:
        """Turn loaded prompt files into a spoken list or reflection."""
        question = (question or "").strip()
        usable = [
            (name, content)
            for name, content in tool_results
            if (content or "").strip() and not str(content).strip().startswith("Error")
        ]
        if not question or not usable:
            return ""
        block = _format_tool_results_block(usable)
        base_reflect = (
            "You are BOB reviewing your own on-disk prompt template files. "
            "Answer in two or three natural spoken sentences meant to be heard aloud. "
            "State your opinion now and, if asked, one concrete change you would make. "
            "Do not read prompts verbatim, list file paths, or mention tools. "
            "Never say you are thinking, might improve later, or will answer later."
        )
        base_catalog = (
            "You are BOB. The user asked about your prompt template files. "
            "Briefly describe what each prompt file is for in two or three spoken sentences. "
            "Do not read them verbatim or mention file paths."
        )
        strict_suffix = (
            " Give the full answer immediately in complete sentences. "
            "Start with I think and include one specific change if improvements were requested."
        )
        for strict in (False, True):
            instruction = (base_reflect if reflect else base_catalog) + (strict_suffix if strict else "")
            messages: list[dict[str, str]] = [{"role": "system", "content": instruction}]
            messages.extend(self._history_for_answer(question))
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"User question:\n{question}\n\n{block}\n\n"
                        "Reply aloud in two or three short sentences."
                    ),
                }
            )
            try:
                content, _thinking, _meta = self._post_chat(
                    messages,
                    num_predict=220,
                    temperature=0.2,
                    think=False,
                )
            except Exception as exc:
                log.warning("Prompt reply synthesis failed: %s", exc)
                continue
            reply = _sanitize_spoken_reply(_strip_think_blocks(content or ""), self.history, question)
            if reply and self._prompt_reply_is_usable(reply, question, reflect=reflect):
                self._append_internal_thought(
                    "Reflected on the prompt files." if reflect else "Summarized the prompt files.",
                    on_thought,
                )
                self.history.append({"role": "assistant", "content": reply})
                return reply
        if reflect:
            system_text = ""
            for name, content in usable:
                if name.endswith("system.txt"):
                    system_text = content
                    break
            reply = format_prompt_reflect_fallback(system_text)
            if reply:
                self._append_internal_thought("Used a deterministic prompt reflection fallback.", on_thought)
                self.history.append({"role": "assistant", "content": reply})
                return reply
        return ""

    def _prompt_edit_is_usable(self, new_text: str, current_text: str) -> bool:
        candidate = (new_text or "").strip()
        current = (current_text or "").strip()
        if not candidate or candidate.startswith("Error"):
            return False
        if len(candidate) < 20:
            return False
        return candidate != current

    def synthesize_system_prompt_edit(
        self,
        question: str,
        current_text: str,
        *,
        on_thought: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """Revise prompts/system.txt and return (new_content, spoken_confirmation)."""
        question = (question or "").strip()
        current = (current_text or "").strip()
        if not question or not current or current.startswith("Error"):
            return "", ""
        base_instruction = (
            "You revise BOB's on-disk system prompt. "
            "Use recent conversation when the user says things like 'those changes'. "
            "Output exactly two sections separated by a line containing only ---\n"
            "Section 1: the complete new system prompt (plain text only)\n"
            "Section 2: two short spoken sentences confirming what changed (no paths, no markdown)"
        )
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": base_instruction + " Apply the requested edits now. Keep BOB's spoken voice-assistant tone.",
            }
        ]
        messages.extend(self._history_for_answer(question))
        messages.append(
            {
                "role": "user",
                "content": f"Current system prompt:\n{current}\n\nUser request:\n{question}",
            }
        )
        try:
            content, _thinking, _meta = self._post_chat(
                messages,
                num_predict=280,
                temperature=0.2,
                think=False,
            )
        except Exception as exc:
            log.warning("Prompt edit synthesis failed: %s", exc)
            return "", ""
        new_prompt, spoken = _parse_prompt_edit_response(content or "")
        spoken = _sanitize_spoken_reply(_strip_think_blocks(spoken), self.history, question)
        if self._prompt_edit_is_usable(new_prompt, current):
            self._append_internal_thought("Revised the system prompt on disk.", on_thought)
            if spoken and _looks_like_spoken_answer(spoken, question):
                self.history.append({"role": "assistant", "content": spoken})
            return new_prompt.strip(), spoken
        return "", ""

    def _finalize_tool_synthesis(
        self,
        question: str,
        memory_block: str = "",
        on_thought: Callable[[str], None] | None = None,
    ) -> str:
        reply = self._try_synthesize_current_tools(question, memory_block)
        if not reply:
            return ""
        self._append_internal_thought("Synthesized an answer from tool results.", on_thought)
        self.history.append({"role": "assistant", "content": reply})
        return reply

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
            body = r.json()
            self._record_eval(body)

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
            self._record_eval(body)
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
        *,
        query: str | None = None,
        thought: str = "Searched the web and synthesized a spoken answer from the results.",
    ) -> str:
        search = _invoke_web_search(on_tool, spoken_user, query=query)
        if not search.strip() or search.startswith("Error"):
            return ""
        self.history.append({"role": "tool", "tool_name": "web_search", "content": search})
        tool_results = [("web_search", search)]
        reply = self._synthesize_from_tools(
            spoken_user,
            tool_results,
            history=self._history_for_answer(spoken_user),
        )
        if not reply:
            if _user_wants_bullets(spoken_user):
                reply = _fallback_bullets_from_search(search)
            else:
                reply = _fallback_headlines_from_search(search)
        if reply:
            self._append_internal_thought(thought, on_thought)
            self.history.append({"role": "assistant", "content": reply})
            self._compact_history_tools()
        return reply

    def _chitchat_memory_block(self, question: str, memory_block: str) -> str:
        """Only inject long-term memory when the turn needs chat context."""
        if needs_chat_context(question):
            return memory_block
        return ""

    def _generate_spoken_answer(
        self,
        question: str,
        memory_block: str = "",
        on_tool: Callable[[str, Any], str] | None = None,
    ) -> str:
        question = (question or "").strip()
        if not question:
            return "Sorry, I didn't catch that."
        inject_memory = self._chitchat_memory_block(question, memory_block)
        messages = self._answer_messages(
            question,
            memory_block=inject_memory,
            history=self._history_for_answer(question),
        )
        messages[0] = {
            "role": "system",
            "content": (
                messages[0]["content"]
                + " Reply now as BOB in one or two short spoken sentences. "
                "Never mention AI, instructions, personas, or rules."
            ),
        }
        raw = ""
        for attempt, num_predict in enumerate((256, 384)):
            try:
                content, _thinking, _meta = self._post_chat(
                    messages,
                    num_predict=num_predict,
                    temperature=0.15 if attempt else 0.2,
                    think=False,
                )
            except Exception as exc:
                log.warning("Spoken answer failed: %s", exc)
                break
            raw = _strip_control_tokens(_strip_think_blocks(content or "")).strip()
            for candidate in _spoken_answer_candidates(raw, question):
                if _looks_like_spoken_answer(candidate, question):
                    return _ensure_spoken_punctuation(candidate)
        fallback = _fallback_spoken_reply(question)
        if fallback:
            return fallback
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
        fallback = _fallback_spoken_reply(question)
        if fallback:
            return fallback
        if needs_calendar_context(question) and on_tool:
            try:
                stamp = on_tool("get_current_time", {})
            except Exception:
                stamp = ""
            calendar = _format_calendar_tool_result(question, stamp)
            if calendar:
                return calendar
        if _fresh_web_search(question) and on_tool:
            reply = self._answer_from_web_search(question, on_tool)
            if reply:
                return reply
        if _is_web_search_followup(question, self.history) and on_tool:
            query = _web_search_followup_query(self.history, question)
            reply = self._answer_from_web_search(
                question,
                on_tool,
                query=query,
                thought="Retried the web search using your earlier request.",
            )
            if reply:
                return reply
        return self._generate_spoken_answer(
            question,
            memory_block=self._chitchat_memory_block(question, memory_block),
            on_tool=on_tool,
        )

    def chat(
        self,
        user_text: str,
        memory_block: str = "",
        tools: list[dict[str, Any]] | None = None,
        on_tool: Callable[[str, Any], str] | None = None,
        on_thought: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
        max_rounds: int = 1,
        runtime: Any | None = None,
    ) -> Iterator[str]:
        """Stream a spoken reply through the LangGraph turn brain."""
        from bob.agents.graph import stream_turn

        yield from stream_turn(
            self,
            user_text,
            memory_block=memory_block,
            tools=tools,
            on_tool=on_tool,
            on_thought=on_thought,
            cancel=cancel,
            max_rounds=max_rounds,
            runtime=runtime,
        )

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
                    _CHAT_NUM_PREDICT
                    if not tools
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
        if cancelled and leftover.strip() and not str(content or "").strip():
            return leftover.strip(), calls
        return content, calls

    def _compact_history_tools(self) -> None:
        from bob.context import compact_history

        self.history = compact_history(self.history, keep_recent_tools=1)

    def _manage_context(self) -> None:
        from bob.context import (
            compact_history,
            compress_session_transcript,
            fallback_compress_summary,
            should_compress,
            transcript_lines,
        )

        self.history = compact_history(self.history)
        if not should_compress(
            self.context_usage(),
            self.compress_threshold,
            self.history,
            self.num_ctx,
        ):
            return
        target = max(4, min(len(self.history) - 2, (self.max_turns // 2) * 2))
        if len(self.history) <= target:
            return
        keep = self.history[-target:]
        while keep and keep[0].get("role") == "tool":
            keep.pop(0)
        overflow = self.history[: len(self.history) - len(keep)]
        if not overflow:
            return
        self.history = keep
        self._index_overflow(overflow)
        lines = transcript_lines(overflow)
        try:
            summary = compress_session_transcript(self.host, self.model, self.session_summary, lines)
        except Exception as exc:
            log.warning("Session compression failed: %s", exc)
            summary = fallback_compress_summary(self.session_summary, lines)
        self.session_summary = summary

    def _index_overflow(self, overflow: list[dict[str, Any]]) -> None:
        if not overflow or self.on_index_overflow is None:
            return
        try:
            self.on_index_overflow(overflow)
        except Exception:
            log.debug("Session overflow indexing failed", exc_info=True)

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
        """Fold trimmed history into the rolling summary on a background thread."""
        from bob.context import transcript_line

        lines = [transcript_line(msg) for msg in overflow]
        lines = [line for line in lines if line]
        if not lines:
            return
        threading.Thread(
            target=self._fold_worker,
            args=(overflow, lines),
            name="summary",
            daemon=True,
        ).start()

    def _fold_worker(self, overflow: list[dict[str, Any]], lines: list[str]) -> None:
        from bob.context import compress_session_transcript, fallback_compress_summary

        self._index_overflow(overflow)
        with self._summary_lock:
            try:
                summary = compress_session_transcript(self.host, self.model, self.session_summary, lines)
            except Exception as exc:
                log.warning("Background session compression failed: %s", exc)
                summary = fallback_compress_summary(self.session_summary, lines)
            self.session_summary = summary


def _transcript_line(msg: dict[str, Any]) -> str:
    from bob.context import transcript_line

    return transcript_line(msg)
