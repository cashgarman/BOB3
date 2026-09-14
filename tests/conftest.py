from __future__ import annotations

import pytest

from bob.state import State
from bob.ui import theme as theming
from bob.ui.app_root import AppRoot
from bob.ui.overlay import Overlay

from tests.helpers import destroy_extra_toplevels, destroy_toplevels, pump


@pytest.fixture(scope="session")
def root():
    """Hidden tray root for CustomTkinter tests."""
    theming.set_current(theming.preset("midnight"))
    try:
        win = AppRoot()
    except Exception as exc:  # pragma: no cover - environment without Tk
        pytest.skip(f"Tk UI is not available: {exc}")
    win.ui = lambda fn: fn()
    pump(win, 1)
    yield win
    try:
        win.destroy()
    except Exception:
        pass


@pytest.fixture(scope="session")
def overlay(root):
    """Optional Bob window hosted on the hidden tray root."""
    try:
        win = Overlay(
            root,
            on_toggle=lambda: None,
            on_quit=lambda: None,
            on_submit=lambda _text: None,
        )
    except Exception as exc:  # pragma: no cover - environment without Tk
        pytest.skip(f"Tk UI is not available: {exc}")
    win.ui = lambda fn: fn()
    win.withdraw()
    pump(root, 1)
    yield win


@pytest.fixture
def ui(overlay):
    """Reset the overlay window and tear down any dialogs opened by a test."""
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
    overlay.set_state(State.IDLE)
    overlay.set_level(0)
    overlay.set_transcript([])
    overlay.composer.delete(0, "end")
    overlay._user_visible = False
    overlay.withdraw()
    destroy_toplevels(overlay)
    destroy_extra_toplevels(overlay.master, keep=overlay)
    pump(overlay.master, 1)
    yield overlay
    destroy_toplevels(overlay)
    destroy_extra_toplevels(overlay.master, keep=overlay)
    overlay.withdraw()
