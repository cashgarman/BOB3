from __future__ import annotations

from bob.audio import WAVE_BARS
from bob.state import State
from bob.ui import theme as theming
from bob.ui.listen_toast import ListenToast
from tests.helpers import pump, transcript_text


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


def test_toast_transcript(ui):
    toast = ListenToast(ui)
    pump(ui, 3)
    toast.set_transcript(
        [{"role": "user", "content": "Hello"}],
        pending_reply="Hi there",
    )
    pump(ui)
    text = transcript_text(toast.transcript)
    assert "You: Hello" in text
    assert "Bob: Hi there" in text
    toast.destroy()


def test_toast_pin_prevents_hide(ui):
    toast = ListenToast(ui)
    pump(ui, 3)
    toast.present()
    pump(ui)
    toast._toggle_pin()
    assert toast.is_pinned() is True

    toast.hide()
    pump(ui)
    assert toast.is_open() is True

    toast.hide(force=True)
    pump(ui)
    assert toast.is_open() is False
    toast.destroy()


def test_toast_pin_button_does_not_toggle_listen(ui):
    clicks = []
    toast = ListenToast(ui, on_click=lambda: clicks.append(1))
    pump(ui, 3)
    toast.pin_btn.invoke()
    pump(ui)
    assert toast.is_pinned() is True
    assert clicks == []
    toast.destroy()


def test_toast_set_stats_updates_meters(ui):
    toast = ListenToast(ui)
    pump(ui, 3)
    toast.present()
    pump(ui)
    toast.set_state(State.THINKING, "ollama")
    toast.set_stats(gpu=0.42, vram=0.67, cpu=0.15)
    pump(ui)
    assert abs(toast.gpu_bar.get() - 0.42) < 1e-6
    assert toast.gpu_pct.cget("text") == "42%"
    assert toast.vram_pct.cget("text") == "67%"
    assert toast.cpu_pct.cget("text") == "15%"
    toast.destroy()
