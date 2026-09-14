from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts"

_FALLBACK_SYSTEM = (
    "You are Bob, a local voice assistant. Speak in short, natural sentences "
    "meant to be heard aloud. No markdown, bullet lists, or code fences unless "
    "the user asks. Keep answers concise."
)
_FALLBACK_TOOL_GUIDANCE = (
    "You can call tools. Use one only when it gives you something you cannot know on your own, "
    "such as the current time, the user's saved notes, or timestamps from this chat via "
    "conversation_log. "
    "When the user's feelings or the news call for it, call set_speech_mood first "
    "(calm, warm, upbeat, excited, serious, sad, sorry, whisper, hurried) and then answer; "
    "never say the mood name aloud. "
    "Never read tool names, arguments, or JSON aloud: once a tool returns, just say the answer "
    "in a short spoken sentence. "
    "Do not tell the user you are checking or looking something up — call the tool silently, "
    "then answer in one breath."
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


def load_tool_guidance() -> str:
    return _read("tool_guidance.txt", _FALLBACK_TOOL_GUIDANCE)


def save_system_prompt(text: str) -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    (PROMPTS_DIR / "system.txt").write_text((text or "").strip() + "\n", encoding="utf-8")
