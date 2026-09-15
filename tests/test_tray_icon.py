from __future__ import annotations

from bob.state import State
from bob.ui.tray_icon import (
    ACCENT,
    animation_frames,
    render_icon,
    tray_title,
    uses_animation,
)


def test_tray_icon_colors():
    assert ACCENT[State.LOADING] == (249, 115, 22)
    assert ACCENT[State.IDLE] == (52, 211, 153)
    assert ACCENT[State.THINKING] == (59, 130, 246)


def test_render_icon_sizes():
    img = render_icon(State.IDLE)
    assert img.size == (64, 64)
    assert img.mode == "RGBA"


def test_animation_frames_for_loading_and_thinking():
    loading = animation_frames(State.LOADING)
    thinking = animation_frames(State.THINKING)
    assert len(loading) == len(thinking) == 8
    assert loading[0].tobytes() != loading[2].tobytes()
    assert thinking[0].tobytes() != thinking[2].tobytes()


def test_uses_animation_only_for_loading_and_thinking():
    assert uses_animation(State.LOADING) is True
    assert uses_animation(State.THINKING) is True
    assert uses_animation(State.IDLE) is False


def test_tray_title_for_ready_and_loading():
    assert tray_title(State.LOADING) == "BOB — Loading"
    assert tray_title(State.IDLE) == "BOB — Ready"
    assert tray_title(State.THINKING) == "BOB — Thinking"
