from __future__ import annotations

from bob.state import State
from bob.ui import theme as theming
from bob.ui.hud import TalkHud
from tests.helpers import pump, transcript_text


def test_hud_present_hide_and_state(ui):
    hud = TalkHud(ui, "ctrl+shift+space")
    pump(ui)
    assert hud.is_open() is False

    hud.present()
    pump(ui)
    assert hud.is_open() is True
    assert hud.status.cget("text") == "LISTENING"

    hud.set_state(State.THINKING, "ollama")
    hud.set_level(0.4)
    pump(ui)
    assert hud.status.cget("text") == "THINKING"
    assert "ollama" in hud.meta.cget("text")
    assert abs(hud.level.get() - 0.4) < 1e-6

    hud.hide()
    pump(ui)
    assert hud.is_open() is False
    hud.destroy()


def test_hud_transcript_and_hotkey(ui):
    hud = TalkHud(ui, "alt+space")
    hud.set_phase("listen")
    hud.set_hotkey("ctrl+a")
    pump(ui)
    assert "CTRL+A" in hud.meta.cget("text")

    hud.set_transcript(
        [{"role": "user", "content": "Question"}],
        pending_reply="Answer…",
    )
    pump(ui)
    text = transcript_text(hud.body)
    assert "You: Question" in text
    assert "BOB: Answer…" in text

    hud.set_user("partial")
    hud.set_reply("draft")
    pump(ui)
    text = transcript_text(hud.body)
    assert "partial" in text
    assert "draft" in text
    hud.destroy()


def test_hud_apply_theme(ui):
    hud = TalkHud(ui, "ctrl+shift+space")
    hud.set_state(State.SPEAKING)
    ember = theming.preset("ember")
    hud.apply_theme(ember)
    pump(ui)
    assert hud.status.cget("text_color") == ember.speaking
    hud.destroy()
