from __future__ import annotations

from collections.abc import Sequence

import customtkinter as ctk

from bob.ui import theme as theming


def paint_transcript(
    widget: ctk.CTkTextbox,
    messages: Sequence[dict],
    pending_user: str = "",
    pending_reply: str = "",
    pending_thought: str = "",
) -> None:
    theme = theming.current()
    inner = widget._textbox
    inner.tag_configure("you", foreground=theme.you)
    inner.tag_configure("bob", foreground=theme.bob)
    inner.tag_configure("body", foreground=theme.text)
    inner.tag_configure("thought_label", foreground=theme.thinking)
    inner.tag_configure("thought_body", foreground=theme.thinking)

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

    def add_thought(text: str) -> None:
        nonlocal first
        shown = text.strip()
        if not shown:
            return
        if not first:
            inner.insert("end", "\n\n")
        inner.insert("end", "Thinking: ", "thought_label")
        inner.insert("end", shown, "thought_body")
        first = False

    for msg in messages:
        role = msg.get("role")
        content = str(msg.get("content") or "")
        if role == "user":
            add("You", "you", content)
        else:
            thought = str(msg.get("thought") or "").strip()
            if thought:
                add_thought(thought)
            add("BOB", "bob", content)

    if pending_user:
        add("You", "you", pending_user)
    if pending_thought:
        add_thought(pending_thought)
    if pending_reply:
        add("BOB", "bob", pending_reply)
    if first:
        add("You", "you", "—")

    widget.see("end")
    widget.configure(state="disabled")
