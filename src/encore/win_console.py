"""The Windows console of a running Claude Code session: find it, read its screen, press keys in it.

Windows only (ctypes, kernel32). Import it on Windows code paths only.
"""
from __future__ import annotations

import os
import time

if os.name != "nt":
    raise ImportError("encore.win_console works on Windows only")

import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE


class _COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class _SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", wintypes.SHORT), ("Top", wintypes.SHORT),
                ("Right", wintypes.SHORT), ("Bottom", wintypes.SHORT)]


class _CSBI(ctypes.Structure):
    _fields_ = [("dwSize", _COORD), ("dwCursorPosition", _COORD), ("wAttributes", wintypes.WORD),
                ("srWindow", _SMALL_RECT), ("dwMaximumWindowSize", _COORD)]


class _KEY_EVENT(ctypes.Structure):
    _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD),
                ("wVirtualKeyCode", wintypes.WORD), ("wVirtualScanCode", wintypes.WORD),
                ("UnicodeChar", wintypes.WCHAR), ("dwControlKeyState", wintypes.DWORD)]


class _EVENT(ctypes.Union):
    _fields_ = [("KeyEvent", _KEY_EVENT), ("_pad", ctypes.c_byte * 16)]


class _INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", wintypes.WORD), ("Event", _EVENT)]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


_k32.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_CSBI)]
_k32.ReadConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, _COORD,
                                             ctypes.POINTER(wintypes.DWORD)]
_k32.WriteConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_INPUT_RECORD), wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD)]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]


_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4


def _process_table() -> dict:
    """{pid: (parent pid, exe name in lower case)} of every running process."""
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)
    table = {}
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile.lower())
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    return table


def _claude_ancestor(table: dict, pid: int):
    """The nearest claude.exe among the parent processes of `pid` (not `pid` itself), or None."""
    for _ in range(30):
        parent, _name = table.get(pid, (0, ""))
        if not parent or parent == pid:
            return None
        if table.get(parent, (0, ""))[1] == "claude.exe":
            return parent
        pid = parent
    return None


def find_claude_pid():
    """The claude.exe that runs this hook: the nearest claude.exe among our parent processes."""
    return _claude_ancestor(_process_table(), os.getpid())


def session_pids() -> list:
    """The claude.exe processes that are Claude Code sessions in a console window.

    A claude.exe started by another claude.exe (a command a session runs) shares that session's
    console, and processes without a console (the desktop app) cannot be typed into: both are left out."""
    table = _process_table()
    found = [pid for pid, (_parent, name) in table.items()
             if name == "claude.exe" and _claude_ancestor(table, pid) is None]
    return sorted(pid for pid in found if has_console(pid))


def has_console(pid: int) -> bool:
    try:
        with _AttachedConsole(pid):
            return True
    except OSError:
        return False


def started_at(pid: int):
    """When process `pid` started (Unix time), or None when that cannot be read."""
    h = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _k32.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
            return None
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime  # 100 ns since 1601
        return ticks / 1e7 - 11644473600
    finally:
        _k32.CloseHandle(h)


class _AttachedConsole:
    """Borrow another process's console for a moment (AttachConsole)."""

    def __init__(self, pid: int):
        self.pid = pid

    def __enter__(self):
        _k32.FreeConsole()
        if not _k32.AttachConsole(self.pid):
            raise OSError(f"could not attach to the console of process {self.pid}")
        return self

    def __exit__(self, *exc):
        _k32.FreeConsole()


def read_screen(pid: int):
    """(visible lines, cursor as (x, index into the lines)) of the console that `pid` runs in."""
    with _AttachedConsole(pid):
        h = _k32.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)
        try:
            info = _CSBI()
            _k32.GetConsoleScreenBufferInfo(h, ctypes.byref(info))
            width = info.dwSize.X
            lines = []
            for y in range(info.srWindow.Top, info.srWindow.Bottom + 1):
                buf = ctypes.create_unicode_buffer(width + 1)
                n = wintypes.DWORD()
                _k32.ReadConsoleOutputCharacterW(h, buf, width, _COORD(0, y), ctypes.byref(n))
                lines.append(buf.value[:n.value].rstrip())
            cursor = (info.dwCursorPosition.X, info.dwCursorPosition.Y - info.srWindow.Top)
            return lines, cursor
        finally:
            _k32.CloseHandle(h)


def _key_records(ch: str, vk: int = 0) -> list:
    recs = []
    for down in (True, False):
        r = _INPUT_RECORD()
        r.EventType = 1  # KEY_EVENT
        k = r.Event.KeyEvent
        k.bKeyDown = down
        k.wRepeatCount = 1
        k.wVirtualKeyCode = vk
        k.UnicodeChar = ch
        recs.append(r)
    return recs


def type_line(pid: int, text: str) -> None:
    """Type `text` and Enter into the console of `pid`, as a person would.

    Enter goes separately after a short gap: Claude Code treats keys that arrive in one burst as a
    paste and would keep the Enter as a new line instead of sending."""
    with _AttachedConsole(pid):
        h = _k32.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
        try:
            for part in (text, "\r"):
                recs = []
                for ch in part:
                    recs += _key_records(ch, 0x0D if ch == "\r" else 0)
                arr = (_INPUT_RECORD * len(recs))(*recs)
                written = wintypes.DWORD()
                if not _k32.WriteConsoleInputW(h, arr, len(recs), ctypes.byref(written)):
                    raise OSError("could not type into the console")
                if part != "\r":
                    time.sleep(0.8)
        finally:
            _k32.CloseHandle(h)


def press_key(pid: int, ch: str, vk: int, ctrl: bool = False) -> None:
    """Press one key in the console of `pid` (Esc, Ctrl+S, ...)."""
    with _AttachedConsole(pid):
        h = _k32.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
        try:
            recs = _key_records(ch, vk)
            if ctrl:
                for r in recs:
                    r.Event.KeyEvent.dwControlKeyState = 0x0008  # LEFT_CTRL_PRESSED
            arr = (_INPUT_RECORD * len(recs))(*recs)
            _k32.WriteConsoleInputW(h, arr, len(recs), ctypes.byref(wintypes.DWORD()))
        finally:
            _k32.CloseHandle(h)
