from __future__ import annotations

import pytest

from bob.state import State
from bob.ui import theme as theming
from bob.ui.overlay import Overlay

from tests.helpers import destroy_toplevels, pump


@pytest.fixture(scope="session")
def overlay():
    """One hidden CustomTkinter root for the whole session.

    Overlay is a ``CTk`` window; destroying it mid-run makes later tests fail,
    so tests must not call ``destroy()`` on this object.
    """
    theming.set_current(theming.preset("midnight"))
    try:
        win = Overlay(
            "ctrl+shift+space",
            on_toggle=lambda: None,
            on_quit=lambda: None,
            on_submit=lambda _text: None,
        )
    except Exception as exc:  # pragma: no cover - environment without Tk
        pytest.skip(f"Tk UI is not available: {exc}")
    win.ui = lambda fn: fn()
    win.withdraw()
    pump(win, 1)
    yield win
    try:
        win.destroy()
    except Exception:
        pass


@pytest.fixture
def ui(overlay):
    """Reset the main window and tear down any dialogs opened by a test."""
    submitted: list[str] = []
    toggled: list[int] = []
    overlay.submitted = submitted
    overlay.toggled = toggled
    overlay.on_submit = submitted.append
    overlay.on_toggle = lambda: toggled.append(1)
    overlay.on_quit = lambda: None
    overlay.on_hide = None
    theming.set_current(theming.preset("midnight"))
    overlay.apply_theme(theming.current())
    overlay.set_state(State.IDLE, "Toggle listen  CTRL+SHIFT+SPACE")
    overlay.set_level(0)
    overlay.set_transcript([])
    overlay.composer.delete(0, "end")
    overlay.withdraw()
    destroy_toplevels(overlay)
    pump(overlay, 1)
    yield overlay
    destroy_toplevels(overlay)
    overlay.withdraw()
