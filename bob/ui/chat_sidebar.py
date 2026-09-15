from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from bob.chat_store import display_session_title
from bob.ui import theme as theming
from bob.ui.theme import set_role

SIDEBAR_WIDTH = 200
TITLE_MAX = 42


def _row_label(row: dict) -> str:
    title = display_session_title(str(row.get("title") or ""))
    if len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1] + "…"
    count = int(row.get("count") or 0)
    when = str(row.get("updated_at") or row.get("created_at") or "")[:10]
    count_text = f"{count} msg" if count == 1 else f"{count} msgs"
    subtitle = " · ".join(part for part in (count_text, when) if part)
    return f"{title}\n{subtitle}" if subtitle else title


class ChatSidebar(ctk.CTkFrame):
    """Left-hand chat list with a New Chat button."""

    def __init__(
        self,
        master,
        on_new_chat: Callable[[], None] | None = None,
        on_select_session: Callable[[int], None] | None = None,
    ) -> None:
        theme = theming.current()
        super().__init__(master, width=SIDEBAR_WIDTH, **theme.frame())
        self.pack_propagate(False)
        self.on_new_chat = on_new_chat
        self.on_select_session = on_select_session
        self._sessions: list[dict] = []
        self._current_id = 0

        self.new_chat_btn = set_role(
            ctk.CTkButton(
                self,
                text="New Chat",
                height=32,
                command=self._new_chat,
                **theme.button("accent"),
            ),
            "accent",
        )
        self.new_chat_btn.pack(fill="x", padx=8, pady=(8, 6))

        self.listbox = ctk.CTkScrollableFrame(self, **theme.scroll_frame())
        self.listbox.pack(fill="both", expand=True, padx=4, pady=(0, 8))

    def refresh(self, sessions: list[dict], current_id: int) -> None:
        self._sessions = list(sessions)
        self._current_id = int(current_id or 0)
        for child in self.listbox.winfo_children():
            child.destroy()
        theme = theming.current()
        for row in self._sessions:
            sid = int(row.get("id") or 0)
            role = "accent" if sid == self._current_id else "surface"
            btn = set_role(
                ctk.CTkButton(
                    self.listbox,
                    text=_row_label(row),
                    anchor="w",
                    height=48,
                    command=lambda session=sid: self._select(session),
                    **theme.button(role),
                ),
                role,
            )
            btn.pack(fill="x", pady=2, padx=2)

    def _new_chat(self) -> None:
        if self.on_new_chat:
            self.on_new_chat()

    def _select(self, session_id: int) -> None:
        if self.on_select_session:
            self.on_select_session(int(session_id))
