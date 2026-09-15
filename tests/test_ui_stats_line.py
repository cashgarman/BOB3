from __future__ import annotations

from bob.ui.stats_line import format_usage_stats


def test_format_usage_stats_includes_context():
    text = format_usage_stats(gpu=0.4, vram=0.5, cpu=0.1, context=0.33)
    assert "GPU 40%" in text
    assert "VRAM 50%" in text
    assert "CPU 10%" in text
    assert "CONTEXT 33%" in text


def test_format_usage_stats_with_detail():
    text = format_usage_stats(detail="ollama", gpu=0.2, context=0.75)
    assert text.startswith("ollama")
    assert "GPU 20%" in text
    assert "CONTEXT 75%" in text
