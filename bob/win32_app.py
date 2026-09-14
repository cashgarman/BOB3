"""Windows app identity: tray Settings name, taskbar grouping, window icon."""

from __future__ import annotations

import sys
from pathlib import Path

APP_ID = "Cash.Bob"
APP_NAME = "Bob"
PUBLISHER = "Bob"
EXE_NAME = "Bob.exe"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def icon_path() -> Path:
    return project_root() / "packaging" / "bob.ico"


def branded_exe() -> Path:
    return project_root() / ".venv" / "Scripts" / EXE_NAME


def apply_process_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        return


def apply_tk_icon(window) -> None:
    if sys.platform != "win32":
        return
    ico = icon_path()
    if not ico.is_file():
        return
    try:
        window.iconbitmap(str(ico))
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        window.update_idletasks()
        hwnd = int(window.winfo_id())
        user32 = ctypes.windll.user32
        root = user32.GetAncestor(hwnd, 2)
        hwnd = int(root or hwnd)
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        small = user32.LoadImageW(None, str(ico), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        big = user32.LoadImageW(None, str(ico), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, 0, small)
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, 1, big)
    except Exception:
        return
