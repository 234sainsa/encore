"""File helpers: JSON read whole and written atomically, backups, and the event log.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import IS_WIN, paths

KEEP_BACKUPS = 20


def read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path: Path, data, private: bool = False) -> None:
    """Write atomically (temp file + rename). private=True means mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if not IS_WIN:
            mode = 0o600
            if not private and path.exists():
                mode = stat.S_IMODE(path.stat().st_mode)
            os.chmod(tmp, mode)
        for attempt in range(30):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                # Windows: another process (Claude Code) may have the file open.
                if attempt == 29:
                    raise
                time.sleep(0.1)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def backup(label: str, data) -> None:
    """Keep a copy of a file encore is about to replace (the newest KEEP_BACKUPS stay)."""
    if data is None:
        return
    d = paths.home() / "backups"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    write_json(d / f"{stamp}-{label}.json", data, private=True)
    files = sorted(d.glob("*.json"))
    for old in files[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)


def log_event(text: str) -> None:
    paths.home().mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} {text}\n"
    with open(paths.home() / "events.log", "a", encoding="utf-8") as f:
        f.write(line)
