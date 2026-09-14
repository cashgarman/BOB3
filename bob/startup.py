from __future__ import annotations

import sys
import winreg
from pathlib import Path

from bob.settings import ROOT

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Bob"


def _pythonw() -> Path:
    venv = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if venv.exists():
        return venv
    return Path(sys.executable).with_name("pythonw.exe")


def _vbs_path() -> Path:
    return ROOT / "bob_startup.vbs"


def write_launcher() -> Path:
    pythonw = _pythonw()
    vbs = _vbs_path()
    script = (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.CurrentDirectory = "{ROOT}"\r\n'
        f'sh.Run """{pythonw}"" -m bob", 0, False\r\n'
    )
    vbs.write_text(script, encoding="utf-8")
    return vbs


def run_command() -> str:
    vbs = write_launcher()
    return f'wscript.exe //nologo "{vbs}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable() -> None:
    command = run_command()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)


def disable() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return
    except OSError:
        return


def set_enabled(enabled: bool) -> bool:
    if enabled:
        enable()
    else:
        disable()
    return is_enabled()
