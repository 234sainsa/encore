"""The lock file (~/.encore/.lock), so that two encore processes never switch at once.
"""
from __future__ import annotations

import os
import time

from . import Error, paths


class Lock:
    """A lock file so that two encore processes never switch at once."""

    def __init__(self, timeout: float = 10.0):
        self.path = paths.home() / ".lock"
        self.timeout = timeout

    def __enter__(self):
        paths.home().mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 30:
                        self.path.unlink()  # left behind by a crashed process
                        continue
                except FileNotFoundError:
                    continue
                if time.time() > deadline:
                    raise Error(f"another encore is busy (lock file: {self.path})")
                time.sleep(0.05)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)
