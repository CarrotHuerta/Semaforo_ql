"""Per-user installer mutexes. Portable instances use their data-directory Qt lock."""
import os
from app_paths import is_portable

_handles = []


def register_process(component):
    if os.name == "nt" and not is_portable():
        import ctypes
        from ctypes import wintypes
        create = ctypes.windll.kernel32.CreateMutexW
        create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        create.restype = wintypes.HANDLE
        handle = create(None, False, "Local\\SemaforoIA." + component)
        if not handle:
            raise ctypes.WinError()
        _handles.append(handle)
