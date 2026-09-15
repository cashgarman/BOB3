"""UI theme: colour slots, presets, user overrides, and live restyling.

A :class:`Theme` is a flat set of named colours plus a font family and a CTk
appearance mode.  Presets live in :data:`PRESETS`; the user picks one in
``config.yaml`` (``theme``) and may override individual slots
(``theme_overrides``).  Windows read colours from :func:`current` when they are
built and call :func:`restyle` when the theme changes so the switch is live.
"""

from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields, replace
from typing import Any

import customtkinter as ctk

from bob.state import State

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# (slot, label shown in the theme editor)
COLOR_SLOTS: tuple[tuple[str, str], ...] = (
    ("bg", "Window background"),
    ("surface", "Panels"),
    ("surface_alt", "Panels (secondary)"),
    ("border", "Borders"),
    ("text", "Text"),
    ("text_muted", "Muted text"),
    ("accent", "Accent"),
    ("accent_hover", "Accent (hover)"),
    ("on_accent", "Text on accent"),
    ("danger", "Danger"),
    ("you", "Transcript: You"),
    ("bob", "Transcript: BOB"),
    ("idle", "State: idle"),
    ("listening", "State: listening"),
    ("thinking", "State: thinking"),
    ("speaking", "State: speaking"),
    ("loading", "State: loading"),
    ("error", "State: error"),
)
COLOR_KEYS = tuple(slot for slot, _ in COLOR_SLOTS)
APPEARANCE_MODES = ("dark", "light")
FONT_SUGGESTIONS = (
    "Segoe UI",
    "Segoe UI Variable",
    "Calibri",
    "Arial",
    "Verdana",
    "Georgia",
    "Cambria",
    "Consolas",
    "Cascadia Code",
    "Courier New",
)


@dataclass(frozen=True)
class Theme:
    key: str
    title: str
    appearance: str = "dark"
    font_family: str = "Segoe UI"
    bg: str = "#111318"
    surface: str = "#1c1c1e"
    surface_alt: str = "#1f2937"
    border: str = "#2a2f3a"
    text: str = "#e5e7eb"
    text_muted: str = "#6b7280"
    accent: str = "#34d399"
    accent_hover: str = "#10b981"
    on_accent: str = "#052e1c"
    danger: str = "#7f1d1d"
    you: str = "#93c5fd"
    bob: str = "#6ee7b7"
    idle: str = "#9aa0a6"
    listening: str = "#34d399"
    thinking: str = "#fbbf24"
    speaking: str = "#60a5fa"
    loading: str = "#a78bfa"
    error: str = "#f87171"

    # -- lookups -------------------------------------------------------------

    def state_color(self, state: State) -> str:
        return getattr(self, state.value, self.idle)

    def font(self, size: int, weight: str | None = None) -> tuple:
        if weight:
            return (self.font_family, size, weight)
        return (self.font_family, size)

    def color(self, slot: str) -> str:
        return getattr(self, slot)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    # -- widget kwargs ---------------------------------------------------------
    # Each returns keyword arguments accepted both by the CTk constructor and by
    # ``configure`` so windows can use them at build time and during restyle.

    def window(self) -> dict[str, Any]:
        return {"fg_color": self.bg}

    def label_style(self, muted: bool = False) -> dict[str, Any]:
        return {"text_color": self.text_muted if muted else self.text}

    def button(self, role: str = "accent") -> dict[str, Any]:
        if role == "danger":
            return {
                "fg_color": self.danger,
                "hover_color": _shade(self.danger, 0.85),
                "text_color": "#ffffff",
                "border_color": self.danger,
            }
        if role == "surface":
            return {
                "fg_color": self.surface_alt,
                "hover_color": _shade(self.surface_alt, 1.2 if self.appearance == "dark" else 0.92),
                "text_color": self.text,
                "border_color": self.border,
            }
        if role == "surface_off":
            return {
                "fg_color": self.surface,
                "hover_color": self.surface_alt,
                "text_color": self.text_muted,
                "border_color": self.border,
            }
        return {
            "fg_color": self.accent,
            "hover_color": self.accent_hover,
            "text_color": self.on_accent,
            "border_color": self.accent,
        }

    def entry(self) -> dict[str, Any]:
        return {
            "fg_color": self.surface,
            "border_color": self.border,
            "text_color": self.text,
            "placeholder_text_color": self.text_muted,
        }

    def combo(self) -> dict[str, Any]:
        return {
            "fg_color": self.surface,
            "border_color": self.border,
            "text_color": self.text,
            "button_color": self.surface_alt,
            "button_hover_color": self.accent,
            "dropdown_fg_color": self.surface,
            "dropdown_hover_color": self.surface_alt,
            "dropdown_text_color": self.text,
        }

    def check(self) -> dict[str, Any]:
        return {
            "fg_color": self.accent,
            "hover_color": self.accent_hover,
            "checkmark_color": self.on_accent,
            "text_color": self.text,
            "border_color": self.border,
        }

    def textbox(self) -> dict[str, Any]:
        return {
            "fg_color": self.surface,
            "text_color": self.text,
            "border_color": self.border,
            "scrollbar_button_color": self.surface_alt,
            "scrollbar_button_hover_color": self.text_muted,
        }

    def progress(self, color: str | None = None) -> dict[str, Any]:
        return {"fg_color": self.surface_alt, "progress_color": color or self.accent}

    def scroll_frame(self) -> dict[str, Any]:
        return {
            "fg_color": "transparent",
            "scrollbar_button_color": self.surface_alt,
            "scrollbar_button_hover_color": self.text_muted,
        }

    def frame(self) -> dict[str, Any]:
        return {"fg_color": self.surface, "border_color": self.border}


