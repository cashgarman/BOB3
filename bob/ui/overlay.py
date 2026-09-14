from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

import customtkinter as ctk

from bob.state import State
from bob.ui.transcript import paint_transcript

STATUS_COLORS = {
    State.IDLE: "#9aa0a6",
    State.LISTENING: "#34d399",
    State.THINKING: "#fbbf24",
    State.SPEAKING: "#60a5fa",
    State.LOADING: "#a78bfa",
    State.ERROR: "#f87171",
}


class Overlay(ctk.CTk):
    def __init__(self, hotkey: str, on_toggle: Callable[[], None], on_quit: Callable[[], None]) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.on_hide = None
        self._messages: list[dict] = []
        self._pending_user = ""
        self._pending_reply = ""
        self.title("Bob")
        self.geometry("560x420+40+40")
        self.minsize(420, 280)
        self.resizable(True, True)
        self.attributes("-topmost", True)
        self.configure(fg_color="#111318")
        self.protocol("WM_DELETE_WINDOW", self.hide)

        self.status = ctk.CTkLabel(self, text="LOADING", font=("Segoe UI", 18, "bold"), text_color="#a78bfa")
        self.status.pack(anchor="w", padx=16, pady=(14, 2))

        self.meta = ctk.CTkLabel(
            self,
            text=f"Toggle listen  {hotkey.upper()}",
            font=("Segoe UI", 12),
            text_color="#6b7280",
            wraplength=520,
            justify="left",
        )
        self.meta.pack(anchor="w", padx=16)

        self.level = ctk.CTkProgressBar(self, height=8, progress_color="#34d399")
        self.level.pack(fill="x", padx=16, pady=(10, 8))
        self.level.set(0)

        self.transcript = ctk.CTkTextbox(self, font=("Segoe UI", 13), wrap="word")
        self.transcript.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._paint()

    def set_state(self, state: State, detail: str = "") -> None:
        label = state.value.upper()
        color = STATUS_COLORS.get(state, "#9aa0a6")
        self.status.configure(text=label, text_color=color)
        self.level.configure(progress_color=color)
        if detail:
            self.meta.configure(text=detail)

    def set_level(self, value: float) -> None:
        self.level.set(max(0.0, min(1.0, value)))

    def set_transcript(
        self,
        messages: Sequence[dict],
        pending_user: str = "",
        pending_reply: str = "",
    ) -> None:
        self._messages = list(messages)
        self._pending_user = pending_user
        self._pending_reply = pending_reply
        self._paint()

    def set_user(self, text: str) -> None:
        self._pending_user = text or ""
        self._paint()

    def set_reply(self, text: str) -> None:
        self._pending_reply = text or ""
        self._paint()

    def set_meta(self, text: str) -> None:
        self.meta.configure(text=text)

    def is_viewable(self) -> bool:
        try:
            return self.state() == "normal" and bool(self.winfo_viewable())
        except Exception:
            return False

    def present(self) -> None:
        try:
            try:
                if self.state() != "normal":
                    self.state("normal")
            except Exception:
                pass
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.focus_force()
            if sys.platform == "win32":
                self.update_idletasks()
                import ctypes

                hwnd = int(self.winfo_id())
                user32 = ctypes.windll.user32
                root = user32.GetAncestor(hwnd, 2)  # GA_ROOT
                hwnd = int(root or hwnd)
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        except Exception:
            try:
                self.deiconify()
            except Exception:
                pass

    def set_phase(self, phase: str) -> None:
        del phase

    def _paint(self) -> None:
        paint_transcript(self.transcript, self._messages, self._pending_user, self._pending_reply)

    def show(self) -> None:
        self.present()

    def hide(self) -> None:
        self.withdraw()
        if self.on_hide:
            self.on_hide()

    def ui(self, fn: Callable[[], None]) -> None:
        self.after(0, fn)
