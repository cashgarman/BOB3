from __future__ import annotations

from typing import Literal

from bob.tools.base import ToolContext
from bob.tools.registry import tool
from bob.voice_mood import list_moods

MoodName = Literal[
    "neutral",
    "calm",
    "warm",
    "upbeat",
    "excited",
    "serious",
    "sad",
    "sorry",
    "whisper",
    "hurried",
]


@tool
def set_speech_mood(mood: MoodName, *, ctx: ToolContext) -> str:
    """Set the spoken delivery for the rest of this reply. Call this before answering when the user's feelings or the news call for a different tone.

    Args:
        mood: How Bob should sound: neutral, calm, warm, upbeat, excited, serious, sad, sorry, whisper, or hurried.
    """
    # ctx.set_mood tells the voice pipeline (speed, pitch, gain, pauses).
    # The model should then speak in matching words and not mention the mood name.
    chosen = ctx.set_mood(str(mood))
    return f"Speaking {chosen} for this reply. Do not mention the mood by name; just answer in that tone."


@tool
def list_speech_moods() -> str:
    """List the voice moods Bob can speak in."""
    return "Available voice moods: " + ", ".join(list_moods()) + "."
