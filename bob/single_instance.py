from __future__ import annotations

import ctypes
import sys

MUTEX_NAME = "Local\\BobVoiceAssistant.SingleInstance"
ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """Hold a named Windows mutex for the life of the process.

    A second `python -m bob` would otherwise grab the microphone and fail to
    register the hotkey while the first keeps running.
    """

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self._handle = None
        self.already_running = False
        if sys.platform != "win32":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        self._kernel32 = kernel32
        self._handle = kernel32.CreateMutexW(None, 1, name)
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle and sys.platform == "win32":
            try:
                self._kernel32.ReleaseMutex(ctypes.c_void_p(self._handle))
                self._kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            except Exception:
                pass
            self._handle = None
