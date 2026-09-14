from __future__ import annotations

from collections.abc import Sequence

import customtkinter as ctk


def paint_transcript(
    widget: ctk.CTkTextbox,
    messages: Sequence[dict],
    pending_user: str = "",
    pending_reply: str = "",
) -> None:
    inner = widget._textbox
    inner.tag_configure("you", foreground="#93c5fd")
    inner.tag_configure("bob", foreground="#6ee7b7")
    inner.tag_configure("body", foreground="#e5e7eb")

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
