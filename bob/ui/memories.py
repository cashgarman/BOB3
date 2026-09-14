from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import customtkinter as ctk

from bob.ui import theme as theming
from bob.ui.theme import Theme, set_role


class MemoriesWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        rows_provider: Callable[[], list[dict]],
        on_toggle: Callable[[str, bool], None],
        on_edit: Callable[[str, str], None],
        on_delete: Callable[[str], None],
        on_forget_all: Callable[[], None],
        autosave: bool,
        on_autosave: Callable[[bool], None],
    ) -> None:
        super().__init__(master)
        theme = theming.current()
        self.title("Bob memories")
        from bob.win32_app import apply_tk_icon

        apply_tk_icon(self)
        self.geometry("560x520")
        self.attributes("-topmost", True)
        self.configure(**theme.window())
        self.rows_provider = rows_provider
        self.on_toggle = on_toggle
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.on_forget_all = on_forget_all
        self.on_autosave = on_autosave
        self._selected: str | None = None

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 6))
        self.search = ctk.CTkEntry(top, placeholder_text="Search memories", **theme.entry())
        self.search.pack(side="left", fill="x", expand=True)
        self.search.bind("<KeyRelease>", lambda *_: self.refresh())
        self.auto = ctk.BooleanVar(value=autosave)
        ctk.CTkCheckBox(top, text="Autosave", variable=self.auto, command=self._auto, **theme.check()).pack(
            side="right", padx=(8, 0)
        )

        self.listbox = ctk.CTkScrollableFrame(self, height=240, **theme.scroll_frame())
        self.listbox.pack(fill="both", expand=True, padx=12)

        self.editor = ctk.CTkTextbox(self, height=90, **theme.textbox())
        self.editor.pack(fill="x", padx=12, pady=8)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(buttons, text="Save edit", command=self._save, **theme.button()).pack(side="left")
        ctk.CTkButton(buttons, text="Enable/disable", command=self._toggle, **theme.button()).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Delete", command=self._delete, **theme.button()).pack(side="left")
        set_role(
            ctk.CTkButton(buttons, text="Forget all", command=self._forget, **theme.button("danger")),
            "danger",
        ).pack(side="right")
        self.refresh()

    def apply_theme(self, theme: Theme) -> None:
        theming.restyle(self, theme)
        self.refresh()

    def _auto(self) -> None:
        self.on_autosave(bool(self.auto.get()))

    def refresh(self) -> None:
        for child in self.listbox.winfo_children():
            child.destroy()
        needle = (self.search.get() or "").lower()
        theme = theming.current()
        for row in self.rows_provider():
            text = str(row.get("text") or "")
            if needle and needle not in text.lower():
                continue
            mid = str(row.get("id"))
            enabled = bool(row.get("enabled", True))
            stamp = row.get("updated") or row.get("created") or 0
            try:
                when = datetime.fromtimestamp(float(stamp)).strftime("%Y-%m-%d %H:%M")
            except Exception:
                when = ""
            label = f"{'[on] ' if enabled else '[off] '}{text}"
            role = "surface" if enabled else "surface_off"
            btn = ctk.CTkButton(
                self.listbox,
                text=f"{label}\n{when}",
                anchor="w",
                height=48,
                command=lambda i=mid, t=text: self._select(i, t),
                **theme.button(role),
            )
            set_role(btn, role).pack(fill="x", pady=3)

    def _select(self, memory_id: str, text: str) -> None:
        self._selected = memory_id
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)

    def _save(self) -> None:
        if not self._selected:
            return
        self.on_edit(self._selected, self.editor.get("1.0", "end").strip())
        self.refresh()

    def _toggle(self) -> None:
        if not self._selected:
            return
        rows = {str(r.get("id")): r for r in self.rows_provider()}
        row = rows.get(self._selected)
        if not row:
            return
        self.on_toggle(self._selected, not bool(row.get("enabled", True)))
        self.refresh()

    def _delete(self) -> None:
        if not self._selected:
            return
        self.on_delete(self._selected)
        self._selected = None
        self.editor.delete("1.0", "end")
        self.refresh()

    def _forget(self) -> None:
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Forget all memories",
            "Delete every stored memory? This cannot be undone.",
            parent=self,
        ):
            return
        self.on_forget_all()
        self._selected = None
        self.editor.delete("1.0", "end")
        self.refresh()
