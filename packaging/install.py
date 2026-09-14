"""Install Bob as a per-user Windows app (Start Menu, Apps & Features, tray identity)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bob import __version__
from bob.win32_app import APP_ID, APP_NAME, EXE_NAME, PUBLISHER, branded_exe, icon_path

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Bob"
APP_PATHS_KEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths\Bob.exe"
APP_CLASS_KEY = r"Software\Classes\Applications\Bob.exe"
APP_ID_KEY = rf"Software\Classes\AppUserModelId\{APP_ID}"
CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")


def _start_menu_lnk() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Bob.lnk"


def _desktop_lnk() -> Path:
    return Path(os.environ["USERPROFILE"]) / "Desktop" / "Bob.lnk"


def write_icon(dest: Path) -> Path:
    from PIL import Image, ImageDraw

    dest.parent.mkdir(parents=True, exist_ok=True)
    sizes = (16, 24, 32, 48, 64, 128, 256)
    frames: list[Image.Image] = []
    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        scale = size / 256
        outline = max(2, round(12 * scale))
        pad = max(1, round(16 * scale))
        fill = (17, 19, 24, 255)
        accent = (52, 211, 153, 255)
        draw.ellipse((pad, pad, size - pad - 1, size - pad - 1), fill=fill, outline=accent, width=outline)
        cx = size / 2
        mic_w = 36 * scale
        mic_top = 70 * scale
        mic_bot = 148 * scale
        draw.rounded_rectangle(
            (cx - mic_w / 2, mic_top, cx + mic_w / 2, mic_bot),
            radius=max(2, 18 * scale),
            fill=accent,
        )
        yoke_w = 56 * scale
        yoke_y = 150 * scale
        yoke_h = 28 * scale
        draw.arc(
            (cx - yoke_w / 2, yoke_y - yoke_h, cx + yoke_w / 2, yoke_y + yoke_h),
            start=0,
            end=180,
            fill=accent,
            width=max(2, round(8 * scale)),
        )
        stem_w = max(2, 10 * scale)
        stem_top = yoke_y + yoke_h * 0.35
        stem_bot = 196 * scale
        draw.rectangle((cx - stem_w / 2, stem_top, cx + stem_w / 2, stem_bot), fill=accent)
        base_w = 48 * scale
        base_h = max(2, 8 * scale)
        draw.rectangle((cx - base_w / 2, stem_bot, cx + base_w / 2, stem_bot + base_h), fill=accent)
        frames.append(img)
    frames[-1].save(dest, format="ICO", sizes=[(s, s) for s in sizes])
    return dest


def _compile_shortcut_helper() -> Path:
    src = Path(__file__).resolve().parent / "shortcut.cs"
    exe = Path(__file__).resolve().parent / "shortcut.exe"
    if not CSC.is_file():
        raise FileNotFoundError(f"C# compiler not found: {CSC}")
    subprocess.check_call(
        [str(CSC), "/nologo", "/target:exe", f"/out:{exe}", str(src)],
        cwd=str(src.parent),
    )
    return exe


def write_shortcut(lnk: Path, target: Path, ico: Path, helper: Path) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            str(helper),
            str(lnk),
            str(target),
            "-m bob",
            str(ROOT),
            str(ico),
            APP_ID,
            "Bob voice assistant",
        ]
    )


def write_bob_exe(ico: Path) -> Path:
    dest = branded_exe()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not CSC.is_file():
        raise FileNotFoundError(f"C# compiler not found: {CSC}")
    src = Path(__file__).with_name("bob_host.cs")
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
            f"/out:{dest}",
            str(src),
        ],
        cwd=str(src.parent),
    )
    return dest


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


def register_windows_app(exe: Path, ico: Path) -> None:
    uninstall = Path(__file__).resolve().parent.parent / "uninstall.ps1"
    _set_sz(
        winreg.HKEY_CURRENT_USER,
        UNINSTALL_KEY,
        {
            "DisplayName": APP_NAME,
            "DisplayVersion": __version__,
            "Publisher": PUBLISHER,
            "InstallLocation": str(ROOT),
            "DisplayIcon": f"{exe},0",
            "UninstallString": (
                f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{uninstall}"'
            ),
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
        {"": str(exe), "Path": str(ROOT)},
    )
    _set_sz(
        winreg.HKEY_CURRENT_USER,
        APP_CLASS_KEY,
        {"FriendlyAppName": APP_NAME, "AppUserModelID": APP_ID},
    )
    _set_sz(
        winreg.HKEY_CURRENT_USER,
        APP_ID_KEY,
        {
            "DisplayName": APP_NAME,
            "IconUri": ico.resolve().as_uri(),
            "IconResource": f"{exe},0",
        },
    )


def unregister_windows_app() -> None:
    _delete_key(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    _delete_key(winreg.HKEY_CURRENT_USER, APP_PATHS_KEY)
    _delete_key(winreg.HKEY_CURRENT_USER, APP_CLASS_KEY)
    _delete_key(winreg.HKEY_CURRENT_USER, APP_ID_KEY)


def install(*, desktop: bool = False) -> Path:
    ico = write_icon(icon_path())
    exe = write_bob_exe(ico)
    helper = _compile_shortcut_helper()
    write_shortcut(_start_menu_lnk(), exe, ico, helper)
    if desktop:
        write_shortcut(_desktop_lnk(), exe, ico, helper)
    register_windows_app(exe, ico)
    return exe


def uninstall() -> None:
    for lnk in (_start_menu_lnk(), _desktop_lnk()):
        try:
            lnk.unlink()
        except FileNotFoundError:
            pass
    unregister_windows_app()
    exe = branded_exe()
    try:
        exe.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"Could not remove {exe}: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install or uninstall Bob as a Windows app")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--desktop", action="store_true", help="Also create a Desktop shortcut")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.uninstall:
        uninstall()
        print("Bob was removed from the Start Menu, Apps list, and tray identity.")
        print("Project files, models, and .venv were left in place.")
        return 0
    exe = install(desktop=args.desktop)
    print(f"Installed {APP_NAME}")
    print(f"  App:        {exe}")
    print(f"  Start Menu: {_start_menu_lnk()}")
    print(f"  Apps list:  Settings > Apps > Installed apps")
    print("Launch Bob once, then open Settings > Personalization > Taskbar >")
    print("Other system tray icons. Bob should be listed there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
