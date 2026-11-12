"""Reading a session's transcript (the .jsonl file Claude Code writes): did it, or one of its
subagents, stop at the limit?
"""
from __future__ import annotations

import json
import os

from . import IS_WIN, paths


def _is_local_record(e: dict) -> bool:
    """User records that a local command wrote (e.g. /usage, !cmd); the model was not called."""
    if e.get("isMeta"):
        return True
    content = (e.get("message") or {}).get("content")
    text = content if isinstance(content, str) else json.dumps(content or "")
    return any(tag in text for tag in ("<command-name>", "<local-command-stdout>", "<bash-input>",
                                       "<bash-stdout>", "<local-command-caveat>"))


def _long(path: str) -> str:
    path = os.path.abspath(path)
    if IS_WIN and not path.startswith("\\\\?\\"):
        path = "\\\\?\\" + path  # transcripts can be deeper than 260 characters
    return path


def of_pid(pid: int):
    """The transcript of the Claude Code session in process `pid`, or None.

    Claude Code keeps <config>/sessions/<pid>.json with the session id; the transcript is
    <config>/projects/<folder>/<session id>.jsonl."""
    try:
        with open(paths.claude_dir() / "sessions" / f"{pid}.json", encoding="utf-8") as f:
            sid = str(json.load(f).get("sessionId") or "")
    except (OSError, ValueError, AttributeError):
        return None
    if not sid or any(c in sid for c in "/\\*?["):
        return None
    for p in (paths.claude_dir() / "projects").glob(f"*/{sid}.jsonl"):
        return str(p)
    return None


def agent_stopped_at_limit(transcript_path, since: float) -> bool:
    """True when a subagent of that session, written to at or after `since`, stopped at the usage
    limit. Subagents write <transcript without .jsonl>/subagents/*.jsonl."""
    if not transcript_path:
        return False
    folder = _long(os.path.join(os.path.splitext(transcript_path)[0], "subagents"))
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return False
    for e in entries:
        try:
            if e.name.endswith(".jsonl") and e.stat().st_mtime >= since and stopped_at_limit(e.path):
                return True
        except OSError:
            continue
    return False


def stopped_at_limit(transcript_path) -> bool:
    """True when the conversation's last exchange is a usage-limit error (the session is waiting)."""
    if not transcript_path:
        return False
    path = _long(transcript_path)
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
