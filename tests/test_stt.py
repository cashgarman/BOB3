from __future__ import annotations

from types import SimpleNamespace

from bob.stt import clean_transcript, is_bad_transcript, _is_hallucination


def test_short_fillers_blocked_without_real_speech_context():
    assert is_bad_transcript("thank you")
    assert clean_transcript("thank you") == ""
    assert clean_transcript("bye") == ""


def test_short_fillers_allowed_when_user_spoke():
    assert not is_bad_transcript("thank you", allow_short_fillers=True)
    assert clean_transcript("thank you", allow_short_fillers=True) == "thank you"
    assert clean_transcript("bye", allow_short_fillers=True) == "bye"
    assert clean_transcript("good bye", allow_short_fillers=True) == "good bye"


def test_hallucination_loops_still_blocked_with_short_fillers():
    assert is_bad_transcript("you you you you", allow_short_fillers=True)
    assert clean_transcript("you you you you", allow_short_fillers=True) == ""


def test_bare_filler_hallucination_still_filtered_on_silence():
    seg = SimpleNamespace(no_speech_prob=0.9, avg_logprob=-1.0, compression_ratio=1.0)
    assert _is_hallucination(seg, "thank you", allow_short_fillers=False)
    # Extreme no-speech scores still drop fillers even in short-phrase mode.
    assert _is_hallucination(seg, "thank you", allow_short_fillers=True)


def test_bare_filler_allowed_when_whisper_heard_speech():
    seg = SimpleNamespace(no_speech_prob=0.2, avg_logprob=-0.3, compression_ratio=1.0)
    assert not _is_hallucination(seg, "thank you", allow_short_fillers=True)
    assert clean_transcript("thank you", allow_short_fillers=True) == "thank you"
