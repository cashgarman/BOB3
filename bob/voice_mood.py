"""Speech moods: named delivery styles applied on top of the user's TTS voice.

Kokoro has no emotion input, so a mood is a bundle of speaking-rate, pitch,
loudness, and pause length. Tools call ``ctx.set_mood("excited")``; the model
can also call the built-in ``set_speech_mood`` tool or prefix a reply with
``[mood:excited]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

DEFAULT_MOOD = "neutral"

# Aliases the model (or a user) might send instead of the canonical name.
_ALIASES = {
    "default": "neutral",
    "normal": "neutral",
    "none": "neutral",
    "happy": "upbeat",
    "cheerful": "upbeat",
    "energetic": "excited",
    "hyped": "excited",
    "quiet": "whisper",
    "soft": "whisper",
    "fast": "hurried",
    "rushed": "hurried",
    "empathetic": "sorry",
    "apology": "sorry",
    "somber": "sad",
    "down": "sad",
    "stern": "serious",
    "gentle": "warm",
    "kind": "warm",
    "relaxed": "calm",
}


@dataclass(frozen=True)
class MoodProfile:
    """How a mood reshapes Kokoro's output relative to the user's settings."""

    name: str
    speed: float = 1.0  # multiplied by Settings.tts_speed, then clamped
    pitch: float = 0.0  # semitones; also slightly shortens/lengthens the clip
    gain_db: float = 0.0
    sentence_pause: float = 0.25  # seconds of silence Kokoro inserts at .!?
    clause_pause: float = 0.1


# Keep this list small and distinct: a 7B model will not use twelve near-synonyms.
MOODS: dict[str, MoodProfile] = {
    "neutral": MoodProfile("neutral"),
    "calm": MoodProfile("calm", speed=0.88, pitch=-0.4, gain_db=-1.0, sentence_pause=0.38, clause_pause=0.16),
    "warm": MoodProfile("warm", speed=0.94, pitch=-0.3, gain_db=0.6, sentence_pause=0.30, clause_pause=0.12),
    "upbeat": MoodProfile("upbeat", speed=1.08, pitch=0.8, gain_db=1.2, sentence_pause=0.18, clause_pause=0.08),
    "excited": MoodProfile("excited", speed=1.18, pitch=1.6, gain_db=2.2, sentence_pause=0.12, clause_pause=0.06),
    "serious": MoodProfile("serious", speed=0.92, pitch=-1.0, gain_db=0.0, sentence_pause=0.32, clause_pause=0.14),
    "sad": MoodProfile("sad", speed=0.82, pitch=-2.0, gain_db=-3.0, sentence_pause=0.42, clause_pause=0.18),
    "sorry": MoodProfile("sorry", speed=0.86, pitch=-1.1, gain_db=-1.5, sentence_pause=0.36, clause_pause=0.16),
    "whisper": MoodProfile("whisper", speed=0.90, pitch=0.8, gain_db=-9.0, sentence_pause=0.28, clause_pause=0.12),
    "hurried": MoodProfile("hurried", speed=1.28, pitch=0.5, gain_db=1.0, sentence_pause=0.10, clause_pause=0.05),
}

MOOD_NAMES = tuple(MOODS)
_TAG = re.compile(r"\[mood:\s*([A-Za-z][A-Za-z0-9_-]*)\s*\]", re.I)


def list_moods() -> list[str]:
    return list(MOOD_NAMES)


def resolve_mood(name: str | None, default: str = DEFAULT_MOOD) -> str:
    """Map a free-form label onto a canonical mood, or `default` if unknown."""
    if name is None:
        return default if default in MOODS else DEFAULT_MOOD
    key = str(name).strip().lower().replace(" ", "_")
    key = _ALIASES.get(key, key)
    if key in MOODS:
        return key
    return default if default in MOODS else DEFAULT_MOOD


def parse_mood(name: str | None) -> str | None:
    """Like resolve_mood but returns None when the label is not a known mood."""
    if name is None or not str(name).strip():
        return None
    key = str(name).strip().lower().replace(" ", "_")
    key = _ALIASES.get(key, key)
    return key if key in MOODS else None


def profile_for(name: str | None) -> MoodProfile:
    return MOODS[resolve_mood(name)]


def apply_mood_audio(samples: np.ndarray, mood: str | MoodProfile | None) -> np.ndarray:
    """Pitch-shift and gain a waveform. Speed/pauses are applied at synthesis time."""
    profile = mood if isinstance(mood, MoodProfile) else profile_for(mood)
    out = np.asarray(samples, dtype=np.float32)
    if out.size == 0:
        return out
    if profile.pitch:
        factor = 2.0 ** (profile.pitch / 12.0)
        old_n = int(out.size)
        new_n = max(1, int(round(old_n / factor)))
        out = np.interp(np.linspace(0, old_n - 1, new_n), np.arange(old_n), out).astype(np.float32)
    if profile.gain_db:
        out = out * (10.0 ** (profile.gain_db / 20.0))
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.99:
        out = out * (0.99 / peak)
    return out


def take_mood_tag(buffer: str) -> tuple[str | None, str, bool]:
    """Pull a leading ``[mood:name]`` off a streaming buffer.

    Returns ``(mood_or_none, remainder, waiting)``. ``waiting`` is True when the
    buffer looks like the start of a tag but the closing ``]`` has not arrived,
    so the caller should not send those characters to TTS yet.
    """
    lead = (buffer or "").lstrip()
    lower = lead.lower()
    if lower.startswith("[mood:"):
        end = lead.find("]")
        if end < 0:
            return None, buffer, True
        raw = lead[6:end].strip()
        rest = lead[end + 1 :].lstrip()
        return (parse_mood(raw) or raw), rest, False
    # Incomplete prefix of the tag, e.g. "[mo" — hold it.
    if lead.startswith("[") and "mood:".startswith(lead[1:].lower()) and "]" not in lead:
        return None, buffer, True
    return None, buffer, False


def strip_mood_tags(text: str) -> str:
    """Remove every ``[mood:…]`` marker so it is never spoken or stored."""
    return _TAG.sub("", text or "").strip()


def visible_reply(text: str) -> str:
    """Text for the overlay: tags gone, and an unfinished tag hidden."""
    _mood, rest, waiting = take_mood_tag(text or "")
    if waiting:
        return ""
    return strip_mood_tags(rest)
