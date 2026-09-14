"""Playful sample tools — upbeat, excited, and warm delivery.

Drop this file in `data/tools/` (already there if you are reading the copy
Bob loads at boot). Each tool does real work, then colours the spoken reply
with `ctx.set_mood(...)` *before* it returns, so Kokoro uses that mood for
the rest of the turn.

Try asking Bob:
    "Tell me a joke."
    "Flip a coin for luck."
    "Give me a pep talk about the interview."
"""

from __future__ import annotations

import random

from bob.tools import ToolContext, tool

# Short enough to speak. The model will usually paraphrase; keep the punchline
# in the returned string so even a clumsy paraphrase still has something funny.
_JOKES = (
    "Why did the scarecrow get promoted? He was outstanding in his field.",
    "I told my computer I needed a break, and it said: no problem, I'll go to sleep.",
    "What do you call a fake noodle? An impasta.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I asked the librarian if the library had books on paranoia. She whispered, they're right behind you.",
)


@tool
def tell_joke(*, ctx: ToolContext) -> str:
    """Tell a short, clean joke. Use this when the user wants a laugh or to lighten the mood."""
    # Upbeat: a bit faster, brighter, shorter pauses. Set it first so the
    # model's spoken paraphrase of this result already sounds cheerful.
    ctx.set_mood("upbeat")
    return random.choice(_JOKES)


@tool
def flip_luck(*, ctx: ToolContext) -> str:
    """Flip a coin for luck and announce heads or tails. Use it for coin tosses, luck, or deciding yes or no."""
    # The *result* picks the mood: a win should sound different from a loss.
    # This is the pattern for any tool whose outcome has an emotional valence.
    if random.random() < 0.5:
        ctx.set_mood("excited")
        return "Heads. Lucky break."
    ctx.set_mood("sorry")
    return "Tails. Not your moment, but it was only a coin."


@tool
def pep_talk(about: str = "", *, ctx: ToolContext) -> str:
    """Give a short, sincere pep talk.

    Args:
        about: Optional topic, for example "the interview" or "today".
    """
    ctx.set_mood("warm")
    topic = about.strip().rstrip(".")
    if topic:
        return f"You can handle {topic}. Slow breath, then one clear next step."
    return "You can handle this. Slow breath, then one clear next step."
