"""Progress dialog while Ollama downloads an LLM."""

from __future__ import annotations

import customtkinter as ctk

from bob.ui import theme as theming
from bob.ui.theme import set_role
from bob.win32_app import apply_tk_icon


def _format_bytes(n: int | float | None) -> str:
    if n is None:
        return ""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(n)} B"


class ModelDownloadDialog(ctk.CTkToplevel):
    def __init__(self, master, model: str) -> None:
        super().__init__(master)
        theme = theming.current()
        self.title("Downloading model")
        apply_tk_icon(self)
        self.geometry("440x200")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(**theme.window())
        self._closed = False

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=16)

        ctk.CTkLabel(
            body,
            text=f"Downloading {model}",
            font=theme.font(15, "bold"),
            anchor="w",
            **theme.label_style(),
        ).pack(fill="x")

        self._status = set_role(
            ctk.CTkLabel(body, text="Starting…", anchor="w", **theme.label_style()),
            "status",
        )
        self._status.pack(fill="x", pady=(10, 6))

        self._bar = ctk.CTkProgressBar(body, **theme.progress())
        self._bar.set(0)
        self._bar.pack(fill="x")

        self._size = set_role(
            ctk.CTkLabel(body, text="", anchor="w", **theme.label_style(muted=True)),
            "muted",
        )
        self._size.pack(fill="x", pady=(6, 0))

        self._error = set_role(
            ctk.CTkLabel(body, text="", anchor="w", text_color=theme.error, wraplength=400, justify="left"),
            "status",
        )

        self._close_btn = ctk.CTkButton(body, text="Close", command=self.close, **theme.button("surface"))
        self.protocol("WM_DELETE_WINDOW", self._on_close_attempt)
        self.transient(master)
        self.grab_set()

    def update_progress(self, completed: int | None, total: int | None, status: str) -> None:
        if self._closed:
            return
        text = (status or "downloading").strip()
        self._status.configure(text=text)
        if total and total > 0:
            frac = min(1.0, max(0.0, (completed or 0) / total))
            self._bar.set(frac)
            self._size.configure(text=f"{_format_bytes(completed)} / {_format_bytes(total)}")
        elif completed is not None and total is not None and completed == total == 1:
            self._bar.set(1.0)
            self._size.configure(text="")
        else:
            self._bar.set(0.2 if completed is None else 1.0)

    def set_error(self, message: str) -> None:
        if self._closed:
            return
        self._error.configure(text=message or "Download failed.")
        self._error.pack(fill="x", pady=(10, 0))
        self._close_btn.pack(anchor="e", pady=(10, 0))
        self.grab_release()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def _on_close_attempt(self) -> None:
        if self._error.cget("text"):
            self.close()
