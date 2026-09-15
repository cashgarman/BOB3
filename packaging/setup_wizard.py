"""First-run setup: listen hotkey, VRAM LLM pick, startup, then download models."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_ROOT_HINT = _PKG.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))
if str(_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(_ROOT_HINT))


def _prepare(root: Path) -> Path:
    root = Path(root).resolve()
    os.environ["BOB_ROOT"] = str(root)
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def apply_choices(
    root: Path,
    *,
    hotkey: str,
    llm_model: str,
    start_with_windows: bool,
) -> None:
    root = _prepare(root)
    from bob.hotkeys import parse_hotkey
    from bob.settings import load_settings
    from bob.startup import set_enabled

    spec = str(hotkey or "").strip().lower()
    parse_hotkey(spec)
    settings = load_settings(root / "config.yaml")
    settings.hotkey = spec
    settings.llm_model = llm_model
    settings.start_with_windows = bool(start_with_windows)
    settings.save(root / "config.yaml")
    set_enabled(bool(start_with_windows))


class _BootstrapProgressReporter:
    OVERALL_START = 0.82
    OVERALL_SPAN = 0.18

    def __init__(self) -> None:
        import time

        from install_progress import BOOTSTRAP_STAGE_DURATIONS_SECONDS, BOOTSTRAP_STEP_START, INSTALL_STEPS

        self._time = time
        self._install_steps = INSTALL_STEPS
        self._bootstrap_step_start = BOOTSTRAP_STEP_START
        self._stage_durations = BOOTSTRAP_STAGE_DURATIONS_SECONDS
        self._last_completed: int | None = None
        self._last_time = time.time()
        self._install_started = self._last_time
        self._current_stage = -1

    def emit(self, stage: int, total: int, name: str, completed: int | None, nbytes: int | None) -> None:
        from install_progress import check_cancel, format_bytes, format_rate, log_note, log_phase, write_progress

        check_cancel()
        now = self._time.time()
        if stage != self._current_stage:
            self._current_stage = stage
            self._last_completed = None
            self._last_time = now
        if nbytes:
            stage_frac = min(1.0, (completed or 0) / max(nbytes, 1))
        elif completed is not None:
            stage_frac = 1.0 if completed else 0.2
        else:
            stage_frac = 0.0
        bootstrap_frac = (stage + stage_frac) / max(total, 1)
        overall = self.OVERALL_START + self.OVERALL_SPAN * bootstrap_frac
        install_step = self._bootstrap_step_start + stage

        rate_bps: float | None = None
        eta_seconds: float | None = None
        if completed is not None and nbytes and nbytes > 0:
            dt = max(0.001, now - self._last_time)
            if self._last_completed is not None and completed >= self._last_completed:
                rate_bps = (completed - self._last_completed) / dt
            self._last_completed = completed
            self._last_time = now
            if rate_bps and rate_bps > 0:
                eta_seconds = max(0.0, (nbytes - completed) / rate_bps)

        detail_parts: list[str] = []
        if completed is not None and nbytes:
            detail_parts.append(f"{format_bytes(completed)} / {format_bytes(nbytes)} downloaded")
        if rate_bps:
            detail_parts.append(format_rate(rate_bps))
        if eta_seconds is not None:
            detail_parts.append(f"{int(eta_seconds)}s left for this download")
        step_duration = (
            self._stage_durations[stage]
            if stage < len(self._stage_durations)
            else 120.0
        )
        overall_eta = None
        if eta_seconds is not None:
            remaining_stages = max(0, total - stage - 1)
            overall_eta = eta_seconds + remaining_stages * step_duration * 0.5
        elif bootstrap_frac > 0:
            elapsed = now - self._install_started
            overall_eta = max(0.0, elapsed * (1.0 - overall) / max(overall, 0.01))

        extra = ""
        if completed is not None and nbytes:
            extra = f" {format_bytes(completed)} / {format_bytes(nbytes)}"
        print(f"{name}{extra}", flush=True)
        log_phase(install_step, name + extra)
        if rate_bps:
            log_note(f"{format_rate(rate_bps)}" + (f", {int(eta_seconds)}s left" if eta_seconds else ""))
        elif completed is not None and nbytes:
            log_note(f"{format_bytes(completed)} / {format_bytes(nbytes)}")
        write_progress(
            phase="download",
            step=install_step,
            step_total=self._install_steps,
            message=name,
            detail="  ·  ".join(detail_parts) if detail_parts else None,
            overall=overall,
            stage=stage_frac,
            completed=completed,
            total=nbytes,
            rate_bps=rate_bps,
            eta_seconds=eta_seconds,
            step_eta_seconds=eta_seconds,
            step_duration_seconds=step_duration,
            overall_eta_seconds=overall_eta,
        )


def run_quiet(
    root: Path,
    *,
    hotkey: str | None = None,
    llm_model: str | None = None,
    start_with_windows: bool | None = None,
    skip_download: bool = False,
) -> int:
    root = _prepare(root)
    from bob.llm_recommend import recommend_llm
    from bob.settings import Settings
    from bootstrap_models import bootstrap_all
    from install_progress import write_progress

    rec = recommend_llm()
    defaults = Settings()
    from install_progress import log_note, log_phase

    chosen_model = llm_model or rec.recommended
    log_phase(None, f"Applying settings: hotkey={hotkey or defaults.hotkey}, model={chosen_model}")
    apply_choices(
        root,
        hotkey=hotkey or defaults.hotkey,
        llm_model=chosen_model,
        start_with_windows=True if start_with_windows is None else start_with_windows,
    )
    if skip_download:
        return 0

    log_phase(4, "Starting model downloads")
    reporter = _BootstrapProgressReporter()
    bootstrap_all(root, on_progress=reporter.emit)
    from install_progress import INSTALL_STEPS

    write_progress(
        phase="done",
        message="BOB is ready",
        overall=1.0,
        stage=1.0,
        step=INSTALL_STEPS,
        step_total=INSTALL_STEPS,
        done=True,
    )
    return 0


def run_ui(root: Path, *, launch_default: bool = True) -> int:
    root = _prepare(root)
    import customtkinter as ctk

    from bob.hotkeys import HotkeyRecorder, parse_hotkey
    from bob.llm_recommend import recommend_llm
    from bob.settings import Settings
    from bob.ui import theme as theming
    from bootstrap_models import bootstrap_all
    from install_progress import format_bytes, write_progress
    from windows_install import branded_exe

    theming.set_current(theming.preset("midnight"))
    theme = theming.current()
    rec = recommend_llm()
    defaults = Settings()
    state = {
        "hotkey": defaults.hotkey,
        "llm_model": rec.recommended,
        "start_with_windows": True,
        "error": "",
        "launch": launch_default,
    }

    app = ctk.CTk()
    app.title("Set up BOB")
    app.geometry("560x520")
    app.minsize(520, 480)
    app.configure(**theme.window())
    try:
        from bob.win32_app import apply_tk_icon

        apply_tk_icon(app)
    except Exception:
        pass

    title_row = ctk.CTkFrame(app, fg_color="transparent")
    title_row.pack(anchor="w", fill="x", padx=24, pady=(20, 4))
    logo_file = root / "packaging" / "logo.png"
    if logo_file.is_file():
        from PIL import Image

        logo_img = ctk.CTkImage(
            light_image=Image.open(logo_file),
            dark_image=Image.open(logo_file),
            size=(48, 48),
        )
        ctk.CTkLabel(title_row, image=logo_img, text="").pack(side="left", padx=(0, 12))
    header = ctk.CTkLabel(title_row, text="Set up BOB", font=theme.font(22, "bold"), **theme.label_style())
    header.pack(side="left", anchor="w")
    subtitle = ctk.CTkLabel(app, text="", font=theme.font(13), **theme.label_style(muted=True))
    subtitle.pack(anchor="w", padx=24)

    body = ctk.CTkFrame(app, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=24, pady=12)
    nav = ctk.CTkFrame(app, fg_color="transparent")
    nav.pack(fill="x", padx=24, pady=(0, 20))

    pages: dict[str, ctk.CTkFrame] = {}
    current = {"name": "hotkey"}
    recorder: dict[str, HotkeyRecorder | None] = {"r": None}

    def show(name: str) -> None:
        current["name"] = name
        for key, frame in pages.items():
            if key == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        back_btn.configure(state="normal" if name in {"llm", "startup"} else "disabled")
        if name == "download":
            next_btn.pack_forget()
            back_btn.configure(state="disabled")
        elif name == "done":
            next_btn.configure(text="Finish")
            next_btn.pack(side="right")
        else:
            next_btn.configure(text="Next")
            next_btn.pack(side="right")

    def stop_recorder() -> None:
        rec_obj = recorder["r"]
        recorder["r"] = None
        if rec_obj:
            rec_obj.stop()

    # --- page 1: hotkey ---
    hotkey_page = ctk.CTkFrame(body, fg_color="transparent")
    pages["hotkey"] = hotkey_page
    ctk.CTkLabel(
        hotkey_page,
        text="Press a key to start and stop listening",
        font=theme.font(16, "bold"),
        **theme.label_style(),
    ).pack(anchor="w", pady=(8, 8))
    hotkey_var = ctk.StringVar(value=state["hotkey"].upper())
    hotkey_btn = ctk.CTkButton(hotkey_page, text=hotkey_var.get(), **theme.button())
    hotkey_btn.pack(fill="x", pady=(4, 4))
    hotkey_hint = ctk.CTkLabel(
        hotkey_page,
        text="Click, then press a key combination.",
        **theme.label_style(muted=True),
    )
    hotkey_hint.pack(anchor="w")

    def toggle_hotkey() -> None:
        if recorder["r"] is not None:
            stop_recorder()
            hotkey_btn.configure(text=hotkey_var.get())
            hotkey_hint.configure(text="Click, then press a key combination.")
            return
        hotkey_btn.configure(text="Press any key…")
        hotkey_hint.configure(text="Waiting for a key. Click again to cancel.")
        hook = HotkeyRecorder()
        recorder["r"] = hook

        def captured(spec: str) -> None:
            def apply() -> None:
                stop_recorder()
                try:
                    parse_hotkey(spec)
                except ValueError:
                    hotkey_hint.configure(text="That shortcut is not valid. Try again.")
                    hotkey_btn.configure(text=hotkey_var.get())
                    return
                state["hotkey"] = spec
                hotkey_var.set(spec.upper())
                hotkey_btn.configure(text=spec.upper())
                hotkey_hint.configure(text="Click, then press a key combination.")

            app.after(0, apply)

        hook.start(captured)

    hotkey_btn.configure(command=toggle_hotkey)

    # --- page 2: LLM ---
    llm_page = ctk.CTkFrame(body, fg_color="transparent")
    pages["llm"] = llm_page
    ctk.CTkLabel(llm_page, text="Choose an AI model", font=theme.font(16, "bold"), **theme.label_style()).pack(
        anchor="w", pady=(8, 8)
    )
    ctk.CTkLabel(llm_page, text=rec.reason, wraplength=500, justify="left", **theme.label_style(muted=True)).pack(
        anchor="w", pady=(0, 12)
    )
    labels: list[str] = []
    values: dict[str, str] = {}
    for choice in rec.choices:
        suffix = ""
        if choice.name == rec.recommended:
            suffix = "  — recommended for your GPU"
        elif not choice.fits(rec.gpu.total_vram_mb):
            suffix = "  — needs more VRAM"
        label = f"{choice.name}{suffix}"
        labels.append(label)
        values[label] = choice.name
    recommended_label = next(label for label, name in values.items() if name == rec.recommended)
    llm_var = ctk.StringVar(value=recommended_label)
    llm_combo = ctk.CTkComboBox(llm_page, values=labels, variable=llm_var, **theme.combo())
    llm_combo.pack(fill="x")
    ctk.CTkLabel(
        llm_page,
        text="BOB will download the selected model with Ollama after this step.",
        wraplength=500,
        justify="left",
        **theme.label_style(muted=True),
    ).pack(anchor="w", pady=(10, 0))

    # --- page 3: startup ---
    start_page = ctk.CTkFrame(body, fg_color="transparent")
    pages["startup"] = start_page
    ctk.CTkLabel(
        start_page,
        text="Start BOB when Windows starts?",
        font=theme.font(16, "bold"),
        **theme.label_style(),
    ).pack(anchor="w", pady=(8, 8))
    start_var = ctk.BooleanVar(value=True)
    ctk.CTkCheckBox(
        start_page,
        text="Start BOB when Windows starts",
        variable=start_var,
        **theme.check(),
    ).pack(anchor="w")
    ctk.CTkLabel(
        start_page,
        text="You can change this later from the tray menu.",
        **theme.label_style(muted=True),
    ).pack(anchor="w", pady=(8, 0))

    # --- page 4: download ---
    down_page = ctk.CTkFrame(body, fg_color="transparent")
    pages["download"] = down_page
    ctk.CTkLabel(
        down_page,
        text="Downloading BOB components",
        font=theme.font(16, "bold"),
        **theme.label_style(),
    ).pack(anchor="w", pady=(8, 8))
    overall_label = ctk.CTkLabel(down_page, text="Overall", **theme.label_style(muted=True))
    overall_label.pack(anchor="w")
    overall_bar = ctk.CTkProgressBar(down_page, **theme.progress())
    overall_bar.set(0)
    overall_bar.pack(fill="x", pady=(0, 12))
    stage_label = ctk.CTkLabel(down_page, text="Starting…", **theme.label_style())
    stage_label.pack(anchor="w")
    stage_bar = ctk.CTkProgressBar(down_page, **theme.progress())
    stage_bar.set(0)
    stage_bar.pack(fill="x", pady=(0, 6))
    size_label = ctk.CTkLabel(down_page, text="", **theme.label_style(muted=True))
    size_label.pack(anchor="w")
    error_label = ctk.CTkLabel(down_page, text="", text_color="#f87171")
    error_label.pack(anchor="w", pady=(8, 0))
    retry_btn = ctk.CTkButton(down_page, text="Retry", **theme.button())

    # --- done ---
    done_page = ctk.CTkFrame(body, fg_color="transparent")
    pages["done"] = done_page
    done_copy = ctk.CTkLabel(done_page, text="", wraplength=500, justify="left", **theme.label_style())
    done_copy.pack(anchor="w", pady=(8, 12))
    launch_var = ctk.BooleanVar(value=True)
    ctk.CTkCheckBox(done_page, text="Launch BOB now", variable=launch_var, **theme.check()).pack(anchor="w")

    def set_progress(stage: int, total: int, name: str, completed: int | None, nbytes: int | None) -> None:
        stage_frac = 0.0 if not nbytes else min(1.0, (completed or 0) / max(nbytes, 1))
        overall = (stage + stage_frac) / max(total, 1)
        extra = ""
        if completed is not None and nbytes:
            extra = f"{format_bytes(completed)} / {format_bytes(nbytes)}"
        write_progress(
            phase="download",
            message=name,
            overall=overall,
            stage=stage_frac,
            completed=completed,
            total=nbytes,
        )

        def paint() -> None:
            overall_bar.set(overall)
            stage_bar.set(stage_frac if nbytes else (0.2 if completed is None else 1.0))
            overall_label.configure(text=f"Overall  {int(overall * 100)}%")
            stage_label.configure(text=name)
            size_label.configure(text=extra)

        app.after(0, paint)

    def start_download() -> None:
        error_label.configure(text="")
        retry_btn.pack_forget()
        show("download")
        subtitle.configure(text="This can take several minutes the first time.")

        def work() -> None:
            try:
                bootstrap_all(root, on_progress=set_progress)
            except Exception as exc:
                def fail() -> None:
                    error_label.configure(text=str(exc) or "Download failed.")
                    retry_btn.pack(anchor="w", pady=(8, 0))
                    back_btn.configure(state="normal")

                app.after(0, fail)
                return

            def ok() -> None:
                write_progress(phase="done", message="BOB is ready", overall=1.0, stage=1.0, done=True)
                done_copy.configure(
                    text=(
                        f"BOB is ready. Press {state['hotkey'].upper()} or say “hey jarvis”. "
                        "Ollama stays installed if you remove BOB later."
                    )
                )
                show("done")
                subtitle.configure(text="")
                header.configure(text="You're all set")

            app.after(0, ok)

        threading.Thread(target=work, name="bob-bootstrap", daemon=True).start()

    retry_btn.configure(command=start_download)

    def go_next() -> None:
        page = current["name"]
        if page == "hotkey":
            stop_recorder()
            try:
                parse_hotkey(state["hotkey"])
            except ValueError:
                hotkey_hint.configure(text="Choose a valid shortcut first.")
                return
            subtitle.configure(text="")
            header.configure(text="AI model")
            show("llm")
            return
        if page == "llm":
            state["llm_model"] = values.get(llm_var.get(), rec.recommended)
            header.configure(text="Startup")
            show("startup")
            return
        if page == "startup":
            state["start_with_windows"] = bool(start_var.get())
            apply_choices(
                root,
                hotkey=state["hotkey"],
                llm_model=state["llm_model"],
                start_with_windows=state["start_with_windows"],
            )
            start_download()
            return
        if page == "done":
            if launch_var.get():
                exe = branded_exe(root)
                target = str(exe if exe.is_file() else root / ".venv" / "Scripts" / "pythonw.exe")
                args = [] if exe.is_file() else ["-m", "bob"]
                subprocess.Popen(
                    [target, *args],
                    cwd=str(root),
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    close_fds=True,
                )
            app.destroy()

    def go_back() -> None:
        page = current["name"]
        if page == "llm":
            header.configure(text="Set up BOB")
            subtitle.configure(text="")
            show("hotkey")
        elif page == "startup":
            header.configure(text="AI model")
            show("llm")
        elif page == "download":
            header.configure(text="Startup")
            show("startup")

    back_btn = ctk.CTkButton(nav, text="Back", command=go_back, **theme.button("surface"))
    back_btn.pack(side="left")
    next_btn = ctk.CTkButton(nav, text="Next", command=go_next, **theme.button())
    next_btn.pack(side="right")

    subtitle.configure(text="Choose a shortcut to start and stop listening.")
    show("hotkey")
    back_btn.configure(state="disabled")
    app.protocol("WM_DELETE_WINDOW", lambda: (stop_recorder(), app.destroy()))
    app.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    from install_progress import InstallCancelled, write_progress

    try:
        return _main_impl(argv)
    except InstallCancelled:
        write_progress(phase="cancel", message="Installation cancelled.", cancelled=True, done=True)
        return 2
    except Exception as exc:
        from install_progress import INSTALL_STEPS

        write_progress(
            phase="error",
            message=str(exc),
            error=str(exc),
            done=True,
            step=INSTALL_STEPS,
            step_total=INSTALL_STEPS,
        )
        return 1


def _main_impl(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BOB first-run setup wizard")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--hotkey")
    parser.add_argument("--llm-model")
    parser.add_argument("--start-with-windows", choices=("true", "false"))
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else Path(os.environ.get("BOB_ROOT") or Path.cwd())
    start = None if args.start_with_windows is None else args.start_with_windows == "true"
    if args.quiet:
        return run_quiet(
            root,
            hotkey=args.hotkey,
            llm_model=args.llm_model,
            start_with_windows=start,
            skip_download=args.skip_download,
        )
    return run_ui(root)


if __name__ == "__main__":
    raise SystemExit(main())
