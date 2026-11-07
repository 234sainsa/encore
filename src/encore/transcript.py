"""Reading a session's transcript (the .jsonl file Claude Code writes): did it stop at the limit?
"""
from __future__ import annotations

import json
import os

from . import IS_WIN


def _is_local_record(e: dict) -> bool:
    """User records that a local command wrote (e.g. /usage, !cmd); the model was not called."""
    if e.get("isMeta"):
        return True
    content = (e.get("message") or {}).get("content")
    text = content if isinstance(content, str) else json.dumps(content or "")
    return any(tag in text for tag in ("<command-name>", "<local-command-stdout>", "<bash-input>",
                                       "<bash-stdout>", "<local-command-caveat>"))


def stopped_at_limit(transcript_path) -> bool:
    """True when the conversation's last exchange is a usage-limit error (the session is waiting)."""
    if not transcript_path:
        return False
    path = os.path.abspath(transcript_path)
    if IS_WIN and not path.startswith("\\\\?\\"):
        path = "\\\\?\\" + path  # transcripts can be deeper than 260 characters
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 512 * 1024))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return False
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") not in ("user", "assistant"):
            continue
        if e.get("type") == "user" and _is_local_record(e):
            continue
        return bool(e.get("isApiErrorMessage")) and e.get("error") == "rate_limit"
    return False
