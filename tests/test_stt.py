from __future__ import annotations

from types import SimpleNamespace

from bob.stt import clean_transcript, is_allowed_short_phrase, is_bad_transcript, _is_hallucination


def test_short_fillers_blocked_without_real_speech_context():
    assert is_bad_transcript("thank you")
    assert clean_transcript("thank you") == ""
    assert clean_transcript("bye") == ""
    assert clean_transcript("you") == ""


def test_short_fillers_allowed_when_user_spoke():
    assert is_allowed_short_phrase("thank you")
    assert not is_bad_transcript("thank you", allow_short_fillers=True)
    assert clean_transcript("thank you", allow_short_fillers=True) == "thank you"
    assert clean_transcript("bye", allow_short_fillers=True) == "bye"
    assert clean_transcript("good bye", allow_short_fillers=True) == "good bye"


def test_bare_you_never_allowed_even_with_short_fillers():
    assert not is_allowed_short_phrase("you")
    assert is_bad_transcript("you", allow_short_fillers=True)
    assert clean_transcript("you", allow_short_fillers=True) == ""


def test_all_right_loops_rejected():
    text = "you All right. All right. All right."
    assert is_bad_transcript(text)
    assert clean_transcript(text) == ""
    assert is_bad_transcript("All right. All right. All right.")
    assert is_bad_transcript("all right all right all right")


def test_real_request_not_rejected():
    text = "Can you count from 1 to 10 for me please?"
    assert not is_bad_transcript(text)
    assert clean_transcript(text) == text


def test_stream_clean_decode_keeps_whitelisted_short_phrase():
    from bob.stt_stream import StreamingTranscriber

    stream = StreamingTranscriber(stt=object())  # type: ignore[arg-type]
    assert stream._clean_decode("thank you", allow_short=False) == "thank you"
    assert stream._clean_decode("you you you you", allow_short=False) == ""


def test_hallucination_loops_still_blocked_with_short_fillers():
    assert is_bad_transcript("you you you you", allow_short_fillers=True)
    assert clean_transcript("you you you you", allow_short_fillers=True) == ""


def test_bare_filler_hallucination_still_filtered_on_silence():
    seg = SimpleNamespace(no_speech_prob=0.9, avg_logprob=-1.0, compression_ratio=1.0)
    assert _is_hallucination(seg, "thank you", allow_short_fillers=False)
    assert _is_hallucination(seg, "thank you", allow_short_fillers=True)


def test_bare_filler_allowed_when_whisper_heard_speech():
    seg = SimpleNamespace(no_speech_prob=0.2, avg_logprob=-0.3, compression_ratio=1.0)
    assert not _is_hallucination(seg, "thank you", allow_short_fillers=True)
    assert clean_transcript("thank you", allow_short_fillers=True) == "thank you"
