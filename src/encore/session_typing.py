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


def wait_for_box(pid: int, deadline: float, session: str = "", not_text=None, not_until: float = 0):
    """Wait until the input box of the main conversation is on screen (no dialog, no subagent
    shown) and the person is not in the middle of typing (the box did not change for a moment).
    Until `not_until`, a box that holds `not_text` does not count. Returns (lines, cursor), or None
    at the deadline."""
    last = None
    told = told_list = False
    while time.time() < deadline:
        try:
            lines, cursor = win_console.read_screen(pid)
        except OSError:
            return None
        box = screen.input_box(lines)
        if box and screen.in_agent_list(lines, cursor):
            # The person is picking a conversation: wait until they are back in the input box.
            if not told_list:
                files.log_event(f"on-switch session={session}: the agent list is in use; waiting")
                told_list = True
            box = None
        held = bool(box) and not_text is not None and box[2] == not_text and time.time() < not_until
        if box and (held or screen.viewing_agent(lines, cursor)):
            # Typed text would go to that subagent: wait until the person goes back to the main one.
            if not told:
                files.log_event(f"on-switch session={session}: a subagent is on screen; "
                                "waiting for the main conversation")
                told = True
            box = None
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


DRAFT_RECHECK_SEC = 30  # how often a draft typed to a subagent is put aside to look under it


def give_back_draft(pid: int, draft: str, session: str) -> None:
    """Undo stash_draft: Ctrl+S on the empty box brings the stashed text back (not seen on a real
    screen yet, hence the log line either way)."""
    win_console.press_key(pid, "\x13", 0x53, ctrl=True)
    time.sleep(1.2)
    try:
        box = screen.input_box(win_console.read_screen(pid)[0])
    except OSError:
        box = None
    back = bool(box) and box[2] == draft
    files.log_event(f"on-switch session={session}: the typed text was for a subagent; "
                    + ("gave it back" if back else "it stays put aside (Claude Code brings it back after the next message)"))


def type_one(pid: int, text: str, deadline: float, session: str, cancel_wait: bool = False) -> bool:
    """Type `text` + Enter into the main conversation of the session, keeping whatever the person
    had typed. `cancel_wait`: press Esc first when the session waits for the old login's limit."""
    agent_draft, recheck_at = None, 0.0  # a draft that turned out to be typed to a subagent
    while True:
        view = wait_for_box(pid, deadline, session, not_text=agent_draft, not_until=recheck_at)
        if view is None:
            files.log_event(f"on-switch session={session}: gave up before typing {text!r} "
                            "(a dialog or a subagent stayed on screen)")
            return False
        draft = None if screen.box_empty(*view) else screen.input_box(view[0])[2]
        if not stash_draft(pid, *view):
            files.log_event(f"on-switch session={session}: gave up before typing {text!r} "
                            "(could not put the typed text aside)")
            return False
        try:
            lines, cursor = win_console.read_screen(pid)
        except OSError:
            return False
        if not screen.viewing_agent(lines, cursor):
            break
        # The draft hid the subagent's hint: it was typed to that subagent. Give it back, and wait
        # for the main conversation. The same draft is looked under again only now and then: the
        # main conversation may show it too, and each look puts it aside for a moment.
        if draft:
            give_back_draft(pid, draft, session)
            agent_draft, recheck_at = draft, time.time() + DRAFT_RECHECK_SEC
    if cancel_wait and screen.waiting_for_reset(lines):
        cancel_limit_wait(pid, session)
    win_console.type_line(pid, text)
    files.log_event(f"on-switch session={session}: typed {text!r}"
                    + (" (queued: Claude was working)" if screen.is_busy(view[0]) else ""))
    return True


REMOTE_CONTROL_NOTICE_SEC = 90  # how long the dialog may wait for Remote Control to notice the switch


def remote_control_asked_retry(pid: int, deadline: float, session: str = "") -> bool:
    """After /remote-control: True when its "try again" dialog came up (and was answered).

    A command typed while Claude works runs when the turn ends, so watch until the session has
    been idle for a few seconds. While the dialog shows the connected state, keep watching: it
    turns into the "try again" one when Remote Control notices the account change."""
    idle_since = None
    dialog_until = None
    while time.time() < deadline:
        time.sleep(1.0)
        try:
            lines = win_console.read_screen(pid)[0]
        except OSError:
            return False
        if screen.remote_control_says_retry(lines):
            win_console.type_line(pid, "")  # "Continue" is selected
            return True
        if screen.remote_control_dialog_open(lines):
            idle_since = None
            dialog_until = dialog_until or time.time() + REMOTE_CONTROL_NOTICE_SEC
            if time.time() > dialog_until:
                # Remote Control still holds its connection: close the dialog (Esc = Continue),
                # which leaves the connection as it is.
                win_console.press_key(pid, "\x1b", 0x1B)
                files.log_event(f"on-switch session={session}: Remote Control stayed connected; "
                                "closed its dialog")
                return False
            continue
        if screen.is_busy(lines):
            idle_since = None
        elif idle_since is None:
            idle_since = time.time()
        elif time.time() - idle_since > 4:
            return False
    return False