def _shade(hex_color: str, factor: float) -> str:
    """Lighten (>1) or darken (<1) a hex colour."""
    rgb = _to_rgb(hex_color)
    if rgb is None:
        return hex_color
    out = tuple(max(0, min(255, int(round(c * factor)))) for c in rgb)
    return "#%02x%02x%02x" % out


def _to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    if not isinstance(hex_color, str) or not HEX_RE.match(hex_color):
        return None
    h = hex_color[1:]
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def normalize_hex(value: Any) -> str | None:
    """Return ``#rrggbb`` (lower-case) or ``None`` if *value* is not a colour."""
    rgb = _to_rgb(str(value).strip() if value is not None else "")
    if rgb is None:
        return None
    return "#%02x%02x%02x" % rgb


# --------------------------------------------------------------------------- presets

PRESETS: dict[str, Theme] = {
    t.key: t
    for t in (
        Theme(key="midnight", title="Midnight"),
        Theme(
            key="ocean",
            title="Ocean",
            bg="#0b1622",
            surface="#12202f",
            surface_alt="#1b2d40",
            border="#24405a",
            text="#dbe9f4",
            text_muted="#6f8aa3",
            accent="#38bdf8",
            accent_hover="#0ea5e9",
            on_accent="#06202f",
            danger="#7f1d1d",
            you="#7dd3fc",
            bob="#5eead4",
            idle="#8da2b5",
            listening="#22d3ee",
            thinking="#fbbf24",
            speaking="#60a5fa",
            loading="#a78bfa",
            error="#fb7185",
        ),
        Theme(
            key="ember",
            title="Ember",
            bg="#16110f",
            surface="#221916",
            surface_alt="#2f221d",
            border="#44302a",
            text="#f3e9e3",
            text_muted="#8f7b72",
            accent="#fb923c",
            accent_hover="#f97316",
            on_accent="#2a1204",
            danger="#7f1d1d",
            you="#fdba74",
            bob="#fcd34d",
            idle="#a09088",
            listening="#fb923c",
            thinking="#facc15",
            speaking="#f472b6",
            loading="#c084fc",
            error="#f87171",
        ),
        Theme(
            key="forest",
            title="Forest",
            bg="#0f1512",
            surface="#17201b",
            surface_alt="#1f2b24",
            border="#2c3d33",
            text="#e3ede6",
            text_muted="#6f857a",
            accent="#4ade80",
            accent_hover="#22c55e",
            on_accent="#052e16",
            danger="#7f1d1d",
            you="#86efac",
            bob="#a3e635",
            idle="#8fa398",
            listening="#4ade80",
            thinking="#fde047",
            speaking="#67e8f9",
            loading="#c4b5fd",
            error="#fb7185",
        ),
        Theme(
            key="dracula",
            title="Dracula",
            bg="#282a36",
            surface="#21222c",
            surface_alt="#343746",
            border="#44475a",
            text="#f8f8f2",
            text_muted="#6272a4",
            accent="#bd93f9",
            accent_hover="#a97bf0",
            on_accent="#1e1f29",
            danger="#8b2c2c",
            you="#8be9fd",
            bob="#50fa7b",
            idle="#6272a4",
            listening="#50fa7b",
            thinking="#f1fa8c",
            speaking="#8be9fd",
            loading="#bd93f9",
            error="#ff5555",
        ),
        Theme(
            key="nord",
            title="Nord",
            bg="#2e3440",
            surface="#3b4252",
            surface_alt="#434c5e",
            border="#4c566a",
            text="#eceff4",
            text_muted="#8f99ad",
            accent="#88c0d0",
            accent_hover="#81a1c1",
            on_accent="#2e3440",
            danger="#bf616a",
            you="#81a1c1",
            bob="#a3be8c",
            idle="#8f99ad",
            listening="#a3be8c",
            thinking="#ebcb8b",
            speaking="#88c0d0",
            loading="#b48ead",
            error="#bf616a",
        ),
        Theme(
            key="paper",
            title="Paper (light)",
            appearance="light",
            bg="#f7f7f5",
            surface="#ffffff",
            surface_alt="#ececea",
            border="#d6d6d2",
            text="#1f2937",
            text_muted="#6b7280",
            accent="#2563eb",
            accent_hover="#1d4ed8",
            on_accent="#ffffff",
            danger="#b91c1c",
            you="#1d4ed8",
            bob="#047857",
            idle="#6b7280",
            listening="#059669",
            thinking="#d97706",
            speaking="#2563eb",
            loading="#7c3aed",
            error="#dc2626",
        ),
        Theme(
            key="solar",
            title="Solarized (light)",
            appearance="light",
            bg="#fdf6e3",
            surface="#eee8d5",
            surface_alt="#e4dcc4",
            border="#d3cbb7",
            text="#073642",
            text_muted="#657b83",
            accent="#268bd2",
            accent_hover="#1f78b8",
            on_accent="#fdf6e3",
            danger="#dc322f",
            you="#268bd2",
            bob="#859900",
            idle="#93a1a1",
            listening="#859900",
            thinking="#b58900",
            speaking="#268bd2",
            loading="#6c71c4",
            error="#dc322f",
        ),
        Theme(
            key="contrast",
            title="High contrast",
            bg="#000000",
            surface="#0a0a0a",
            surface_alt="#1a1a1a",
            border="#ffffff",
            text="#ffffff",
            text_muted="#c0c0c0",
            accent="#ffff00",
            accent_hover="#e6e600",
            on_accent="#000000",
            danger="#ff0000",
            you="#00ffff",
            bob="#00ff00",
            idle="#c0c0c0",
            listening="#00ff00",
            thinking="#ffff00",
            speaking="#00bfff",
            loading="#ff80ff",
            error="#ff4040",
        ),
    )
}
DEFAULT_PRESET = "midnight"
PRESET_KEYS = tuple(PRESETS)


