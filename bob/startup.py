from __future__ import annotations

import sys
import winreg
from pathlib import Path

from bob.paths import project_root
from bob.win32_app import branded_exe

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Bob"


def _root() -> Path:
    return project_root()


def _pythonw() -> Path:
    branded = branded_exe()
    if branded.is_file():
        return branded
    venv = _root() / ".venv" / "Scripts" / "pythonw.exe"
    if venv.exists():
        return venv
    return Path(sys.executable).with_name("pythonw.exe")


def _vbs_path() -> Path:
    return _root() / "bob_startup.vbs"


def write_launcher() -> Path:
    branded = branded_exe()
    vbs = _vbs_path()
    if branded.is_file():
        script = (
            'Set sh = CreateObject("WScript.Shell")\r\n'
            f'sh.CurrentDirectory = "{_root()}"\r\n'
            f'sh.Run """{branded}""", 0, False\r\n'
        )
    else:
        run_ps1 = _root() / "run.ps1"
        script = (
            'Set sh = CreateObject("WScript.Shell")\r\n'
            f'sh.CurrentDirectory = "{_root()}"\r\n'
            f'sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""{run_ps1}""", 0, False\r\n'
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
