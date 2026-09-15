"""Shared Windows app registration: icon, Bob.exe host, shortcuts, HKCU identity."""

from __future__ import annotations

import os
import subprocess
import sys
import winreg
from pathlib import Path

from bob import __version__
from bob.win32_app import APP_ID, APP_NAME, EXE_NAME, PUBLISHER

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Bob"
APP_PATHS_KEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths\Bob.exe"
APP_CLASS_KEY = r"Software\Classes\Applications\Bob.exe"
APP_ID_KEY = rf"Software\Classes\AppUserModelId\{APP_ID}"
CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")


def default_root() -> Path:
    return Path(__file__).resolve().parent.parent


def start_menu_lnk() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "BOB.lnk"


def desktop_lnk() -> Path:
    return Path(os.environ["USERPROFILE"]) / "Desktop" / "BOB.lnk"


def branded_exe(root: Path | None = None) -> Path:
    return (root or default_root()) / ".venv" / "Scripts" / EXE_NAME


def logo_path(root: Path | None = None) -> Path:
    return (root or default_root()) / "packaging" / "logo.png"


def icon_path(root: Path | None = None) -> Path:
    return (root or default_root()) / "packaging" / "bob.ico"


def _load_logo(root: Path | None = None):
    from PIL import Image

    src = logo_path(root)
    if not src.is_file():
        raise FileNotFoundError(f"BOB logo not found: {src}")
    return Image.open(src).convert("RGBA")


def write_icon(dest: Path, root: Path | None = None) -> Path:
    from PIL import Image

    dest.parent.mkdir(parents=True, exist_ok=True)
    base = _load_logo(root)
    sizes = (16, 24, 32, 48, 64, 128, 256)
    frames = [base.resize((size, size), Image.Resampling.LANCZOS) for size in sizes]
    frames[-1].save(dest, format="ICO", sizes=[(s, s) for s in sizes])
    return dest


def write_logo_png(dest: Path, size: int = 128, root: Path | None = None) -> Path:
    from PIL import Image

    img = _load_logo(root).resize((size, size), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return dest


def compile_shortcut_helper(packaging_dir: Path | None = None) -> Path:
    base = packaging_dir or Path(__file__).resolve().parent
    src = base / "shortcut.cs"
    exe = base / "shortcut.exe"
    if not CSC.is_file():
        raise FileNotFoundError(f"C# compiler not found: {CSC}")
    subprocess.check_call(
        [str(CSC), "/nologo", "/target:exe", f"/out:{exe}", str(src)],
        cwd=str(src.parent),
    )
    return exe


def write_shortcut(lnk: Path, target: Path, ico: Path, helper: Path, workdir: Path, arguments: str = "") -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            str(helper),
            str(lnk),
            str(target),
            arguments,
            str(workdir),
            str(ico),
            APP_ID,
            "BOB voice assistant",
        ]
    )


def write_bob_exe(ico: Path, dest: Path | None = None, host_src: Path | None = None) -> Path:
    out = dest or branded_exe()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not CSC.is_file():
        raise FileNotFoundError(f"C# compiler not found: {CSC}")
    src = host_src or Path(__file__).with_name("bob_host.cs")
    fx = CSC.parent
    subprocess.check_call(
        [
            str(CSC),
            "/nologo",
            "/optimize",
            "/target:winexe",
            "/platform:x64",
            f"/reference:{fx / 'System.Windows.Forms.dll'}",
            f"/reference:{fx / 'System.Drawing.dll'}",
            f"/win32icon:{ico}",
            f"/out:{out}",
            str(src),
        ],
        cwd=str(src.parent),
    )
    return out


def _set_sz(root, path: str, values: dict[str, str], extra: dict[str, tuple[int, object]] | None = None) -> None:
    key = winreg.CreateKey(root, path)
    try:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        if extra:
            for name, (kind, value) in extra.items():
                winreg.SetValueEx(key, name, 0, kind, value)
    finally:
        winreg.CloseKey(key)


def _delete_key(root, path: str) -> None:
    try:
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        return
    except OSError:
        return


