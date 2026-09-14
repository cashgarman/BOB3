from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

import customtkinter as ctk

from bob.state import State
from bob.ui import theme as theming
from bob.ui.theme import Theme, set_role
from bob.ui.transcript import paint_transcript


class Overlay(ctk.CTk):
    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_quit: Callable[[], None],
        on_submit: Callable[[str], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        *,
        visible: bool = True,
    ) -> None:
        theme = theming.current()
        ctk.set_appearance_mode(theme.appearance)
        ctk.set_default_color_theme("dark-blue")
        super().__init__()
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.on_submit = on_submit
        self.on_settings = on_settings
        self.on_hide = None
        self._messages: list[dict] = []
        self._pending_user = ""
        self._pending_reply = ""
        self._state = State.LOADING
        self.title("Bob")
        from bob.win32_app import apply_tk_icon

        apply_tk_icon(self)
        self.geometry("560x460+40+40")
        self.minsize(420, 320)
        self.resizable(True, True)
        self.attributes("-topmost", True)
        self.configure(**theme.window())
        self.protocol("WM_DELETE_WINDOW", self.hide)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 2))

        self.status = set_role(
            ctk.CTkLabel(
                header,
                text="LOADING",
                font=theme.font(18, "bold"),
                text_color=theme.state_color(State.LOADING),
            ),
            "status",
        )
        self.status.pack(side="left", anchor="w")

        self.settings_btn = set_role(
            ctk.CTkButton(
                header,
                text="⚙",
                width=32,
                height=32,
                font=theme.font(18),
                command=self._open_settings,
                **theme.button("surface_off"),
            ),
            "surface_off",
        )
        self.settings_btn.pack(side="right")

        self.level = ctk.CTkProgressBar(self, height=8, **theme.progress(theme.state_color(State.LOADING)))
        self.level.pack(fill="x", padx=16, pady=(10, 8))
        self.level.set(0)

        self.transcript = ctk.CTkTextbox(self, font=theme.font(13), wrap="word", **theme.textbox())
        self.transcript.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self._paint()

        composer = ctk.CTkFrame(self, fg_color="transparent")
        composer.pack(fill="x", padx=16, pady=(0, 12))
        self.composer = ctk.CTkEntry(composer, placeholder_text="Type a message and press Enter", **theme.entry())
        self.composer.pack(side="left", fill="x", expand=True)
        inner = getattr(self.composer, "_entry", None)
        if inner is not None:
            inner.bind("<Return>", self._submit_typed)
        else:
            self.composer.bind("<Return>", self._submit_typed)
        self.send_btn = ctk.CTkButton(
            composer,
            text="Send",
            width=72,
            command=self._submit_typed,
            **theme.button(),
        )
        self.send_btn.pack(side="right", padx=(8, 0))

        if not visible:
            self.withdraw()

    def _open_settings(self) -> None:
        if self.on_settings:
            self.on_settings()

    def _submit_typed(self, _event=None) -> None:  # noqa: ANN001
        text = (self.composer.get() or "").strip()
        if not text or self.on_submit is None:
            return
        if self._state == State.LOADING:
            return
        self.composer.delete(0, "end")
        self.on_submit(text)

    def apply_theme(self, theme: Theme) -> None:
        theming.restyle(self, theme)
        color = theme.state_color(self._state)
        self.status.configure(text_color=color)
        self.level.configure(progress_color=color)
        self._paint()

    def set_state(self, state: State, detail: str = "") -> None:
        del detail
        self._state = state
        label = state.value.upper()
        color = theming.current().state_color(state)
        self.status.configure(text=label, text_color=color)
        self.level.configure(progress_color=color)

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
