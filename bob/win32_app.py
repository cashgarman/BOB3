"""Windows app identity: tray Settings name, taskbar grouping, window icon."""

from __future__ import annotations

import sys
from pathlib import Path

APP_ID = "Cash.Bob"
APP_NAME = "BOB"
PUBLISHER = "BOB"
EXE_NAME = "Bob.exe"


def project_root() -> Path:
    from bob.paths import project_root as _root

    return _root()


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
    ensure_tray_registration()


def preferred_launch_exe() -> Path:
    """Bob.exe host when built; pythonw only for dev trees without a branded exe."""
    branded = branded_exe()
    if branded.is_file():
        return branded
    return project_root() / ".venv" / "Scripts" / "pythonw.exe"


def launch_arguments(exe: Path) -> str:
    if exe.name.lower() == EXE_NAME.lower():
        return ""
    return "-m bob"


def ensure_tray_registration() -> None:
    """Keep Settings → tray list showing BOB (not Python) for the branded exe."""
    if sys.platform != "win32":
        return
    exe = branded_exe()
    if not exe.is_file():
        return
    try:
        import importlib.util

        wi = project_root() / "packaging" / "windows_install.py"
        if not wi.is_file():
            return
        spec = importlib.util.spec_from_file_location("windows_install", wi)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ico = icon_path()
        if ico.is_file():
            mod.register_windows_app(exe, ico, root=project_root())
    except Exception:
        return


def tk_root_hwnd(window) -> int:
    if sys.platform != "win32":
        return int(window.winfo_id())
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = int(window.winfo_id())
    root = user32.GetAncestor(hwnd, 2)  # GA_ROOT
    return int(root or hwnd)


def hide_from_taskbar(window) -> None:
    """Keep a Tk window out of the taskbar and Alt+Tab list."""
    if sys.platform != "win32":
        return
    try:
        window.attributes("-toolwindow", True)
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        hwnd = tk_root_hwnd(window)
        style = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
        style |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception:
        return


def show_in_taskbar(window) -> None:
    """Restore normal taskbar presence when the user explicitly opens a window."""
    if sys.platform != "win32":
        return
    try:
        window.attributes("-toolwindow", False)
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        hwnd = tk_root_hwnd(window)
        style = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
        style &= ~WS_EX_TOOLWINDOW
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception:
        return


def window_debug_snapshot(window) -> dict:
    try:
        return {
            "title": window.title(),
            "tk_state": window.state(),
            "viewable": bool(window.winfo_viewable()),
            "alpha": float(window.attributes("-alpha")),
        }
    except Exception as exc:
        return {"error": str(exc)}


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
