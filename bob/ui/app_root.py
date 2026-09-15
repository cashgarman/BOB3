from __future__ import annotations

import sys

import customtkinter as ctk

from bob.ui import theme as theming
from bob.win32_app import hide_from_taskbar


class AppRoot(ctk.CTk):
    """Hidden Tk host for tray-only Bob. Never appears in the taskbar."""

    def __init__(self) -> None:
        theme = theming.current()
        ctk.set_appearance_mode(theme.appearance)
        ctk.set_default_color_theme("dark-blue")
        super().__init__()
        self.withdraw()
        self.title("")
        self.geometry("1x1+-10000+-10000")
        try:
            self.attributes("-alpha", 0)
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                self.attributes("-toolwindow", True)
            except Exception:
                pass
        hide_from_taskbar(self)
        self.update_idletasks()

    def ui(self, fn) -> None:
        self.after(0, fn)
