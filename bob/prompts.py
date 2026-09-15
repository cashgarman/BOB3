from __future__ import annotations

from pathlib import Path

from bob.paths import project_root

ROOT = project_root()
PROMPTS_DIR = ROOT / "prompts"

_FALLBACK_SYSTEM = (
    "You are BOB, a local voice assistant. Speak in two or three natural sentences "
    "meant to be heard aloud. Lead with the answer, then add a brief extra detail. "
    "No markdown, bullet lists, or code fences unless the user asks. Background notes "
    "and memory are for your use only — never repeat, summarize, or mention them unless "
    "the user explicitly asks."
)
_FALLBACK_ANSWER = (
    "You are BOB. Answer in two or three spoken sentences. Give the fact first, "
    "then one extra detail."
)
_FALLBACK_TOOL_GUIDANCE = (
    "You can call tools. Use one only when it gives you something you cannot know on your own, "
    "such as the current time, the user's saved notes, or timestamps from this chat via "
    "conversation_log. "
    "When the user's feelings or the news call for it, call set_speech_mood first "
    "(calm, warm, upbeat, excited, serious, sad, sorry, whisper, hurried) and then answer; "
    "never say the mood name aloud. "
    "Never narrate your reasoning, planning, or tool selection aloud. "
    "Never read tool names, arguments, or JSON aloud: once a tool returns, just say the answer "
    "in a short spoken sentence. "
    "Do not tell the user you are checking or looking something up — call the tool silently, "
    "then answer in one breath."
)
_FALLBACK_TOOL_SYNTHESIS = (
    "You are BOB, a local voice assistant. The user asked a question and tools have already "
    "been run. Use the user's question, conversation history, background notes, and tool "
    "results to produce one short spoken answer. Output ONLY the exact words to speak aloud."
)


def _read(name: str, fallback: str) -> str:
    path = PROMPTS_DIR / name
    try:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    except OSError:
        pass
    return fallback


def load_system_prompt() -> str:
    return _read("system.txt", _FALLBACK_SYSTEM)


def load_answer_prompt() -> str:
    return _read("answer.txt", _FALLBACK_ANSWER)


def load_tool_guidance() -> str:
    return _read("tool_guidance.txt", _FALLBACK_TOOL_GUIDANCE)


def load_tool_synthesis_prompt() -> str:
    return _read("tool_synthesis.txt", _FALLBACK_TOOL_SYNTHESIS)


def save_system_prompt(text: str) -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    (PROMPTS_DIR / "system.txt").write_text((text or "").strip() + "\n", encoding="utf-8")
