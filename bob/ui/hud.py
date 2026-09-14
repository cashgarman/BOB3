from __future__ import annotations

import sys
from collections.abc import Sequence

import customtkinter as ctk

from bob.state import State
from bob.ui.overlay import STATUS_COLORS
from bob.ui.transcript import paint_transcript


class TalkHud(ctk.CTkToplevel):
    """Always-on-top talk card used when the main window is hidden or minimized."""

    def __init__(self, master: ctk.CTk, hotkey: str) -> None:
        super().__init__(master)
        self.title("Bob")
        self.resizable(True, True)
        self.minsize(420, 260)
        self.configure(fg_color="#111318")
        self.attributes("-topmost", True)
        if sys.platform == "win32":
            self.attributes("-toolwindow", True)
        self.protocol("WM_DELETE_WINDOW", self.hide)
        self._open = False
        self._phase = "listen"
        self._messages: list[dict] = []
        self._pending_user = ""
        self._pending_reply = ""

        self.status = ctk.CTkLabel(self, text="LISTENING", font=("Segoe UI", 18, "bold"), text_color="#34d399")
        self.status.pack(anchor="w", padx=16, pady=(14, 2))

        self.meta = ctk.CTkLabel(
            self,
            text=f"Speaking  ·  {hotkey.upper()} to send",
            font=("Segoe UI", 12),
            text_color="#6b7280",
        )
        self.meta.pack(anchor="w", padx=16)

        self.level = ctk.CTkProgressBar(self, height=8, progress_color="#34d399")
        self.level.pack(fill="x", padx=16, pady=(10, 8))
        self.level.set(0)

        self.body = ctk.CTkTextbox(self, font=("Segoe UI", 14), wrap="word")
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._paint()

        self.withdraw()

    def is_open(self) -> bool:
        return self._open

    def present(self) -> None:
        self._place()
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self._open = True

    def hide(self) -> None:
        self.withdraw()
        self._open = False

    def set_phase(self, phase: str) -> None:
        self._phase = phase

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

    def set_state(self, state: State, detail: str = "") -> None:
        color = STATUS_COLORS.get(state, "#9aa0a6")
        self.status.configure(text=state.value.upper(), text_color=color)
        self.level.configure(progress_color=color)
        if detail:
            self.meta.configure(text=detail)

    def set_level(self, value: float) -> None:
        self.level.set(max(0.0, min(1.0, value)))

    def set_hotkey(self, hotkey: str) -> None:
        if self._phase == "listen":
            self.meta.configure(text=f"Speaking  ·  {hotkey.upper()} to send")

    def _paint(self) -> None:
        paint_transcript(self.body, self._messages, self._pending_user, self._pending_reply)

    def _place(self) -> None:
        self.update_idletasks()
        width, height = 560, 380
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(16, (screen_w - width) // 2)
        y = max(16, screen_h - height - 96)
        self.geometry(f"{width}x{height}+{x}+{y}")