def cleanup_stale_tray_entries(exe: Path | None = None, root: Path | None = None) -> None:
    """Drop ghost tray / notification entries from older BOB or pythonw launches."""
    install_root = (root or default_root()).resolve()

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\AppUserModelId") as parent:
            for name in _enum_subkeys(parent):
                if name == APP_ID:
                    continue
                if "bob" in name.lower():
                    _delete_key(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{name}")
    except OSError:
        pass

    notif_root = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, notif_root) as parent:
            for name in _enum_subkeys(parent):
                lower = name.lower()
                if name == APP_ID or "bob" in lower:
                    _delete_key(winreg.HKEY_CURRENT_USER, rf"{notif_root}\{name}")
    except OSError:
        pass

    tray_notify = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\TrayNotify"
    for value in ("IconStreams", "PastIconsStream"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, tray_notify, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, value)
        except OSError:
            pass

    # pythonw-based BOB runs show up as "Python" in tray settings; remove those ghosts.
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\Applications") as parent:
            for name in _enum_subkeys(parent):
                if not name.lower().endswith("pythonw.exe"):
                    continue
                try:
                    with winreg.OpenKey(parent, name) as app_key:
                        open_with, _ = winreg.QueryValueEx(app_key, "AppUserModelID")
                        if isinstance(open_with, str) and "bob" in open_with.lower():
                            _delete_key(winreg.HKEY_CURRENT_USER, rf"Software\Classes\Applications\{name}")
                except OSError:
                    pass
    except OSError:
        pass


def _enum_subkeys(key) -> list[str]:
    names: list[str] = []
    index = 0
    while True:
        try:
            names.append(winreg.EnumKey(key, index))
        except OSError:
            break
        index += 1
    return names


def register_windows_app(
    exe: Path,
    ico: Path,
    *,
    root: Path | None = None,
    uninstall_string: str | None = None,
) -> None:
    install_root = root or default_root()
    cleanup_stale_tray_entries(exe, install_root)
    uninstall = uninstall_string or (
        f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{install_root / "uninstall.ps1"}"'
    )
    _set_sz(
        winreg.HKEY_CURRENT_USER,
        UNINSTALL_KEY,
        {
            "DisplayName": APP_NAME,
            "DisplayVersion": __version__,
            "Publisher": PUBLISHER,
            "InstallLocation": str(install_root),
            "DisplayIcon": f"{exe},0",
            "UninstallString": uninstall,
            "HelpLink": "",
        },
        extra={
            "NoModify": (winreg.REG_DWORD, 1),
            "NoRepair": (winreg.REG_DWORD, 1),
        },
    )
    _set_sz(
        winreg.HKEY_CURRENT_USER,
        APP_PATHS_KEY,
        {"": str(exe), "Path": str(install_root)},
    )
    _set_sz(
        winreg.HKEY_CURRENT_USER,
        APP_CLASS_KEY,
        {
            "FriendlyAppName": APP_NAME,
            "AppUserModelID": APP_ID,
            "ApplicationName": APP_NAME,
            "ApplicationCompany": PUBLISHER,
        },
    )
    _set_sz(
        winreg.HKEY_CURRENT_USER,
        APP_ID_KEY,
        {
            "DisplayName": APP_NAME,
            "CustomActivator": str(exe.resolve()),
            "IconUri": ico.resolve().as_uri(),
            "IconResource": f"{exe.resolve()},0",
        },
    )


def unregister_windows_app() -> None:
    cleanup_stale_tray_entries()
    _delete_key(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    _delete_key(winreg.HKEY_CURRENT_USER, APP_PATHS_KEY)
    _delete_key(winreg.HKEY_CURRENT_USER, APP_CLASS_KEY)
    _delete_key(winreg.HKEY_CURRENT_USER, APP_ID_KEY)


def install(*, desktop: bool = False, root: Path | None = None) -> Path:
    install_root = root or default_root()
    ico = write_icon(icon_path(install_root))
    exe = write_bob_exe(ico, dest=branded_exe(install_root), host_src=install_root / "packaging" / "bob_host.cs")
    helper = compile_shortcut_helper(install_root / "packaging")
    write_shortcut(start_menu_lnk(), exe, ico, helper, install_root, arguments="")
    if desktop:
        write_shortcut(desktop_lnk(), exe, ico, helper, install_root, arguments="")
    register_windows_app(exe, ico, root=install_root)
    return exe


def uninstall(root: Path | None = None) -> None:
    for lnk in (start_menu_lnk(), desktop_lnk()):
        try:
            lnk.unlink()
        except FileNotFoundError:
            pass
    unregister_windows_app()
    exe = branded_exe(root)
    try:
        exe.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"Could not remove {exe}: {exc}", file=sys.stderr)
