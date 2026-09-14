"""Quiet sample tools — calm, whisper, sorry, and sad delivery.

These are the opposite of the playful set: slower rate, softer gain, longer
pauses. `whisper_reminder` also writes to the notes file so you can hear a
mood *and* see a side effect.

Try asking Bob:
    "Walk me through a breath."
    "Whisper a reminder to lock the back door."
    "I had a rough day, can you sit with that?"
    "Something sad happened."
"""

from __future__ import annotations

from bob.tools import ToolContext, ToolError, tool

_MAX_NOTE = 200


@tool
def guided_breath(rounds: int = 1, *, ctx: ToolContext) -> str:
    """Lead a short breathing exercise. Use this when the user is stressed, anxious, or asks to calm down.

    Args:
        rounds: How many slow breaths to describe, from 1 to 3.
    """
    count = max(1, min(int(rounds), 3))
    ctx.set_mood("calm")
    if count == 1:
        return "Breathe in for four, hold for four, out for four. That is one round."
    return f"Breathe in for four, hold for four, out for four. Repeat that {count} times."


@tool
def whisper_reminder(text: str, *, ctx: ToolContext) -> str:
    """Save a quiet reminder to the user's notes and speak it softly. Use this for secrets, late night, or 'don't wake anyone'.

    Args:
        text: The reminder to store and whisper back.
    """
    note = text.strip().rstrip(".")
    if not note:
        raise ToolError("tell me what to whisper")
    if len(note) > _MAX_NOTE:
        note = note[:_MAX_NOTE].rstrip()
    # Same notes file the built-in notes_write tool uses.
    path = ctx.data_dir / "notes.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(f"{existing.rstrip()}\nwhisper: {note}\n" if existing.strip() else f"whisper: {note}\n", encoding="utf-8")
    ctx.set_mood("whisper")
    return f"Reminder saved: {note}."


@tool
def comfort(situation: str = "", *, ctx: ToolContext) -> str:
    """Offer a short, kind response when the user is upset, disappointed, or asking for comfort.

    Args:
        situation: Optional what went wrong, for example "the interview" or "a fight".
    """
    ctx.set_mood("sorry")
    what = situation.strip().rstrip(".")
    if what:
        return f"That sounds hard, about {what}. I am here. We can take this one small step at a time."
    return "That sounds hard. I am here. We can take this one small step at a time."


@tool
def sit_with_sadness(*, ctx: ToolContext) -> str:
    """Speak slowly and quietly when the user is grieving or names something truly sad. Do not use this for mild disappointment."""
    # Sad is lower and slower than sorry. Keep the returned line short so the
    # model does not pile on platitudes in a mismatched upbeat voice.
    ctx.set_mood("sad")
    return "I hear you. We do not have to fix it right now."
