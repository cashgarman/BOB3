from __future__ import annotations

import math
import sys
import time
import tkinter as tk
from collections.abc import Callable, Sequence

import customtkinter as ctk

from bob.audio import WAVE_BARS
from bob.state import State
from bob.ui import theme as theming
from bob.ui.theme import Theme, set_role

TOAST_W = 364
TOAST_H = 118
MARGIN = 16


def _hwnd(widget: tk.Misc) -> int:
    hwnd = int(widget.winfo_id())
    if sys.platform != "win32":
        return hwnd
    import ctypes

    user32 = ctypes.windll.user32
    GA_ROOT = 2
    root = user32.GetAncestor(hwnd, GA_ROOT)
    return int(root or hwnd)


def _work_area() -> tuple[int, int, int, int]:
    if sys.platform != "win32":
        return (0, 0, 0, 0)
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
    return (rect.left, rect.top, rect.right, rect.bottom)


def _style_native(hwnd: int, dark: bool = True) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    import ctypes
    from ctypes import wintypes

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOPMOST = 0x00000008
    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWCP_ROUND = 2
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    HWND_TOPMOST = -1
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020

    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    style = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
    style |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
    user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        corner = ctypes.c_int(DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner),
            ctypes.sizeof(corner),
        )
        dark_flag = ctypes.c_int(1 if dark else 0)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark_flag),
            ctypes.sizeof(dark_flag),
        )
    except Exception:
        pass


def _restore_foreground(hwnd: int) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    import ctypes

    ctypes.windll.user32.SetForegroundWindow(hwnd)


class ListenToast(ctk.CTkToplevel):
    """Windows toast-style banner: live mic waveform plus Bob's current state."""

    def __init__(self, master: ctk.CTk, on_click: Callable[[], None] | None = None) -> None:
        super().__init__(master)
        theme = theming.current()
        self.on_click = on_click
        self._open = False
        self._state = State.LISTENING
        self._shown = [0.08] * WAVE_BARS
        self.overrideredirect(True)
        self.resizable(False, False)
        set_role(self, "skip")
        self.configure(fg_color=theme.surface)
        self.attributes("-topmost", True)
        if sys.platform == "win32":
            self.attributes("-toolwindow", True)
        self.protocol("WM_DELETE_WINDOW", self.hide)

        self.inner = ctk.CTkFrame(self, fg_color=theme.surface, corner_radius=0)
        self.inner.pack(fill="both", expand=True, padx=14, pady=12)
        inner = self.inner

        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x")
        self.app_name = set_role(
            ctk.CTkLabel(
                header,
                text="Bob",
                font=theme.font(12),
                text_color=theme.text_muted,
                anchor="w",
            ),
            "muted",
        )
        self.app_name.pack(side="left")
        self.status = set_role(
            ctk.CTkLabel(
                header,
                text="LISTENING",
                font=theme.font(13, "bold"),
                text_color=theme.state_color(State.LISTENING),
                anchor="e",
            ),
            "status",
        )
        self.status.pack(side="right")

        self.wave = tk.Canvas(
            inner,
            height=44,
            bg=theme.surface,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.wave.pack(fill="x", pady=(8, 6))

        self.meta = set_role(
            ctk.CTkLabel(
                inner,
                text="",
                font=theme.font(11),
                text_color=theme.text_muted,
                anchor="w",
            ),
            "muted",
        )
        self.meta.pack(fill="x")

        for widget in (self, inner, header, self.app_name, self.status, self.wave, self.meta):
            widget.bind("<Button-1>", self._clicked)
        self.wave.bind("<Configure>", lambda _e: self._paint())
        self.withdraw()
        self.after(20, self._init_native)

    def apply_theme(self, theme: Theme) -> None:
        theming.restyle(self, theme)  # the toplevel itself is role "skip": it is a card, not a window
        self.configure(fg_color=theme.surface)
        self.wave.configure(bg=theme.surface)
        self.status.configure(text_color=theme.state_color(self._state))
        self._style()
        self._paint()

    def is_open(self) -> bool:
        return self._open

    def present(self) -> None:
        fg = 0
        if sys.platform == "win32":
            import ctypes

            fg = int(ctypes.windll.user32.GetForegroundWindow() or 0)
        self.overrideredirect(True)
        self._place()
        self.deiconify()
        self.update_idletasks()
        self.lift()
        self.attributes("-topmost", True)
        self._style()
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.ShowWindow(_hwnd(self), 4)  # SW_SHOWNOACTIVATE
        if fg:
            _restore_foreground(fg)
        self._open = True
        self._paint()

    def hide(self) -> None:
        self.withdraw()
        self._open = False

    def set_state(self, state: State, detail: str = "") -> None:
        self._state = state
        color = theming.current().state_color(state)
        self.status.configure(text=state.value.upper(), text_color=color)
        if detail:
            self.meta.configure(text=detail)
        if not self._open:
            self.present()

    def set_waveform(self, bars: Sequence[float]) -> None:
        if not self._open:
            return
        if self._state == State.THINKING:
            target = self._idle_bars(0.22, 1.6)
        elif self._state == State.SPEAKING and not any(abs(float(v)) > 0.004 for v in bars):
            target = self._idle_bars(0.35, 4.5)
        else:
            target = [min(1.0, max(0.0, float(v) * 8.0)) for v in bars]
            if len(target) < WAVE_BARS:
                target = [0.0] * (WAVE_BARS - len(target)) + target
            elif len(target) > WAVE_BARS:
                target = target[-WAVE_BARS:]
            if self._state != State.LISTENING and self._state != State.SPEAKING:
                target = self._idle_bars(0.18, 1.2)
        self._shown = [0.62 * prev + 0.38 * nxt for prev, nxt in zip(self._shown, target)]
        self._paint()

    def _idle_bars(self, amp: float, speed: float) -> list[float]:
        t = time.monotonic() * speed
        return [0.08 + amp * (0.55 + 0.45 * math.sin(t + i * 0.28)) for i in range(WAVE_BARS)]

    def _paint(self) -> None:
        canvas = self.wave
        width = int(canvas.winfo_width())
        height = int(canvas.winfo_height())
        if width < 8 or height < 8:
            return
        canvas.delete("all")
        color = theming.current().state_color(self._state)
        n = len(self._shown)
        gap = 2
        bar_w = max(2.0, (width - gap * (n - 1)) / n)
        mid = height / 2
        max_h = max(2.0, height / 2 - 1)
        for i, value in enumerate(self._shown):
            amp = max(0.07, min(1.0, value))
            bh = amp * max_h
            x0 = i * (bar_w + gap)
            canvas.create_rectangle(
                x0,
                mid - bh,
                x0 + bar_w,
                mid + bh,
                fill=color,
                outline="",
            )

    def _place(self) -> None:
        left, top, right, bottom = _work_area()
        if right <= left:
            right = self.winfo_screenwidth()
            bottom = self.winfo_screenheight()
            left = 0
        x = right - TOAST_W - MARGIN
        y = bottom - TOAST_H - MARGIN
        if x < left:
            x = left + MARGIN
        if y < top:
            y = top + MARGIN
        self.geometry(f"{TOAST_W}x{TOAST_H}+{x}+{y}")

    def _init_native(self) -> None:
        self._place()
        self._style()

    def _style(self) -> None:
        try:
            _style_native(_hwnd(self), dark=theming.current().appearance != "light")
        except Exception:
            pass

    def _clicked(self, _event=None) -> None:  # noqa: ANN001
        if self.on_click:
            self.on_click()
