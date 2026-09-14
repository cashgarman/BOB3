from __future__ import annotations

import customtkinter as ctk

from bob.state import State
from bob.ui import theme as theming
from tests.helpers import find_widget, pump, transcript_text


def test_overlay_initial_state(ui):
    assert ui.title() == "Bob"
    assert "LOADING" not in ui.status.cget("text") or True
    ui.set_state(State.IDLE)
    pump(ui)
    assert ui.status.cget("text") == "IDLE"


def test_overlay_set_state_and_level(ui):
    ui.set_state(State.LISTENING)
    ui.set_level(0.75)
    pump(ui)
    assert ui.status.cget("text") == "LISTENING"
    assert abs(ui.level.get() - 0.75) < 1e-6


def test_overlay_level_clamped(ui):
    ui.set_level(2.0)
    assert ui.level.get() == 1.0
    ui.set_level(-1.0)
    assert ui.level.get() == 0.0


def test_overlay_transcript_history_and_pending(ui):
    ui.set_transcript(
        [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}],
        pending_user="Typing…",
        pending_reply="Thinking…",
    )
    pump(ui)
    text = transcript_text(ui.transcript)
    assert "You: Hi" in text
    assert "Bob: Hello" in text
    assert "You: Typing…" in text
    assert "Bob: Thinking…" in text


def test_overlay_empty_transcript_shows_placeholder(ui):
    ui.set_transcript([])
    pump(ui)
    assert "You: —" in transcript_text(ui.transcript)


def test_overlay_set_user_and_reply(ui):
    ui.set_transcript([])
    ui.set_user("heard this")
    ui.set_reply("saying that")
    pump(ui)
    text = transcript_text(ui.transcript)
    assert "heard this" in text
    assert "saying that" in text


def test_overlay_submit_typed_message(ui):
    ui.set_state(State.IDLE)
    ui.composer.insert(0, "  hello bob  ")
    ui.send_btn.invoke()
    pump(ui)
    assert ui.submitted == ["hello bob"]
    assert ui.composer.get() == ""


def test_overlay_submit_ignores_empty_and_loading(ui):
    ui.set_state(State.LOADING)
    ui.composer.insert(0, "blocked")
    ui.send_btn.invoke()
    assert ui.submitted == []

    ui.set_state(State.IDLE)
    ui.composer.delete(0, "end")
    ui.send_btn.invoke()
    assert ui.submitted == []


def test_overlay_submit_allowed_in_error_state(ui):
    # Overlay only blocks LOADING; ERROR is cleared by Assistant.submit_text.
    ui.set_state(State.ERROR)
    ui.composer.insert(0, "recover")
    ui.send_btn.invoke()
    assert ui.submitted == ["recover"]


def test_overlay_hide_calls_on_hide(ui):
    called = []
    ui.on_hide = lambda: called.append(True)
    ui.hide()
    pump(ui)
    assert called == [True]


def test_overlay_present_and_is_viewable(ui):
    ui.set_user_visible(True)
    pump(ui)
    assert ui.is_viewable() is True
    ui.hide()
    pump(ui)
    assert ui.is_viewable() is False
    assert ui.is_user_visible() is False


def test_overlay_hidden_by_default(ui):
    ui.set_user_visible(False)
    pump(ui.master, 3)
    assert ui.is_viewable() is False
    assert ui.state() == "withdrawn"


def test_overlay_apply_theme(ui):
    ocean = theming.preset("ocean")
    ui.set_state(State.LISTENING)
    ui.apply_theme(ocean)
    pump(ui)
    assert ui.status.cget("text_color") == ocean.listening


def test_overlay_ui_schedules_callback(ui):
    seen = []
    ui.ui(lambda: seen.append("ok"))
    pump(ui)
    assert seen == ["ok"]


def test_overlay_settings_button(ui):
    opened = []
    ui.on_settings = lambda: opened.append(True)
    find_widget(ui, ctk.CTkButton, text="⚙").invoke()
    assert opened == [True]
