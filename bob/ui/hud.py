from __future__ import annotations

import sys
from collections.abc import Sequence

import customtkinter as ctk

from bob.state import State
from bob.ui import theme as theming
from bob.ui.theme import Theme, set_role
from bob.ui.transcript import paint_transcript


class TalkHud(ctk.CTkToplevel):
    """Always-on-top talk card used when the main window is hidden or minimized."""

    def __init__(self, master: ctk.CTk, hotkey: str) -> None:
        super().__init__(master)
        theme = theming.current()
        self.title("Bob")
        self.resizable(True, True)
        self.minsize(420, 260)
        self.configure(**theme.window())
        self.attributes("-topmost", True)
        if sys.platform == "win32":
            self.attributes("-toolwindow", True)
        self.protocol("WM_DELETE_WINDOW", self.hide)
        self._open = False
        self._phase = "listen"
        self._state = State.LISTENING
        self._messages: list[dict] = []
        self._pending_user = ""
        self._pending_reply = ""

        self.status = set_role(
            ctk.CTkLabel(
                self,
                text="LISTENING",
                font=theme.font(18, "bold"),
                text_color=theme.state_color(State.LISTENING),
            ),
            "status",
        )
        self.status.pack(anchor="w", padx=16, pady=(14, 2))

        self.meta = set_role(
            ctk.CTkLabel(
                self,
                text=f"Speaking  ·  {hotkey.upper()} to send",
                font=theme.font(12),
                **theme.label_style(muted=True),
            ),
            "muted",
        )
        self.meta.pack(anchor="w", padx=16)

        self.level = ctk.CTkProgressBar(self, height=8, **theme.progress(theme.state_color(State.LISTENING)))
        self.level.pack(fill="x", padx=16, pady=(10, 8))
        self.level.set(0)

        self.body = ctk.CTkTextbox(self, font=theme.font(14), wrap="word", **theme.textbox())
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._paint()

        self.withdraw()

    def apply_theme(self, theme: Theme) -> None:
        theming.restyle(self, theme)
        color = theme.state_color(self._state)
        self.status.configure(text_color=color)
        self.level.configure(progress_color=color)
        self._paint()

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
        self._state = state
        color = theming.current().state_color(state)
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
