from __future__ import annotations

import math
from collections.abc import Sequence
from functools import lru_cache

from PIL import Image, ImageDraw

from bob.state import State

_ICON_SIZE = 64

# Tray/taskbar accent colors for BOB's lifecycle states.
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


@lru_cache(maxsize=1)
def _base_logo() -> Image.Image:
    from bob.win32_app import project_root

    path = project_root() / "packaging" / "logo.png"
    if path.is_file():
        return Image.open(path).convert("RGBA")
    return Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (255, 220, 0, 255))


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
        glow_r = 30 + int(4 * pulse)
        glow_alpha = int(50 + 160 * pulse)
        draw.ellipse(
            (cx - glow_r, cx - glow_r, cx + glow_r, cx + glow_r),
            outline=accent + (glow_alpha,),
            width=3,
        )

    if state == State.ERROR:
        ring_r = 30
        draw.ellipse(
            (cx - ring_r, cx - ring_r, cx + ring_r, cx + ring_r),
            outline=accent + (220,),
            width=3,
        )

    logo = _base_logo().resize((size - 8, size - 8), Image.Resampling.LANCZOS)
    img.alpha_composite(logo, dest=(4, 4))
    return img


def animation_frames(state: State) -> list[Image.Image]:
    return [render_icon(state, frame=i) for i in range(_ANIM_FRAMES)]


def tray_title(state: State, detail: str = "") -> str:
    labels = {
        State.LOADING: "BOB — Loading",
        State.IDLE: "BOB — Ready",
        State.LISTENING: "BOB — Listening",
        State.THINKING: "BOB — Thinking",
        State.SPEAKING: "BOB — Speaking",
        State.ERROR: "BOB — Error",
    }
    title = labels.get(state, "BOB")
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
