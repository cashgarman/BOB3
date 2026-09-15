from __future__ import annotations

import sys
from pathlib import Path
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

import msi_postinstall


def test_product_wxs_does_not_run_postinstall_inside_msi():
    text = (ROOT / "installer" / "wix" / "Product.wxs").read_text(encoding="utf-8")
    assert "SetRunPostInstall" not in text
    assert (ROOT / "packaging" / "bob_setup_ui.cs").is_file()


def test_build_script_fixes_ice64_and_suppresses_parent_programs_dir():
    text = (ROOT / "installer" / "scripts" / "build.ps1").read_text(encoding="utf-8")
    assert "fix-payload-ice64.py" in text
    assert "-sice:ICE64" in text


def test_build_script_does_not_bundle_wheelhouse():
    text = (ROOT / "installer" / "scripts" / "build.ps1").read_text(encoding="utf-8")
    assert "pip download" not in text
    assert "pip wheel" not in text
    assert "wheelhouse" not in text


def test_postinstall_uses_pypi_when_no_wheelhouse(tmp_path: Path):
    root = tmp_path / "bob"
    root.mkdir()
    (root / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='bob'\n", encoding="utf-8")
    venv_scripts = root / ".venv" / "Scripts"
    venv_scripts.mkdir(parents=True)
    (venv_scripts / "python.exe").write_text("", encoding="utf-8")

    calls: list[list[str]] = []

    with (
        patch.object(msi_postinstall, "check_cancel"),
        patch.object(msi_postinstall, "_venv_ready", return_value=True),
        patch.object(msi_postinstall, "pip_install", side_effect=lambda pip, args, tracker: calls.append([str(pip), *args])),
        patch.object(msi_postinstall, "write_icon"),
        patch.object(msi_postinstall, "install"),
        patch.object(msi_postinstall.os, "chdir"),
    ):
        msi_postinstall.postinstall(root)

    assert len(calls) == 1
    cmd = calls[0]
    joined = " ".join(cmd)
    assert "--isolated" in joined
    assert "--prefer-binary" in joined
    assert "--index-url" in joined and "pypi.org" in joined
    assert str(root) in joined
    assert "-r" in joined
    assert "--no-index" not in joined


def test_venv_ready_requires_pyvenv_cfg(tmp_path: Path):
    root = tmp_path / "bob"
    scripts = root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("", encoding="utf-8")
    assert not msi_postinstall._venv_ready(root)

    (root / ".venv" / "pyvenv.cfg").write_text("home = C:\\Python312\n", encoding="utf-8")
    with patch.object(msi_postinstall.subprocess, "run", return_value=msi_postinstall.subprocess.CompletedProcess([], 0)):
        assert msi_postinstall._venv_ready(root)


def test_ensure_install_files_requires_requirements(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="install files are missing"):
        msi_postinstall._ensure_install_files(tmp_path)


def test_main_returns_error_exit_code_on_failure(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    with patch.object(msi_postinstall, "postinstall", side_effect=RuntimeError("pip exploded")):
        assert msi_postinstall.main(["--root", str(tmp_path)]) == 1


def test_main_returns_cancel_exit_code(tmp_path: Path, monkeypatch):
    cancel_file = tmp_path / "bob-install.cancel"
    monkeypatch.setenv("BOB_INSTALL_CANCEL", str(cancel_file))
    cancel_file.write_text("1", encoding="utf-8")

    with patch.object(msi_postinstall, "check_cancel", side_effect=msi_postinstall.InstallCancelled("cancelled")):
        assert msi_postinstall.main(["--root", str(tmp_path)]) == 2


def test_setup_ui_supports_graceful_cancel():
    text = (ROOT / "packaging" / "bob_setup_ui.cs").read_text(encoding="utf-8")
    assert "RequestCancel" in text
    assert "RollbackInstall" in text
    assert "BOB_INSTALL_CANCEL" in text
    assert "OperationCanceledException" in text


def test_setup_ui_has_command_log():
    text = (ROOT / "packaging" / "bob_setup_ui.cs").read_text(encoding="utf-8")
    assert "_logBox" in text
    assert "TailInstallLog" in text
    assert "BOB_INSTALL_LOG" in text


def test_postinstall_ps1_propagates_cancel_exit_code():
    text = (ROOT / "packaging" / "msi_postinstall.ps1").read_text(encoding="utf-8")
    assert "Get-CancelPath" in text
    assert "exit 2" in text


def test_postinstall_uses_wheelhouse_when_present(tmp_path: Path):
    root = tmp_path / "bob"
    root.mkdir()
    (root / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "numpy-1.0-py3-none-any.whl").write_text("", encoding="utf-8")
    venv_scripts = root / ".venv" / "Scripts"
    venv_scripts.mkdir(parents=True)
    (venv_scripts / "python.exe").write_text("", encoding="utf-8")

    calls: list[list[str]] = []

    with (
        patch.object(msi_postinstall, "check_cancel"),
        patch.object(msi_postinstall, "_venv_ready", return_value=True),
        patch.object(msi_postinstall, "pip_install", side_effect=lambda pip, args, tracker: calls.append([str(pip), *args])),
        patch.object(msi_postinstall, "write_icon"),
        patch.object(msi_postinstall, "install"),
        patch.object(msi_postinstall.os, "chdir"),
    ):
        msi_postinstall.postinstall(root)

    assert len(calls) == 1
    joined = " ".join(calls[0])
    assert "--isolated" in joined
    assert "--no-index" in joined and "--find-links" in joined
    assert joined.endswith("bob")
