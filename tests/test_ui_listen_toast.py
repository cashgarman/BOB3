from __future__ import annotations

from bob.audio import WAVE_BARS
from bob.state import State
from bob.ui import theme as theming
from bob.ui.listen_toast import ListenToast
from tests.helpers import pump


def test_toast_present_hide_and_click(ui):
    clicks = []
    toast = ListenToast(ui, on_click=lambda: clicks.append(1))
    pump(ui, 3)
    assert toast.is_open() is False

    toast.present()
    pump(ui)
    assert toast.is_open() is True
    assert toast.status.cget("text") == "LISTENING"

    toast._clicked()
    assert clicks == [1]

    toast.hide()
    pump(ui)
    assert toast.is_open() is False
    toast.destroy()


def test_toast_set_state_opens_when_closed(ui):
    toast = ListenToast(ui)
    pump(ui, 3)
    toast.set_state(State.THINKING, "tool: clock")
    pump(ui)
    assert toast.is_open() is True
    assert toast.status.cget("text") == "THINKING"
    assert "tool: clock" in toast.meta.cget("text")
    toast.destroy()


def test_toast_waveform_while_open(ui):
    toast = ListenToast(ui)
    pump(ui, 3)
    toast.present()
    pump(ui)
    toast.set_state(State.LISTENING)
    bars = [0.1] * WAVE_BARS
    toast.set_waveform(bars)
    pump(ui)
    assert len(toast._shown) == WAVE_BARS
    assert all(v >= 0 for v in toast._shown)
    toast.destroy()


def test_toast_waveform_ignored_when_closed(ui):
    toast = ListenToast(ui)
    pump(ui, 3)
    before = list(toast._shown)
    toast.set_waveform([1.0] * WAVE_BARS)
    assert toast._shown == before
    toast.destroy()


def test_toast_apply_theme(ui):
    toast = ListenToast(ui)
    pump(ui, 3)
    toast.set_state(State.SPEAKING)
    forest = theming.preset("forest")
    toast.apply_theme(forest)
    pump(ui)
    assert toast.status.cget("text_color") == forest.speaking
    toast.destroy()
