from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

from unittest.mock import MagicMock, patch

from install_progress import format_eta, format_rate
from pip_with_progress import PipProgressTracker, pip_install


def test_format_helpers():
    assert "MB" in format_rate(2 * 1024 * 1024)
    assert "remaining" in format_eta(125)


def test_tracker_parses_download_line():
    tracker = PipProgressTracker(
        overall_start=0.2,
        overall_span=0.5,
        step=3,
        step_total=4,
        label="pip",
    )
    tracker.handle_line("Collecting numpy")
    tracker.handle_line("  Downloading numpy-1.0-py3-none-any.whl (12.5 MB)")
    tracker.handle_line("     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 12.5/12.5 MB 5.2 MB/s eta 0:00:00")


def test_pip_install_puts_index_url_after_install_subcommand(tmp_path: Path):
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    tracker = PipProgressTracker(
        overall_start=0.2,
        overall_span=0.1,
        step=3,
        step_total=4,
        label="pip",
    )
    proc = MagicMock()
    proc.stdout = iter(["done\n"])
    proc.wait.return_value = 0

    with (
        patch("pip_with_progress.check_cancel"),
        patch("pip_with_progress.cancel_requested", return_value=False),
        patch("pip_with_progress.append_log"),
    ):
        with patch("pip_with_progress.subprocess.Popen", return_value=proc) as popen:
            pip_install(
                python,
                ["--index-url", "https://pypi.org/simple", "--upgrade", "pip"],
                tracker,
            )
            cmd = popen.call_args.args[0]
    assert cmd[:4] == [str(python), "-m", "pip", "install"]
    assert "--index-url" in cmd
    install_idx = cmd.index("install")
    index_idx = cmd.index("--index-url")
    assert index_idx > install_idx


def test_tracker_aggregates_package_sizes(tmp_path: Path, monkeypatch):
    progress_file = tmp_path / "bob-install.json"
    monkeypatch.setenv("BOB_INSTALL_PROGRESS", str(progress_file))
    tracker = PipProgressTracker(
        overall_start=0.2,
        overall_span=0.5,
        step=3,
        step_total=4,
        label="Downloading BOB dependencies from PyPI…",
    )
    tracker.handle_line("  Downloading numpy-1.0-py3-none-any.whl (12.5 MB)")
    tracker.handle_line("  Downloading torch-2.5.1-cp312-cp312-win_amd64.whl (230.5 MB)")
    tracker.handle_line("     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 115.0/230.5 MB 5.2 MB/s eta 0:00:22")
    data = __import__("json").loads(progress_file.read_text(encoding="utf-8"))
    assert data["total"] > 200 * 1024 * 1024
    assert "downloaded" in data["detail"]


def test_tracker_keeps_label_as_status_message(tmp_path: Path, monkeypatch):
    progress_file = tmp_path / "bob-install.json"
    monkeypatch.setenv("BOB_INSTALL_PROGRESS", str(progress_file))
    tracker = PipProgressTracker(
        overall_start=0.2,
        overall_span=0.5,
        step=3,
        step_total=4,
        label="Downloading BOB dependencies from PyPI…",
    )
    tracker.emit(detail="Collecting numpy", stage=0.1)
    data = __import__("json").loads(progress_file.read_text(encoding="utf-8"))
    assert data["message"] == "Downloading BOB dependencies from PyPI…"
    assert data["detail"] == "Collecting numpy"
