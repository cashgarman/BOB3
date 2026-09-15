"""Install Bob as a per-user Windows app (Start Menu, Apps & Features, tray identity)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))

from bob.win32_app import APP_NAME
from windows_install import (
    branded_exe,
    compile_shortcut_helper,
    desktop_lnk,
    icon_path,
    install,
    register_windows_app,
    start_menu_lnk,
    uninstall,
    unregister_windows_app,
    write_bob_exe,
    write_icon,
    write_shortcut,
)

__all__ = [
    "branded_exe",
    "compile_shortcut_helper",
    "icon_path",
    "install",
    "register_windows_app",
    "uninstall",
    "unregister_windows_app",
    "write_bob_exe",
    "write_icon",
    "write_shortcut",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Install or uninstall BOB as a Windows app")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--desktop", action="store_true", help="Also create a Desktop shortcut")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.uninstall:
        uninstall(ROOT)
        print("BOB was removed from the Start Menu, Apps list, and tray identity.")
        print("Project files, models, and .venv were left in place.")
        return 0
    exe = install(desktop=args.desktop, root=ROOT)
    print(f"Installed {APP_NAME}")
    print(f"  App:        {exe}")
    print(f"  Start Menu: {start_menu_lnk()}")
    print("  Apps list:  Settings > Apps > Installed apps")
    print("Launch BOB once, then open Settings > Personalization > Taskbar >")
    print("Other system tray icons. BOB should be listed there.")
    if args.desktop:
        print(f"  Desktop:    {desktop_lnk()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