def preset(key: str | None) -> Theme:
    return PRESETS.get(str(key or "").strip().lower(), PRESETS[DEFAULT_PRESET])


def clean_overrides(raw: Any) -> dict[str, str]:
    """Keep only recognised override slots with valid values."""
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        key = str(key)
        if key in COLOR_KEYS:
            color = normalize_hex(value)
            if color:
                out[key] = color
        elif key == "font_family":
            fam = str(value or "").strip()
            if fam:
                out[key] = fam
        elif key == "appearance":
            mode = str(value or "").strip().lower()
            if mode in APPEARANCE_MODES:
                out[key] = mode
    return out


def build_theme(preset_key: str | None, overrides: Any = None) -> Theme:
    base = preset(preset_key)
    clean = clean_overrides(overrides)
    if not clean:
        return base
    return replace(base, **clean)


def diff_overrides(theme: Theme, base_key: str | None) -> dict[str, str]:
    """Slots in *theme* that differ from preset *base_key*."""
    base = preset(base_key)
    out: dict[str, str] = {}
    for f in fields(Theme):
        if f.name in {"key", "title"}:
            continue
        if getattr(theme, f.name) != getattr(base, f.name):
            out[f.name] = getattr(theme, f.name)
    return out


def resolve_theme(settings: Any) -> Theme:
    """Theme described by ``settings.theme`` + ``settings.theme_overrides``."""
    return build_theme(getattr(settings, "theme", None), getattr(settings, "theme_overrides", None))


# --------------------------------------------------------------------------- current

