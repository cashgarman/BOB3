from __future__ import annotations

import customtkinter as ctk

from bob.ui import theme as theming
from bob.ui.stats_line import format_meter_label
from bob.ui.theme import set_role

METRICS: tuple[tuple[str, str], ...] = (
    ("gpu", "GPU"),
    ("vram", "VRAM"),
    ("cpu", "CPU"),
    ("context", "CONTEXT"),
)


class UsageMeters(ctk.CTkFrame):
    """Compact GPU/VRAM/CPU/CONTEXT bars with labels drawn on top."""

    def __init__(self, master) -> None:
        theme = theming.current()
        super().__init__(master, fg_color="transparent")
        self._detail = set_role(
            ctk.CTkLabel(
                self,
                text="",
                font=theme.font(11),
                text_color=theme.text_muted,
                anchor="w",
            ),
            "muted",
        )
        self._row = ctk.CTkFrame(self, fg_color="transparent")
        self._row.pack(fill="x")
        self._cells: dict[str, dict] = {}
        for key, name in METRICS:
            cell = ctk.CTkFrame(self._row, fg_color="transparent", height=20)
            cell.pack_propagate(False)
            bar = ctk.CTkProgressBar(cell, height=20, **theme.progress())
            bar.pack(fill="both", expand=True)
            bar.set(0)
            label = set_role(
                ctk.CTkLabel(
                    cell,
                    text="",
                    font=theme.font(10),
                    text_color=theme.text,
                    fg_color="transparent",
                ),
                "meter",
            )
            label.place(relx=0.5, rely=0.5, anchor="center")
            self._cells[key] = {
                "frame": cell,
                "bar": bar,
                "label": label,
                "name": name,
                "visible": False,
            }
        self._detail_visible = False

    def apply_theme(self) -> None:
        theme = theming.current()
        self._detail.configure(text_color=theme.text_muted, font=theme.font(11))
        for cell in self._cells.values():
            cell["bar"].configure(**theme.progress())
            cell["label"].configure(text_color=theme.text, font=theme.font(10))

    def set_values(
        self,
        *,
        detail: str = "",
        gpu: float | None = None,
        vram: float | None = None,
        cpu: float | None = None,
        context: float | None = None,
    ) -> None:
        text = (detail or "").strip()
        if text:
            if not self._detail_visible:
                self._detail.pack(fill="x", pady=(0, 4), before=self._row)
                self._detail_visible = True
            self._detail.configure(text=text)
        else:
            self._detail.configure(text="")
            if self._detail_visible:
                self._detail.pack_forget()
                self._detail_visible = False

        values = {"gpu": gpu, "vram": vram, "cpu": cpu, "context": context}
        for key, cell in self._cells.items():
            value = values.get(key)
            frame = cell["frame"]
            if value is None:
                if cell["visible"]:
                    frame.pack_forget()
                    cell["visible"] = False
                continue
            clamped = max(0.0, min(1.0, float(value)))
            cell["bar"].set(clamped)
            cell["label"].configure(text=format_meter_label(cell["name"], clamped))
            if not cell["visible"]:
                frame.pack(side="left", fill="x", expand=True, padx=2)
                cell["visible"] = True

    def meter_labels(self) -> dict[str, str]:
        return {
            key: str(cell["label"].cget("text"))
            for key, cell in self._cells.items()
            if cell["visible"]
        }

    def meter_values(self) -> dict[str, float]:
        return {
            key: float(cell["bar"].get())
            for key, cell in self._cells.items()
            if cell["visible"]
        }

    def detail_text(self) -> str:
        return str(self._detail.cget("text") or "")
