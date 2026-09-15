from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

import customtkinter as ctk

from bob.state import State
from bob.ui import theme as theming
from bob.ui.theme import Theme, set_role
from bob.ui.transcript import paint_transcript
from bob.win32_app import hide_from_taskbar, show_in_taskbar


class Overlay(ctk.CTkToplevel):
    """Optional main Bob window. Hidden by default; only shown when the user asks."""

    def __init__(
        self,
        master: ctk.CTk,
        on_toggle: Callable[[], None],
        on_quit: Callable[[], None],
        on_submit: Callable[[str], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        *,
        visible: bool = True,
    ) -> None:
        super().__init__(master)
        theme = theming.current()
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.on_submit = on_submit
        self.on_settings = on_settings
        self.on_hide = None
        self._user_visible = bool(visible)
        self._saved_geometry = "560x460+40+40"
        self._messages: list[dict] = []
        self._pending_user = ""
        self._pending_reply = ""
        self._pending_thought = ""
        self._state = State.LOADING
        self.title("BOB")
        from bob.win32_app import apply_tk_icon

        apply_tk_icon(self)
        self.geometry(self._saved_geometry)
        self.minsize(420, 320)
        self.resizable(True, True)
        self.attributes("-topmost", True)
        self.configure(**theme.window())
        self.protocol("WM_DELETE_WINDOW", self.hide)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 2))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(side="left", anchor="w")
        from bob.win32_app import project_root

        logo_file = project_root() / "packaging" / "logo.png"
        if logo_file.is_file():
            from PIL import Image

            self._logo_img = ctk.CTkImage(
                light_image=Image.open(logo_file),
                dark_image=Image.open(logo_file),
                size=(28, 28),
            )
            ctk.CTkLabel(title_row, image=self._logo_img, text="").pack(side="left", padx=(0, 8))

        self.status = set_role(
            ctk.CTkLabel(
                title_row,
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

        if visible:
            show_in_taskbar(self)
        else:
            self.withdraw()
            hide_from_taskbar(self)

    def is_user_visible(self) -> bool:
        return self._user_visible

    def set_user_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible:
            if self._user_visible and self.state() != "withdrawn":
                return
            self._user_visible = True
            show_in_taskbar(self)
            self.present(take_focus=True)
            return
        if not self._user_visible and self.state() == "withdrawn":
            return
        self.hide()

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
        pending_thought: str = "",
    ) -> None:
        self._messages = list(messages)
        self._pending_user = pending_user
        self._pending_reply = pending_reply
        self._pending_thought = pending_thought
        self._paint()

    def set_user(self, text: str) -> None:
        self._pending_user = text or ""
        self._paint()

    def set_reply(self, text: str) -> None:
        self._pending_reply = text or ""
        self._paint()

    def is_viewable(self) -> bool:
        if not self._user_visible:
            return False
        try:
            return self.state() == "normal" and bool(self.winfo_viewable())
        except Exception:
            return False

    def present(self, *, take_focus: bool = False) -> None:
        if not self._user_visible:
            return
        try:
            try:
                geo = self.geometry()
                if geo and "+" in geo and "-10000" not in geo:
                    self._saved_geometry = geo
            except Exception:
                pass
            if self.state() != "normal":
                self.state("normal")
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            if take_focus:
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
        paint_transcript(
            self.transcript,
            self._messages,
            self._pending_user,
            self._pending_reply,
            self._pending_thought,
        )

    def show(self) -> None:
        self.set_user_visible(True)

    def hide(self) -> None:
        self._user_visible = False
        self.withdraw()
        hide_from_taskbar(self)
        if self.on_hide:
            self.on_hide()

    def ui(self, fn: Callable[[], None]) -> None:
        self.after(0, fn)
