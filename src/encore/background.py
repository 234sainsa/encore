"""Run a encore command in the background, detached from whatever started it.
"""
from __future__ import annotations

import subprocess

from . import IS_WIN, paths


def start(args: str) -> None:
    """Run `encore <args>` in the background, with no window, and do not wait for it."""
    cmd = f"{paths.self_command()} {args}"
    kw = dict(shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not IS_WIN:
        subprocess.Popen(cmd, start_new_session=True, **kw)
        return
    no_window, new_group, breakaway = 0x08000000, 0x00000200, 0x01000000
    try:
        # Out of Claude Code's job, so it keeps running after the hook or status line command ends.
        subprocess.Popen(cmd, creationflags=no_window | new_group | breakaway, **kw)
    except OSError:
        subprocess.Popen(cmd, creationflags=no_window | new_group, **kw)
