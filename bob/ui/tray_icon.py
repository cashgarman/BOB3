from __future__ import annotations

import math
from collections.abc import Sequence

from PIL import Image, ImageDraw

from bob.state import State

_ICON_SIZE = 64
_BG = (17, 19, 24, 255)

# Tray/taskbar accent colors for Bob's lifecycle states.
ACCENT = {
    State.LOADING: (249, 115, 22),  # orange
    State.IDLE: (52, 211, 153),  # green
    State.LISTENING: (52, 211, 153),
    State.SPEAKING: (52, 211, 153),
    State.THINKING: (59, 130, 246),  # blue
    State.ERROR: (239, 68, 68),  # red
}

ANIMATED = {State.LOADING, State.THINKING}
_ANIM_FRAMES = 8


def _accent(state: State) -> tuple[int, int, int]:
    return ACCENT.get(state, ACCENT[State.IDLE])


def render_icon(state: State, frame: int = 0) -> Image.Image:
    accent = _accent(state)
    pulse = 0.0
    if state in ANIMATED:
        pulse = 0.35 + 0.65 * (0.5 + 0.5 * math.sin((frame / _ANIM_FRAMES) * 2 * math.pi))

    size = _ICON_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = size / 2

    if pulse > 0:
        glow_r = 27 + int(5 * pulse)
        glow_alpha = int(50 + 160 * pulse)
        draw.ellipse(
            (cx - glow_r, cx - glow_r, cx + glow_r, cx + glow_r),
            outline=accent + (glow_alpha,),
            width=3,
        )

    draw.ellipse((8, 8, 56, 56), fill=_BG, outline=accent + (255,), width=4)
    draw.ellipse((24, 22, 40, 42), fill=accent + (255,))
    draw.rectangle((30, 40, 34, 52), fill=accent + (255,))
    return img


def animation_frames(state: State) -> list[Image.Image]:
    return [render_icon(state, frame=i) for i in range(_ANIM_FRAMES)]


def tray_title(state: State, detail: str = "") -> str:
    labels = {
        State.LOADING: "Bob — Loading",
        State.IDLE: "Bob — Ready",
        State.LISTENING: "Bob — Listening",
        State.THINKING: "Bob — Thinking",
        State.SPEAKING: "Bob — Speaking",
        State.ERROR: "Bob — Error",
    }
    title = labels.get(state, "Bob")
    text = (detail or "").strip()
    if text and state not in {State.IDLE, State.LOADING}:
        if len(text) > 96:
            text = text[:95] + "…"
        return f"{title} — {text}"
    return title


def uses_animation(state: State) -> bool:
    return state in ANIMATED


def frame_interval_ms(state: State) -> int:
    if state == State.LOADING:
        return 450
    if state == State.THINKING:
        return 320
    return 400


def preload_frames(states: Sequence[State] | None = None) -> dict[State, list[Image.Image]]:
    wanted = list(states or ANIMATED)
    return {state: animation_frames(state) for state in wanted if state in ANIMATED}
