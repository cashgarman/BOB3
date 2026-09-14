"""Theme editor: pick a preset, then tune colours, font and appearance live."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from tkinter import colorchooser

import customtkinter as ctk

from bob.settings import Settings
from bob.ui import theme as theming
from bob.ui.theme import (
    APPEARANCE_MODES,
    COLOR_SLOTS,
    FONT_SUGGESTIONS,
    PRESET_KEYS,
    PRESETS,
    Theme,
    build_theme,
    diff_overrides,
    key_for_label,
    labels_for,
    normalize_hex,
    preset,
    set_role,
)


class ThemeDialog(ctk.CTkToplevel):
    """Edits ``settings.theme`` / ``settings.theme_overrides``.

    Every change is pushed through *on_preview* so the rest of the app updates
    immediately; *on_save* persists, closing without saving reverts.
    """

    def __init__(
        self,
        master,
        settings: Settings,
        on_preview: Callable[[Theme], None],
        on_save: Callable[[dict], None],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.settings = settings
        self.on_preview = on_preview
        self.on_save = on_save
        self.on_close = on_close
        self._saved = theming.resolve_theme(settings)
        self._preset_key = settings.theme if settings.theme in PRESETS else theming.DEFAULT_PRESET
        self._draft: Theme = self._saved
        self._suspend = False
        self._swatches: dict[str, ctk.CTkButton] = {}
        self._hex_vars: dict[str, ctk.StringVar] = {}

        theme = self._draft
        self.title("Bob theme")
        self.geometry("520x680")
        self.minsize(440, 480)
        self.attributes("-topmost", True)
        self.configure(**theme.window())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        body = ctk.CTkScrollableFrame(self, **theme.scroll_frame())
        body.pack(fill="both", expand=True, padx=14, pady=(12, 6))
        self.body = body

        # -- preset ---------------------------------------------------------
        self._heading(body, "Preset")
        self.preset_var = ctk.StringVar(value=preset(self._preset_key).label)
        self.preset_box = ctk.CTkComboBox(
            body,
            values=labels_for(PRESET_KEYS),
            variable=self.preset_var,
            state="readonly",
            command=self._preset_changed,
            **theme.combo(),
        )
        self.preset_box.pack(fill="x")
        self._hint(body, "Picking a preset resets every colour below to that preset.")

        # -- appearance + font ----------------------------------------------
        self._heading(body, "Appearance mode")
        self.mode_var = ctk.StringVar(value=theme.appearance)
        self.mode_box = ctk.CTkComboBox(
            body,
            values=list(APPEARANCE_MODES),
            variable=self.mode_var,
            state="readonly",
            command=lambda _v: self._field_changed(),
            **theme.combo(),
        )
        self.mode_box.pack(fill="x")
        self._hint(body, "Controls native widget styling (title bars, scrollbars, drop-downs).")

        self._heading(body, "Font family")
        fonts = list(FONT_SUGGESTIONS)
        if theme.font_family not in fonts:
            fonts.insert(0, theme.font_family)
        self.font_var = ctk.StringVar(value=theme.font_family)
        self.font_box = ctk.CTkComboBox(
            body,
            values=fonts,
            variable=self.font_var,
            command=lambda _v: self._field_changed(),
            **theme.combo(),
        )
        self.font_box.pack(fill="x")
        self.font_box.bind("<Return>", lambda _e: self._field_changed())
        self.font_box.bind("<FocusOut>", lambda _e: self._field_changed())

        # -- colours ---------------------------------------------------------
        self._heading(body, "Colours")
        self._hint(body, "Click a swatch to pick, or type a hex value like #ff8800.")
        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1)
        for row, (slot, label) in enumerate(COLOR_SLOTS):
            self._color_row(grid, row, slot, label)

        # -- preview strip ------------------------------------------------------
        self._heading(body, "Preview")
        self.preview = ctk.CTkFrame(body, corner_radius=8, **theme.frame())
        set_role(self.preview, "surface")
        self.preview.pack(fill="x", pady=(0, 8))
        self.preview_status = set_role(
            ctk.CTkLabel(self.preview, text="LISTENING", font=theme.font(16, "bold"), text_color=theme.listening),
            "status",
        )
        self.preview_status.pack(anchor="w", padx=12, pady=(10, 0))
        self.preview_meta = set_role(
            ctk.CTkLabel(self.preview, text="Speaking  ·  CTRL+SHIFT+SPACE to send", font=theme.font(11), **theme.label(True)),
            "muted",
        )
        self.preview_meta.pack(anchor="w", padx=12)
        self.preview_bar = ctk.CTkProgressBar(self.preview, height=6, **theme.progress(theme.listening))
        self.preview_bar.pack(fill="x", padx=12, pady=(6, 6))
        self.preview_bar.set(0.55)
        self.preview_text = ctk.CTkTextbox(self.preview, height=64, font=theme.font(12), wrap="word", **theme.textbox())
        self.preview_text.pack(fill="x", padx=12, pady=(0, 10))
        self._paint_preview()

        # -- buttons -----------------------------------------------------------
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=(0, 12))
        set_role(
            ctk.CTkButton(bar, text="Reset to preset", command=self._reset, **theme.button("surface")),
            "surface",
        ).pack(side="left")
        ctk.CTkButton(bar, text="Save", command=self._save, **theme.button()).pack(side="right")
        set_role(
            ctk.CTkButton(bar, text="Cancel", command=self._cancel, **theme.button("surface")),
            "surface",
        ).pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------------ layout

    def _heading(self, parent, text: str) -> None:
        theme = self._draft
        set_role(
            ctk.CTkLabel(parent, text=text.upper(), anchor="w", font=theme.font(11, "bold"), **theme.label(True)),
            "muted",
        ).pack(fill="x", pady=(12, 2))

    def _hint(self, parent, text: str) -> None:
        theme = self._draft
        set_role(
            ctk.CTkLabel(parent, text=text, anchor="w", font=theme.font(11), wraplength=460, **theme.label(True)),
            "muted",
        ).pack(fill="x", pady=(2, 2))

    def _color_row(self, parent, row: int, slot: str, label: str) -> None:
        theme = self._draft
        value = theme.color(slot)
        ctk.CTkLabel(parent, text=label, anchor="w", **theme.label()).grid(row=row, column=0, sticky="ew", pady=3)
        var = ctk.StringVar(value=value)
        self._hex_vars[slot] = var
        entry = ctk.CTkEntry(parent, textvariable=var, width=96, **theme.entry())
        entry.grid(row=row, column=1, padx=(8, 8), pady=3)
        entry.bind("<Return>", lambda _e, s=slot: self._hex_typed(s))
        entry.bind("<FocusOut>", lambda _e, s=slot: self._hex_typed(s))
        swatch = ctk.CTkButton(
            parent,
            text="",
            width=44,
            height=26,
            corner_radius=6,
            fg_color=value,
            hover_color=value,
            border_width=1,
            border_color=theme.border,
            command=lambda s=slot: self._pick(s),
        )
        set_role(swatch, "swatch")
        swatch.grid(row=row, column=2, pady=3)
        self._swatches[slot] = swatch

    # ------------------------------------------------------------------ events

    def _preset_changed(self, label: str) -> None:
        self._preset_key = key_for_label(label)
        self._set_draft(preset(self._preset_key))

    def _reset(self) -> None:
        self._set_draft(preset(self._preset_key))

    def _field_changed(self) -> None:
        if self._suspend:
            return
        mode = self.mode_var.get().strip().lower()
        if mode not in APPEARANCE_MODES:
            mode = self._draft.appearance
        font = self.font_var.get().strip() or self._draft.font_family
        if mode == self._draft.appearance and font == self._draft.font_family:
            return
        self._set_draft(replace(self._draft, appearance=mode, font_family=font), sync_fields=False)

    def _hex_typed(self, slot: str) -> None:
        if self._suspend:
            return
        color = normalize_hex(self._hex_vars[slot].get())
        if color is None:
            self._hex_vars[slot].set(self._draft.color(slot))
            return
        if color == self._draft.color(slot):
            return
        self._set_draft(replace(self._draft, **{slot: color}), sync_fields=False)

    def _pick(self, slot: str) -> None:
        current = self._draft.color(slot)
        try:
            _rgb, chosen = colorchooser.askcolor(color=current, parent=self, title=f"Pick colour: {slot}")
        except tk.TclError:
            chosen = None
        color = normalize_hex(chosen) if chosen else None
        if color and color != current:
            self._set_draft(replace(self._draft, **{slot: color}), sync_fields=False)

    # ------------------------------------------------------------------ state

    def _set_draft(self, theme: Theme, sync_fields: bool = True) -> None:
        self._draft = theme
        self._suspend = True
        try:
            if sync_fields:
                self.mode_var.set(theme.appearance)
                self.font_var.set(theme.font_family)
                fonts = list(FONT_SUGGESTIONS)
                if theme.font_family not in fonts:
                    fonts.insert(0, theme.font_family)
                self.font_box.configure(values=fonts)
            for slot, var in self._hex_vars.items():
                var.set(theme.color(slot))
        finally:
            self._suspend = False
        self.on_preview(theme)
        self.apply_theme(theme)

    def apply_theme(self, theme: Theme) -> None:
        """Restyle this dialog; swatches keep their own colour."""
        self._draft = theme
        theming.restyle(self, theme)
        for slot, swatch in self._swatches.items():
            color = theme.color(slot)
            swatch.configure(fg_color=color, hover_color=color, border_color=theme.border)
        self.preview_status.configure(text_color=theme.listening)
        self.preview_bar.configure(progress_color=theme.listening)
        self._paint_preview()

    def _paint_preview(self) -> None:
        theme = self._draft
        inner = self.preview_text._textbox
        inner.tag_configure("you", foreground=theme.you)
        inner.tag_configure("bob", foreground=theme.bob)
        inner.tag_configure("body", foreground=theme.text)
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        inner.insert("end", "You: ", "you")
        inner.insert("end", "What does this theme look like?\n\n", "body")
        inner.insert("end", "Bob: ", "bob")
        inner.insert("end", "Like this.", "body")
        self.preview_text.configure(state="disabled")

    # ------------------------------------------------------------------ actions

    def _save(self) -> None:
        overrides = diff_overrides(self._draft, self._preset_key)
        # ``build_theme`` is the canonical round-trip; make sure it reproduces the draft.
        final = build_theme(self._preset_key, overrides)
        self.on_save({"theme": self._preset_key, "theme_overrides": overrides})
        self.on_preview(final)
        self._finish()

    def _cancel(self) -> None:
        self.on_preview(self._saved)
        self._finish()

    def _finish(self) -> None:
        if self.on_close:
            try:
                self.on_close()
            except Exception:
                pass
        self.destroy()
