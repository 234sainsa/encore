"""Reading Claude Code's screen: the visible console lines of a session, as text.

Pure functions, so they work (and are tested) on every system; only reading the lines off a real
console needs Windows (win_console).
"""
from __future__ import annotations

import re


def input_box(lines: list):
    """(row, column where the text starts, text) of Claude Code's input box.

    None when no input box is on screen: a dialog or a menu is open. The input box is the ❯ line
    right under a horizontal rule; menus mark their choice with ❯ too, but not under a rule."""
    rows = [i for i, x in enumerate(lines) if x.strip()][-16:]
    if any("Enter to select" in lines[i] or "Enter to confirm" in lines[i] for i in rows):
        return None
    for k in range(len(rows) - 1, 0, -1):
        line = lines[rows[k]]
        # (The rule is matched loosely: a half-redrawn screen can leave other text on its line.)
        if line.lstrip().startswith("❯") and "─" * 20 in lines[rows[k - 1]]:
            start = line.index("❯") + 2
            return rows[k], start, line[start - 1:].strip()
    return None


_SPINNER = re.compile(r"…\s*\(\d+s")  # "✻ Stewing… (12s · ↓ 24 tokens)"


def is_busy(lines: list) -> bool:
    """True while Claude works, or while typed messages wait in the queue."""
    bottom = [x for x in lines if x.strip()][-16:]
    return any("esc to interrupt" in x or "to send now" in x or _SPINNER.search(x) for x in bottom)


def box_empty(lines: list, cursor=None) -> bool:
    """True when the input box holds no typed text.

    The box can show example text or a suggested next prompt. The screen gives those the same
    look as typed text, but the cursor stays at the start of the box for them (tested)."""
    box = input_box(lines)
    if box is None:
        return False
    row, start, text = box
    return not text or (cursor is not None and tuple(cursor) == (start, row))


def prompt_ready(lines: list, cursor=None) -> bool:
    """True when the session waits for input and nobody is typing in the input box."""
    return not is_busy(lines) and box_empty(lines, cursor)


def waiting_for_reset(lines: list) -> bool:
    """Claude Code waits for the old login's limit to reset, even after a switch. It shows
    "Continuing automatically at <time> · Esc to cancel", or (newer, the turn stays open)
    "Weekly limit … · Retrying in 5h (Nov 7, 6am) · attempt 1/15"."""
    for x in lines[-14:]:
        low = x.lower()
        if "continuing automatically" in low or ("retrying in" in low and "attempt" in low):
            return True
    return False


def remote_control_says_retry(lines: list) -> bool:
    """Right after a switch, /remote-control opens "Remote Control isn't connected ... To try again,
    choose Continue, wait about 10 seconds ..., then run /remote-control." (Continue is selected)."""
    text = " ".join(lines[-20:])
    return "try again, choose Continue" in text and "Remote Control" in text
