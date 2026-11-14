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


def _tail_lines(transcript_path) -> list:
    """The last 512 KiB of the transcript, as lines ([] when it cannot be read)."""
    if not transcript_path:
        return []
    try:
        with open(_long(transcript_path), "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 512 * 1024))
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


# Notes Claude Code adds to the conversation at a usage limit (user records with isMeta and
# "usageLimitNote": "wrap_up"), and when that limit no longer applies ("release"). It adds the
# release only with a prompt the user types. The texts are the fallback for records without the
# field.
LIMIT_NOTE = "[Usage limit reached"
LIMIT_CLEARED_NOTE = "[Earlier usage-limit notes no longer apply"


def limit_note_left(transcript_path, since: float) -> bool:
    """True when Claude Code told the model, at or after `since`, that the usage limit was reached,
    and has not taken it back since.

    The note asks the model to wind down and stop. After a switch it is about the old login, but
    Claude Code takes it back only with the next prompt the user types: a turn the switch notice
    starts still carries it, and the model stops."""
    for line in reversed(_tail_lines(transcript_path)):
        if '"usageLimitNote"' not in line and LIMIT_NOTE not in line and LIMIT_CLEARED_NOTE not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "user" or not e.get("isMeta"):
            continue  # e.g. "api-request-blob" records copy the whole conversation
        kind = e.get("usageLimitNote")
        if not kind:
            text = json.dumps((e.get("message") or {}).get("content") or "", ensure_ascii=False)
            kind = "release" if LIMIT_CLEARED_NOTE in text else "wrap_up" if LIMIT_NOTE in text else ""
        if kind == "release":
            return False  # the latest note was taken back
        if kind:
            return _epoch(e.get("timestamp")) >= since
    return False


def _epoch(stamp) -> float:
    """Epoch seconds of a transcript timestamp ("2026-11-14T22:34:44.123Z"), 0 when unreadable."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def stopped_at_limit(transcript_path) -> bool:
    """True when the conversation's last exchange is a usage-limit error (the session is waiting)."""
    for line in reversed(_tail_lines(transcript_path)):
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
