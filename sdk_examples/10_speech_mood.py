"""Example 10 - Colouring the spoken reply with a speech mood.

What this shows
---------------
Kokoro cannot take an "emotion" input, so Bob maps a small set of mood names
onto speaking rate, pitch, loudness, and pause length. A tool sets the mood
for the rest of the turn through `ToolContext`:

    ctx.set_mood("excited")   # raises ToolError on an unknown name
    ctx.mood                  # canonical name currently in effect

The voice pipeline also honours:

* the built-in `set_speech_mood` tool (the model calls this),
* a leading `[mood:excited]` tag on the spoken text (stripped before TTS).

Unknown labels such as "happy" are aliased (`happy` → `upbeat`). Anything
unrecognised raises from `set_mood` so the model can correct itself.

How to try it
-------------
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 10_speech_mood.py --schema
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 10_speech_mood.py --call celebrate_win
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 10_speech_mood.py --call break_bad_news subject="the flight"
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 10_speech_mood.py --chat
"""

from __future__ import annotations

from bob.tools import ToolContext, list_moods, tool


@tool
def celebrate_win(*, ctx: ToolContext) -> str:
    """React to good news from the user: a win, a compliment, something to cheer."""
    # Set the mood *before* returning so the spoken paraphrase of this result
    # (and the model's follow-up sentence) already uses the excited delivery.
    ctx.set_mood("excited")
    return "That's wonderful. Share the win in one short, upbeat sentence."


@tool
def break_bad_news(subject: str, *, ctx: ToolContext) -> str:
    """Help Bob deliver disappointing news gently.

    Args:
        subject: What went wrong, in a few words, for example "the reservation".
    """
    what = subject.strip() or "that"
    ctx.set_mood("sorry")
    return f"Speak gently about {what}. One short, kind sentence, no sugar-coating."


@tool
def hush(*, ctx: ToolContext) -> str:
    """Drop Bob's voice to a whisper, for secrets or late-night replies."""
    ctx.set_mood("whisper")
    return "Keep the next sentence very quiet."


@tool
def pick_mood(mood: str, *, ctx: ToolContext) -> str:
    """Set an explicit speech mood for the rest of this reply.

    Args:
        mood: One of neutral, calm, warm, upbeat, excited, serious, sad, sorry, whisper, hurried.
    """
    # `set_mood` already validates; this wrapper exists so example authors can
    # see the error path (`--call pick_mood mood=grumpy`).
    ctx.set_mood(mood)
    return f"Mood is {ctx.mood}. Available moods: {', '.join(list_moods())}."
