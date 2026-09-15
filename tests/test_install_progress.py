from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

import pytest

from install_progress import (
    InstallCancelled,
    append_log,
    cancel_requested,
    check_cancel,
    clear_cancel,
    clear_log,
    format_duration,
    log_note,
    log_path,
    log_phase,
    request_cancel,
    write_progress,
)


def test_cancel_flag_round_trip(tmp_path, monkeypatch):
    cancel_file = tmp_path / "bob-install.cancel"
    monkeypatch.setenv("BOB_INSTALL_CANCEL", str(cancel_file))
    clear_cancel()
    assert not cancel_requested()
    request_cancel()
    assert cancel_requested()
    with pytest.raises(InstallCancelled):
        check_cancel()
    clear_cancel()
    assert not cancel_requested()


def test_format_duration():
    assert format_duration(45) == "45s"
    assert "m" in format_duration(125)


def test_log_helpers_write_prefixed_lines(tmp_path, monkeypatch):
    log_file = tmp_path / "bob-install.log"
    monkeypatch.setenv("BOB_INSTALL_LOG", str(log_file))
    clear_log()
    log_phase(3, "Installing dependencies")
    log_note("Collecting numpy")
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert lines == ["[step 3] Installing dependencies", "  Collecting numpy"]


def test_append_log_writes_lines(tmp_path, monkeypatch):
    log_file = tmp_path / "bob-install.log"
    monkeypatch.setenv("BOB_INSTALL_LOG", str(log_file))
    clear_log()
    append_log("> pip install bob")
    append_log("  done")
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert lines == ["> pip install bob", "  done"]


def test_log_path_honors_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom.log"
    monkeypatch.setenv("BOB_INSTALL_LOG", str(custom))
    assert log_path() == custom


def test_default_state_dir_uses_localappdata(monkeypatch):
    monkeypatch.delenv("BOB_INSTALL_PROGRESS", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    from install_progress import status_path

    assert status_path() == Path(r"C:\Users\test\AppData\Local\BOB\setup\bob-install.json")


def test_write_progress_atomic_round_trip(tmp_path, monkeypatch):
    progress_file = tmp_path / "bob-install.json"
    monkeypatch.setenv("BOB_INSTALL_PROGRESS", str(progress_file))
    write_progress(phase="pip", message="first", overall=0.1)
    write_progress(phase="pip", message="second", overall=0.2)
    data = json.loads(progress_file.read_text(encoding="utf-8"))
    assert data["message"] == "second"


def test_write_progress_marks_cancelled(tmp_path, monkeypatch):
    progress_file = tmp_path / "bob-install.json"
    monkeypatch.setenv("BOB_INSTALL_PROGRESS", str(progress_file))
    write_progress(phase="cancel", message="Installation cancelled.", cancelled=True, done=True)
    data = json.loads(progress_file.read_text(encoding="utf-8"))
    assert data["cancelled"] is True
    assert data["done"] is True
