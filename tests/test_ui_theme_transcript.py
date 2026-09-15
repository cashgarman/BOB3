from __future__ import annotations

import customtkinter as ctk

from bob.ui import theme as theming
from bob.ui.transcript import paint_transcript
from tests.helpers import pump, transcript_text


def test_compose_internal_thought_includes_filtered_monologue():
    from bob.llm import _compose_internal_thought

    raw = (
        "Okay, the user is asking for the current time. Let me think about how to handle this. "
        'Bob should say "It\'s 1:03 PM, Cash."'
    )
    thought = _compose_internal_thought("", raw, "It's 1:03 PM, Cash.", "What time is it?")
    assert thought == "Planned the reply internally."


def test_paint_transcript_shows_internal_thought(ui):
    box = ctk.CTkTextbox(ui)
    theming.set_current(theming.preset("midnight"))
    paint_transcript(
        box,
        [
            {"role": "user", "content": "What time is it?"},
            {
                "role": "assistant",
                "content": "It's 1:03 PM.",
                "thought": "Called get_current_time directly (skipped LLM).",
            },
        ],
        pending_thought="Checking tool results…",
        pending_reply="It's 1:03 PM.",
    )
    text = transcript_text(box)
    assert "Thinking: Called get_current_time directly (skipped LLM)." in text
    assert "Thinking: Checking tool results…" in text
    assert "BOB: It's 1:03 PM." in text
    box.destroy()


def test_paint_transcript_roles_and_empty(ui):
    box = ctk.CTkTextbox(ui)
    theming.set_current(theming.preset("midnight"))
    paint_transcript(box, [])
    assert "You: —" in transcript_text(box)

    paint_transcript(
        box,
        [
            {"role": "user", "content": "  hi  "},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "there"},
        ],
        pending_user="partial",
        pending_reply="draft",
    )
    text = transcript_text(box)
    assert "You: hi" in text
    assert "BOB: —" in text
    assert "BOB: there" in text
    assert "You: partial" in text
    assert "BOB: draft" in text
    assert str(box.cget("state")) == "disabled"
    box.destroy()


def test_theme_presets_and_build():
    for key in theming.PRESET_KEYS:
        theme = theming.preset(key)
        assert theme.key == key
        assert theming.normalize_hex(theme.accent) == theme.accent.lower()

    built = theming.build_theme("ocean", {"accent": "#FF8800", "font_family": "Consolas", "appearance": "light"})
    assert built.accent == "#ff8800"
    assert built.font_family == "Consolas"
    assert built.appearance == "light"
    assert built.bg == theming.preset("ocean").bg


def test_theme_clean_overrides_and_diff():
    clean = theming.clean_overrides(
        {"accent": "not-a-color", "bg": "#abc", "font_family": "  ", "appearance": "neon", "extra": 1}
    )
    assert clean == {"bg": "#aabbcc"}

    theme = theming.build_theme("midnight", {"accent": "#123456"})
    diff = theming.diff_overrides(theme, "midnight")
    assert diff == {"accent": "#123456"}


def test_theme_labels_and_key_lookup():
    labels = theming.labels_for(("midnight", "paper"))
    assert "Midnight" in labels
    assert theming.key_for_label("Paper (light)") == "paper"
    assert theming.key_for_label("Nope") == theming.DEFAULT_PRESET


def test_theme_set_current_and_restyle(ui):
    paper = theming.preset("paper")
    theming.set_current(paper)
    assert theming.current().key == "paper"
    theming.restyle(ui, paper)
    pump(ui)
    assert ui.cget("fg_color") == paper.bg


def test_theme_state_colors():
    theme = theming.preset("midnight")
    from bob.state import State

    assert theme.state_color(State.LISTENING) == theme.listening
    assert theme.state_color(State.ERROR) == theme.error
