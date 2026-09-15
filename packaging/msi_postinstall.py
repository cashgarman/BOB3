"""MSI deferred action: Python venv, online pip deps, Bob.exe, Windows registration."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_ROOT_HINT = _PKG.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))
if str(_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(_ROOT_HINT))

from install_progress import INSTALL_STEPS, InstallCancelled, check_cancel, log_note, log_phase, write_progress
from pip_with_progress import PipProgressTracker, pip_install
from windows_install import icon_path, install, uninstall, write_icon

PYPI_INDEX = "https://pypi.org/simple"


def _wheelhouse_has_packages(wheelhouse: Path) -> bool:
    if not wheelhouse.is_dir():
        return False
    for path in wheelhouse.iterdir():
        if path.suffix in {".whl", ".tar.gz", ".zip"}:
            return True
    return False


def _venv_ready(root: Path) -> bool:
    cfg = root / ".venv" / "pyvenv.cfg"
    py = root / ".venv" / "Scripts" / "python.exe"
    if not cfg.is_file() or not py.is_file():
        return False
    try:
        subprocess.run(
            [str(py), "-c", "import sys"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _ensure_install_files(root: Path) -> None:
    if not (root / "requirements.txt").is_file():
        raise FileNotFoundError(
            f"Bob install files are missing from {root}. "
            "Remove that folder and run BobSetup.exe again."
        )


def _ensure_venv(root: Path) -> None:
    if _venv_ready(root):
        log_note("Python virtual environment is ready")
        return
    broken = root / ".venv"
    if broken.exists():
        log_note("Removing broken virtual environment")
        shutil.rmtree(broken, ignore_errors=True)
    embed_py = root / "python" / "python.exe"
    if embed_py.is_file():
        log_note(f"Creating virtual environment with {embed_py}")
        subprocess.check_call([str(embed_py), "-m", "venv", "--copies", str(root / ".venv")])
    if not _venv_ready(root):
        raise FileNotFoundError(
            "Python 3.12 is not available. Re-run BobSetup.exe or install Python 3.12, then repair Bob."
        )


def _pip_install_cmd(root: Path, wheelhouse: Path) -> list[str]:
    """Fast, reproducible pip flags (matches setup.ps1: ignore user extra-indexes)."""
    cache = root / ".pip-cache"
    cache.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = [
        "--isolated",
        "--prefer-binary",
        "--no-compile",
        "--cache-dir",
        str(cache),
    ]
    if _wheelhouse_has_packages(wheelhouse):
        cmd += ["--no-index", "--find-links", str(wheelhouse)]
    else:
        cmd += ["--index-url", PYPI_INDEX]
    return cmd


def postinstall(root: Path, *, desktop: bool = False, python_installer: Path | None = None) -> None:
    root = Path(root)
    check_cancel()
    _ensure_install_files(root)
    os.chdir(root)
    log_phase(3, "Preparing Python environment")
    write_progress(
        phase="python",
        message="Preparing Python environment…",
        overall=0.05,
        stage=0.1,
        step=3,
        step_total=INSTALL_STEPS,
    )

    _ensure_venv(root)
    pip = root / ".venv" / "Scripts" / "python.exe"
    wheelhouse = root / "wheelhouse"
    req = root / "requirements.txt"
    offline = _wheelhouse_has_packages(wheelhouse)
    pip_args = _pip_install_cmd(root, wheelhouse)
    bob_target = "bob" if offline else str(root)
    install_args = [*pip_args, "--upgrade", "pip", "wheel"]
    if req.is_file():
        install_args += ["-r", str(req)]
    install_args.append(bob_target)

    check_cancel()
    log_phase(
        3,
        "Downloading and installing BOB dependencies (online)"
        if not offline
        else "Installing BOB dependencies from wheelhouse",
    )
    pip_install(
        pip,
        install_args,
        PipProgressTracker(
            overall_start=0.18,
            overall_span=0.64,
            step=3,
            step_total=INSTALL_STEPS,
            label="Downloading and installing BOB dependencies…"
            if not offline
            else "Installing BOB dependencies…",
        ),
    )

    log_phase(3, "Creating BOB.exe and shortcuts")
    write_progress(
        phase="launcher",
        message="Creating BOB.exe and shortcuts…",
        overall=0.78,
        stage=0.4,
        step=3,
        step_total=INSTALL_STEPS,
    )
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ["BOB_ROOT"] = str(root)
    write_icon(icon_path(root))
    install(desktop=desktop, root=root)

    log_phase(3, "Registering BOB with Windows")
    write_progress(
        phase="register",
        message="Registering BOB with Windows…",
        overall=0.82,
        stage=1.0,
        step=3,
        step_total=INSTALL_STEPS,
        done=True,
    )


def remove(root: Path) -> None:
    root = Path(root)
    try:
        from bob.startup import disable

        disable()
    except Exception:
        pass
    uninstall(root)
    for name in (".venv", "python"):
        path = root / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main_impl(argv)
    except InstallCancelled:
        write_progress(phase="cancel", message="Installation cancelled.", cancelled=True, done=True)
        return 2
    except Exception as exc:
        write_progress(
            phase="error",
            message=str(exc),
            error=str(exc),
            done=True,
            step=3,
            step_total=INSTALL_STEPS,
        )
        return 1


def _main_impl(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)
    if args.uninstall:
        remove(args.root)
        return 0
    postinstall(args.root, desktop=args.desktop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
