"""Brisk sample tools — hurried and serious delivery.

`running_late` uses the clock the way a real assistant would, then rushes the
spoken line. `status_brief` reads live settings in a clipped, serious tone.

Try asking Bob:
    "We're late, what's the time?"
    "Give me a serious status brief."
    "Hype me up, I got the job!"
"""

from __future__ import annotations

from datetime import datetime

from bob.tools import ToolContext, tool


@tool
def running_late(*, ctx: ToolContext) -> str:
    """Report the current local time in a rushed voice. Use this when the user is in a hurry, running late, or needs the time right now."""
    now = datetime.now().astimezone()
    hour = now.strftime("%I").lstrip("0") or "12"
    stamp = f"{hour}:{now:%M} {now:%p}"
    ctx.set_mood("hurried")
    return f"It is {stamp}. Move."


@tool
def status_brief(*, ctx: ToolContext) -> str:
    """Give a clipped status of which model, voice, and mood Bob is on. Use this for a serious briefing, a systems check, or 'what are you running'."""
    ctx.set_mood("serious")
    settings = ctx.settings
    if settings is None:
        return f"Tools are up. Spoken mood for this line is {ctx.mood}."
    return (
        f"Model {settings.llm_model}, voice {settings.tts_voice}, "
        f"default mood {getattr(settings, 'tts_mood', 'neutral')}. This reply is serious."
    )


@tool
def celebrate(*, ctx: ToolContext) -> str:
    """Cheer for a win: a job, a score, good news. Use this when the user is excited or asks you to celebrate."""
    ctx.set_mood("excited")
    return "Yes. That is a real win. Enjoy it for a second before the next thing."
