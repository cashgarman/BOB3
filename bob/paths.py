"""Resolve Bob's install / project root for both editable and MSI layouts."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    env = (os.environ.get("BOB_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()

    venv = (os.environ.get("VIRTUAL_ENV") or "").strip()
    if venv:
        parent = Path(venv).resolve().parent
        if _looks_like_root(parent):
            return parent

    cwd = Path.cwd()
    if _looks_like_root(cwd):
        return cwd

    package_parent = Path(__file__).resolve().parent.parent
    if _looks_like_root(package_parent):
        return package_parent

    if venv:
        return Path(venv).resolve().parent
    return package_parent


def _looks_like_root(path: Path) -> bool:
    return (path / "prompts").is_dir() or (path / "config.yaml").is_file() or (path / "run.ps1").is_file()
