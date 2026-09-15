"""Add RemoveFolder to heat-harvested components for per-user ICE64 compliance."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

WIX_NS = "http://schemas.microsoft.com/wix/2006/wi"
ET.register_namespace("", WIX_NS)


def _tag(name: str) -> str:
    return f"{{{WIX_NS}}}{name}"


def _add_remove_folder(directory: ET.Element) -> int:
    added = 0
    for child in directory:
        if child.tag == _tag("Directory"):
            added += _add_remove_folder(child)

    components = [child for child in directory if child.tag == _tag("Component")]
    if not components:
        return added

    last = components[-1]
    if any(grand.tag == _tag("RemoveFolder") for grand in last):
        return added

    dir_id = directory.get("Id", "dir")
    remove = ET.Element(_tag("RemoveFolder"))
    remove.set("Id", f"Remove_{dir_id}")
    remove.set("On", "uninstall")
    last.append(remove)
    return added + 1


def fix_payload(path: Path) -> int:
    tree = ET.parse(path)
    root = tree.getroot()
    added = 0
    for directory_ref in root.iter(_tag("DirectoryRef")):
        if directory_ref.get("Id") != "INSTALLFOLDER":
            continue
        for child in directory_ref:
            if child.tag == _tag("Directory"):
                added += _add_remove_folder(child)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return added


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload_wxs", type=Path)
    args = parser.parse_args()
    count = fix_payload(args.payload_wxs)
    print(f"Added {count} RemoveFolder entries to {args.payload_wxs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
