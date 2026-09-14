from __future__ import annotations

from collections.abc import Sequence

import customtkinter as ctk

from bob.ui import theme as theming


def paint_transcript(
    widget: ctk.CTkTextbox,
    messages: Sequence[dict],
    pending_user: str = "",
    pending_reply: str = "",
) -> None:
    theme = theming.current()
    inner = widget._textbox
    inner.tag_configure("you", foreground=theme.you)
    inner.tag_configure("bob", foreground=theme.bob)
    inner.tag_configure("body", foreground=theme.text)

    widget.configure(state="normal")
    widget.delete("1.0", "end")

    first = True

    def add(who: str, tag: str, text: str) -> None:
        nonlocal first
        if not first:
            inner.insert("end", "\n\n")
        inner.insert("end", f"{who}: ", tag)
        shown = text.strip() if text and text.strip() else "—"
        inner.insert("end", shown, "body")
        first = False

    for msg in messages:
        role = msg.get("role")
        content = str(msg.get("content") or "")
        if role == "user":
            add("You", "you", content)
        else:
            add("Bob", "bob", content)

    if pending_user:
        add("You", "you", pending_user)
    if pending_reply:
        add("Bob", "bob", pending_reply)
    if first:
        add("You", "you", "—")

    widget.see("end")
    widget.configure(state="disabled")
