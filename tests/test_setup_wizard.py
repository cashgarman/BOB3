from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))

from bob.paths import project_root
from setup_wizard import _BootstrapProgressReporter, apply_choices


def test_project_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BOB_ROOT", str(tmp_path))
    assert project_root() == tmp_path.resolve()


def test_project_root_venv_parent(monkeypatch, tmp_path):
    monkeypatch.delenv("BOB_ROOT", raising=False)
    (tmp_path / "prompts").mkdir()
    venv = tmp_path / ".venv"
    venv.mkdir()
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    monkeypatch.chdir(tmp_path)
    assert project_root() == tmp_path.resolve()


def test_bootstrap_progress_maps_to_install_step_four(tmp_path, monkeypatch):
    monkeypatch.setenv("BOB_INSTALL_PROGRESS", str(tmp_path / "progress.json"))
    monkeypatch.setenv("BOB_INSTALL_CANCEL", str(tmp_path / "cancel.flag"))
    reporter = _BootstrapProgressReporter()
    reporter.emit(1, 8, "Pulling qwen3:4b via Ollama", 100_000_000, 2_000_000_000)
    reporter.emit(1, 8, "Pulling qwen3:4b via Ollama", 500_000_000, 2_000_000_000)
    data = __import__("json").loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert data["step"] == 5
    assert data["step_total"] == 11
    assert data["overall"] > 0.82
    assert "downloaded" in data["detail"]
    assert data["rate_bps"] > 0
    assert data["eta_seconds"] is not None


def test_apply_choices_writes_config(tmp_path, monkeypatch):
    monkeypatch.setenv("BOB_ROOT", str(tmp_path))
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.txt").write_text("You are Bob.", encoding="utf-8")
    monkeypatch.setattr("bob.startup.set_enabled", lambda enabled: enabled)

    apply_choices(tmp_path, hotkey="ctrl+shift+f5", llm_model="qwen3:4b", start_with_windows=True)
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "ctrl+shift+f5" in text
    assert "qwen3:4b" in text
    assert "start_with_windows: true" in text
