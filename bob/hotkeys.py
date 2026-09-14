from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
PM_REMOVE = 0x0001
WH_KEYBOARD_LL = 13
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C

MODIFIER_VKS = {
    VK_SHIFT,
    VK_CONTROL,
    VK_MENU,
    VK_LWIN,
    VK_RWIN,
    0xA0,
    0xA1,
    0xA2,
    0xA3,
    0xA4,
    0xA5,
}

VK_NAMES = {
    0x08: "backspace",
    0x09: "tab",
    0x0C: "clear",
    0x0D: "enter",
    0x13: "pause",
    0x14: "capslock",
    0x1B: "esc",
    0x20: "space",
    0x21: "pageup",
    0x22: "pagedown",
    0x23: "end",
    0x24: "home",
    0x25: "left",
    0x26: "up",
    0x27: "right",
    0x28: "down",
    0x2C: "printscreen",
    0x2D: "insert",
    0x2E: "delete",
    0x5D: "app",
    0x90: "numlock",
    0x91: "scrolllock",
    0xBA: "semicolon",
    0xBB: "plus",
    0xBC: "comma",
    0xBD: "minus",
    0xBE: "period",
    0xBF: "slash",
    0xC0: "tilde",
    0xDB: "lbracket",
    0xDC: "backslash",
    0xDD: "rbracket",
    0xDE: "quote",
    0xAD: "mute",
    0xAE: "volumedown",
    0xAF: "volumeup",
    0xB0: "medianext",
    0xB1: "mediaprev",
    0xB2: "mediastop",
    0xB3: "mediaplay",
}
for i in range(10):
    VK_NAMES[0x30 + i] = str(i)
    VK_NAMES[0x60 + i] = f"num{i}"
for i in range(1, 25):
    VK_NAMES[0x70 + i - 1] = f"f{i}"
for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    VK_NAMES[0x41 + i] = ch
VK_NAMES[0x6A] = "nummul"
VK_NAMES[0x6B] = "numadd"
VK_NAMES[0x6D] = "numsub"
VK_NAMES[0x6E] = "numdec"
VK_NAMES[0x6F] = "numdiv"

VK_MAP = {name: vk for vk, name in VK_NAMES.items()}
VK_MAP.update(
    {
        "escape": 0x1B,
        "return": 0x0D,
        "control": VK_CONTROL,
        "ctrl": VK_CONTROL,
        "alt": VK_MENU,
        "win": VK_LWIN,
        "meta": VK_LWIN,
        "super": VK_LWIN,
        "capital": 0x14,
        "pgup": 0x21,
        "pgdn": 0x22,
        "ins": 0x2D,
        "del": 0x2E,
        "plus": 0xBB,
        "minus": 0xBD,
    }
)


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


def vk_to_token(vk: int) -> str:
    return VK_NAMES.get(int(vk), f"vk{int(vk)}")


def current_mods() -> int:
    mods = 0
    if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
        mods |= MOD_CONTROL
    if user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
        mods |= MOD_SHIFT
    if user32.GetAsyncKeyState(VK_MENU) & 0x8000:
        mods |= MOD_ALT
    if (user32.GetAsyncKeyState(VK_LWIN) | user32.GetAsyncKeyState(VK_RWIN)) & 0x8000:
        mods |= MOD_WIN
    return mods


def format_hotkey(mods: int, vk: int) -> str:
    parts: list[str] = []
    if mods & MOD_CONTROL:
        parts.append("ctrl")
    if mods & MOD_SHIFT:
        parts.append("shift")
    if mods & MOD_ALT:
        parts.append("alt")
    if mods & MOD_WIN:
        parts.append("win")
    parts.append(vk_to_token(vk))
    return "+".join(parts)


def parse_hotkey(spec: str) -> tuple[int, int]:
    mods = 0
    vk = None
    for part in spec.lower().replace(" ", "").split("+"):
        if part in {"ctrl", "control"}:
            mods |= MOD_CONTROL
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part == "alt":
            mods |= MOD_ALT
        elif part in {"win", "meta", "super"}:
            mods |= MOD_WIN
        elif part in VK_MAP:
            vk = VK_MAP[part]
        elif part.startswith("vk") and part[2:].isdigit():
            vk = int(part[2:])
        elif len(part) == 1:
            vk = ord(part.upper())
        else:
            raise ValueError(f"Unknown hotkey token: {part}")
    if vk is None:
        raise ValueError(f"Hotkey has no key: {spec}")
    return mods, vk


class HotkeyRecorder:
    """Capture the next non-modifier key (plus held modifiers) via a low-level hook."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._hook = None
        self._proc = None
        self._tid = 0
        self._on_spec: Callable[[str], None] | None = None
        self._fired = False

    def start(self, on_spec: Callable[[str], None]) -> None:
        self.stop()
        self._stop.clear()
        self._fired = False
        self._on_spec = on_spec
        self._thread = threading.Thread(target=self._run, name="hotkey-record", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        self._thread = None
        self._tid = 0

    def _run(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._tid = kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._callback)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, ctypes.cast(self._proc, ctypes.c_void_p), None, 0)
        if not self._hook:
            return
        msg = MSG()
        try:
            while not self._stop.is_set():
                got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if got == 0 or self._stop.is_set():
                    break
                if got == -1:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

    def _callback(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0 and w_param in {WM_KEYDOWN, WM_SYSKEYDOWN} and not self._fired:
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(info.vkCode)
            if vk not in MODIFIER_VKS:
                self._fired = True
                spec = format_hotkey(current_mods(), vk)
                on_spec = self._on_spec
                if on_spec:
                    try:
                        on_spec(spec)
                    except Exception:
                        pass
                self._stop.set()
                if self._tid:
                    user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
                return 1
        return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)


class GlobalHotkey:
    def __init__(self, spec: str, callback: Callable[[], None]) -> None:
        self.spec = spec
        self.callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self.error: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        try:
            mods, vk = parse_hotkey(self.spec)
        except ValueError as exc:
            self.error = str(exc)
            self._ready.set()
            return
        if not user32.RegisterHotKey(None, 1, mods, vk):
            self.error = f"Could not register {self.spec} (already in use?)"
            self._ready.set()
            return
        self._ready.set()
        msg = MSG()
        try:
            while not self._stop.is_set():
                got = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE)
                if got:
                    if msg.message == WM_HOTKEY:
                        try:
                            self.callback()
                        except Exception:
                            pass
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    self._stop.wait(0.03)
        finally:
            user32.UnregisterHotKey(None, 1)
