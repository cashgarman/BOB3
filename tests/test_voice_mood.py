from __future__ import annotations

import numpy as np

from bob.voice_mood import (
    DEFAULT_MOOD,
    MOOD_NAMES,
    apply_mood_audio,
    list_moods,
    parse_mood,
    resolve_mood,
    strip_mood_tags,
    take_mood_tag,
    visible_reply,
)


def test_mood_resolve_and_aliases():
    assert resolve_mood(None) == DEFAULT_MOOD
    assert resolve_mood("Excited") == "excited"
    assert resolve_mood("happy") == "upbeat"
    assert resolve_mood("nope") == DEFAULT_MOOD
    assert parse_mood("whisper") == "whisper"
    assert parse_mood("nope") is None
    assert list_moods() == list(MOOD_NAMES)


def test_mood_tag_streaming():
    mood, rest, waiting = take_mood_tag("[mood:excited] Hello")
    assert mood == "excited"
    assert rest == "Hello"
    assert waiting is False

    mood, rest, waiting = take_mood_tag("[mood:exc")
    assert mood is None and waiting is True

    mood, rest, waiting = take_mood_tag("plain")
    assert mood is None and rest == "plain" and waiting is False


def test_strip_and_visible_reply():
    assert strip_mood_tags("[mood:calm] Hi [mood:sad] there") == "Hi  there"
    assert visible_reply("[mood:calm] Spoken") == "Spoken"
    assert visible_reply("[mood:") == ""


def test_apply_mood_audio_changes_signal():
    samples = np.ones(2400, dtype=np.float32) * 0.2
    out = apply_mood_audio(samples, "excited")
    assert out.dtype == np.float32
    assert out.size > 0
    # Pitch shift changes length and/or amplitude vs the original clip.
    assert out.size != samples.size or float(np.max(np.abs(out))) != float(np.max(np.abs(samples)))
