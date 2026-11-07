"""Typing one line into a running session without getting in the person's way: wait for the input
box, put their draft aside, cancel the wait for the old limit, answer Remote Control's retry dialog.

Windows only (it uses win_console). Import it on Windows code paths only.
"""
from __future__ import annotations

import time

from . import files, screen, win_console


def limit_wait_on_screen(pid: int) -> bool:
    """True when the session shows that it waits for the old login's limit to reset."""
    try:
        return screen.waiting_for_reset(win_console.read_screen(pid)[0])
    except OSError:
        return False


def cancel_limit_wait(pid: int, session: str) -> None:
    win_console.press_key(pid, "\x1b", 0x1B)
    files.log_event(f"on-switch session={session}: pressed Esc (cancel the wait for the old limit)")
    time.sleep(1.5)


def wait_for_box(pid: int, deadline: float):
    """Wait until the input box is on screen (no dialog) and the person is not in the middle of
    typing (the box did not change for a moment). Returns (lines, cursor), or None at the deadline."""
    last = None
    while time.time() < deadline:
        try:
            lines, cursor = win_console.read_screen(pid)
        except OSError:
            return None
        box = screen.input_box(lines)
        now = (box, tuple(cursor)) if box else None
        if now and now == last:
            return lines, cursor
        last = now
        time.sleep(1.5)
    return None


def stash_draft(pid: int, lines: list, cursor) -> bool:
    """Put what the person has typed aside (Ctrl+S, "stash"). Claude Code puts it back by itself
    after the next thing is sent, also when that is queued while Claude works (tested).
    Ctrl+S on an empty box does nothing (tested)."""
    row, start, text = screen.input_box(lines)
    if not text:
        return True
    win_console.press_key(pid, "\x13", 0x53, ctrl=True)
    time.sleep(1.2)
    try:
        lines2, cursor2 = win_console.read_screen(pid)
    except OSError:
        return False
    box = screen.input_box(lines2)
    if box is None:
        return False
    if box[2] != text:
        return True  # stashed
    # Unchanged: fine only if it was example text (the cursor sits at the start for that).
    return tuple(cursor2) == (box[1], box[0])


def type_one(pid: int, text: str, deadline: float, session: str, cancel_wait: bool = False) -> bool:
    """Type `text` + Enter into the session, keeping whatever the person had typed."""
    view = wait_for_box(pid, deadline)
    if view is None:
        files.log_event(f"on-switch session={session}: gave up before typing {text!r} (a dialog stayed open)")
        return False
    if not stash_draft(pid, *view):
        files.log_event(f"on-switch session={session}: gave up before typing {text!r} "
                        "(could not put the typed text aside)")
        return False
    if cancel_wait and screen.waiting_for_reset(win_console.read_screen(pid)[0]):
        cancel_limit_wait(pid, session)
    win_console.type_line(pid, text)
    files.log_event(f"on-switch session={session}: typed {text!r}"
                    + (" (queued: Claude was working)" if screen.is_busy(view[0]) else ""))
    return True


def remote_control_asked_retry(pid: int, deadline: float) -> bool:
    """After /remote-control: True when its "try again" dialog came up (and was answered).

    A command typed while Claude works runs when the turn ends, so watch until the session has
    been idle for a few seconds."""
    idle_since = None
    while time.time() < deadline:
        time.sleep(1.0)
        try:
            lines = win_console.read_screen(pid)[0]
        except OSError:
            return False
        if screen.remote_control_says_retry(lines):
            win_console.type_line(pid, "")  # "Continue" is selected
            return True
        if screen.is_busy(lines):
            idle_since = None
        elif idle_since is None:
            idle_since = time.time()
        elif time.time() - idle_since > 4:
            return False
    return False
