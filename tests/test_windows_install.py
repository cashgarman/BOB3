from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

from windows_install import cleanup_stale_tray_entries
from bob.win32_app import launch_arguments


def test_write_shortcut_defaults_to_no_arguments():
    text = Path(ROOT / "packaging" / "windows_install.py").read_text(encoding="utf-8")
    assert 'arguments: str = ""' in text


def test_launch_arguments_for_branded_exe(tmp_path: Path):
    bob = tmp_path / "Bob.exe"
    bob.write_bytes(b"")
    assert launch_arguments(bob) == ""


def test_launch_arguments_for_pythonw(tmp_path: Path):
    pyw = tmp_path / "pythonw.exe"
    pyw.write_bytes(b"")
    assert launch_arguments(pyw) == "-m bob"


def test_cleanup_stale_tray_entries_removes_other_bob_aumids(tmp_path, monkeypatch):
    deleted: list[str] = []

    class FakeKey:
        def __init__(self, names):
            self._names = names

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_open(root, path, *args, **kwargs):
        if path.endswith("AppUserModelId"):
            return FakeKey(["Cash.Bob", "Old.Bob.Ghost", "Other.App"])
        if path.endswith("Notifications\\Settings"):
            return FakeKey(["Cash.Bob", "Some.Other.App"])
        if path.endswith("Applications"):
            return FakeKey([])
        raise FileNotFoundError(path)

    def fake_delete(root, path):
        deleted.append(path)

    monkeypatch.setattr("windows_install.winreg.OpenKey", fake_open)
    monkeypatch.setattr("windows_install._delete_key", fake_delete)
    monkeypatch.setattr("windows_install._enum_subkeys", lambda key: key._names)

    cleanup_stale_tray_entries(root=tmp_path)

    assert rf"Software\Classes\AppUserModelId\Old.Bob.Ghost" in deleted
    assert rf"Software\Classes\AppUserModelId\Cash.Bob" not in deleted
    assert any("Notifications" in path and "Cash.Bob" in path for path in deleted)