_current: Theme = PRESETS[DEFAULT_PRESET]


def current() -> Theme:
    return _current


def set_current(theme: Theme) -> Theme:
    """Make *theme* the active theme and switch CTk's appearance mode to match."""
    global _current
    _current = theme
    try:
        if ctk.get_appearance_mode().lower() != theme.appearance:
            ctk.set_appearance_mode(theme.appearance)
    except Exception:
        pass
    return theme


# --------------------------------------------------------------------------- restyle

# Widgets may carry a ``_theme_role`` attribute to pick a non-default style:
#   labels:  "muted", "skip"
#   buttons: "danger", "surface", "surface_off", "skip"
#   frames:  "surface" (otherwise transparent frames are left alone)


def set_role(widget: tk.Misc, role: str) -> tk.Misc:
    widget._theme_role = role  # type: ignore[attr-defined]
    return widget


def _role(widget: tk.Misc) -> str | None:
    return getattr(widget, "_theme_role", None)


def _refont(widget: Any, theme: Theme) -> None:
    try:
        font = widget.cget("font")
    except Exception:
        return
    size = weight = slant = None
    if isinstance(font, tuple):
        if len(font) >= 2:
            size = font[1]
        rest = [str(x) for x in font[2:]]
        weight = "bold" if "bold" in rest else None
        slant = "italic" if "italic" in rest else None
    elif isinstance(font, tkfont.Font):
        try:
            size = font.cget("size")
            weight = font.cget("weight")
            slant = font.cget("slant")
        except Exception:
            return
        if weight == "normal":
            weight = None
        if slant == "roman":
            slant = None
    else:
        return
    if size is None:
        return
    parts: list[Any] = [theme.font_family, size]
    if weight:
        parts.append(weight)
    if slant:
        parts.append(slant)
    try:
        widget.configure(font=tuple(parts))
    except Exception:
        pass


def _safe_configure(widget: Any, **kwargs: Any) -> None:
    try:
        widget.configure(**kwargs)
    except Exception:
        pass


def restyle(root: tk.Misc, theme: Theme, refont: bool = True) -> None:
    """Recolour every CTk widget under *root* (inclusive) to match *theme*."""
    stack: list[tk.Misc] = [root]
    while stack:
        w = stack.pop()
        role = _role(w)
        if role != "skip":
            _restyle_one(w, theme, role, refont)
        try:
            stack.extend(w.winfo_children())
        except Exception:
            pass


def _restyle_one(w: Any, theme: Theme, role: str | None, refont: bool) -> None:
    if isinstance(w, (ctk.CTk, ctk.CTkToplevel)):
        _safe_configure(w, **theme.window())
    elif isinstance(w, ctk.CTkButton):
        if role == "swatch":
            return
        _safe_configure(w, **theme.button(role or "accent"))
        if refont:
            _refont(w, theme)
    elif isinstance(w, ctk.CTkLabel):
        if role != "status":
            _safe_configure(w, **theme.label_style(muted=role == "muted"))
        if refont:
            _refont(w, theme)
    elif isinstance(w, ctk.CTkEntry):
        _safe_configure(w, **theme.entry())
        if refont:
            _refont(w, theme)
    elif isinstance(w, ctk.CTkComboBox):
        _safe_configure(w, **theme.combo())
        if refont:
            _refont(w, theme)
    elif isinstance(w, ctk.CTkCheckBox):
        _safe_configure(w, **theme.check())
        if refont:
            _refont(w, theme)
    elif isinstance(w, ctk.CTkTextbox):
        _safe_configure(w, **theme.textbox())
        if refont:
            _refont(w, theme)
    elif isinstance(w, ctk.CTkProgressBar):
        _safe_configure(w, fg_color=theme.surface_alt)
    elif isinstance(w, ctk.CTkScrollableFrame):
        _safe_configure(w, **theme.scroll_frame())
    elif isinstance(w, ctk.CTkFrame):
        if role == "surface":
            _safe_configure(w, **theme.frame())
        else:
            try:
                if w.cget("fg_color") != "transparent":
                    _safe_configure(w, fg_color=theme.surface)
            except Exception:
                pass


def labels_for(keys: Iterable[str]) -> list[str]:
    return [PRESETS[k].title for k in keys if k in PRESETS]


def key_for_label(label: str) -> str:
    for key, theme in PRESETS.items():
        if theme.title == label:
            return key
    return DEFAULT_PRESET
