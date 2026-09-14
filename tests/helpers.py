from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator

import customtkinter as ctk
import pystray


def pump(widget: tk.Misc, times: int = 2) -> None:
    """Flush Tk idle callbacks so widget state matches the last command."""
    for _ in range(times):
        try:
            widget.update_idletasks()
            widget.update()
        except tk.TclError:
            return


def walk(root: tk.Misc) -> Iterator[tk.Misc]:
    stack = [root]
    while stack:
        widget = stack.pop()
        yield widget
        try:
            stack.extend(widget.winfo_children())
        except tk.TclError:
            continue


def widget_text(widget: tk.Misc) -> str:
    try:
        return str(widget.cget("text"))
    except tk.TclError:
        return ""


def find_widgets(root: tk.Misc, cls: type | tuple[type, ...] | None = None, text: str | None = None) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    for widget in walk(root):
        if cls is not None and not isinstance(widget, cls):
            continue
        if text is not None and widget_text(widget) != text:
            continue
        found.append(widget)
    return found


def find_widget(root: tk.Misc, cls: type | tuple[type, ...] | None = None, text: str | None = None) -> tk.Misc:
    matches = find_widgets(root, cls=cls, text=text)
    if not matches:
        raise AssertionError(f"No widget matching cls={cls!r} text={text!r}")
    return matches[0]


def destroy_extra_toplevels(root: tk.Misc, keep: tk.Misc | None = None) -> None:
    for child in list(root.winfo_children()):
        if keep is not None and child is keep:
            continue
        if isinstance(child, (ctk.CTkToplevel, tk.Toplevel)):
            try:
                child.destroy()
            except tk.TclError:
                pass
    pump(root, 1)


def destroy_toplevels(root: tk.Misc) -> None:
    for child in list(root.winfo_children()):
        if isinstance(child, (ctk.CTkToplevel, tk.Toplevel)):
            try:
                child.destroy()
            except tk.TclError:
                pass
    pump(root, 1)


def transcript_text(textbox: ctk.CTkTextbox) -> str:
    try:
        return textbox.get("1.0", "end-1c")
    except tk.TclError:
        return textbox._textbox.get("1.0", "end-1c")


def iter_menu_items(menu: pystray.Menu | None):
    if menu is None:
        return
    for item in menu:
        if item is pystray.Menu.SEPARATOR:
            continue
        yield item
        if item.submenu is not None:
            yield from iter_menu_items(item.submenu)


def find_menu_item(menu: pystray.Menu, *path: str) -> pystray.MenuItem:
    current: pystray.Menu | None = menu
    found: pystray.MenuItem | None = None
    for label in path:
        if current is None:
            raise AssertionError(f"No submenu while looking for {path!r}")
        found = None
        for item in current:
            if item is pystray.Menu.SEPARATOR:
                continue
            if item.text == label:
                found = item
                break
        if found is None:
            available = [item.text for item in current if item is not pystray.Menu.SEPARATOR]
            raise AssertionError(f"No menu item {label!r} in {path!r}; have {available}")
        current = found.submenu
    assert found is not None
    return found


def click_menu(tray, *path: str, icon=None) -> pystray.MenuItem:
    item = find_menu_item(tray.icon.menu, *path)
    item(icon if icon is not None else tray.icon)
    return item
