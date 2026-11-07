"""switched.json: how running sessions hear that the login changed.

Every session watches the file (the SessionStart hook gives them its path) and runs the
FileChanged hook when it changes. seen/ remembers which session already heard about which switch.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from . import files, paths


def path() -> Path:
    return paths.home() / "switched.json"


def ensure_exists() -> None:
    """Sessions watch switched.json from their start. A session that started while the file did
    not exist yet never hears about it (tested on 2026-11-05), so it must exist before that."""
    if not path().exists():
        files.write_json(path(), {"seq": 0})


def announce(before, after: str, why: str) -> None:
    """Tell running sessions (through the FileChanged hook) that the login changed."""
    old = files.read_json(path(), {}) or {}
    files.write_json(path(), {
        "seq": int(old.get("seq") or 0) + 1,
        "at": int(time.time()),
        "from": before,
        "to": after,
        "why": why,
    })


def read():
    """The last switch, or None. Raises ValueError when the file is caught in the middle of a write."""
    return files.read_json(path())


def first_notice(session_id, seq) -> bool:
    """True the first time this session asks about switch number `seq`.

    One switch can cause several file events: tell each session once per switch."""
    seen = paths.home() / "seen"
    seen.mkdir(parents=True, exist_ok=True)
    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(session_id or "unknown"))
    try:
        os.close(os.open(seen / f"{session}-{seq}", os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    for old in seen.iterdir():
        try:
            if time.time() - old.stat().st_mtime > 7 * 86400:
                old.unlink()
        except OSError:
            pass
    return True
