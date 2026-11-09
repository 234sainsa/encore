"""The hooks encore installs in Claude Code: read the event from stdin, act, and answer on
stdout, stderr and the exit code.
"""
from __future__ import annotations

import json
import sys

from . import Error, after_switch, auto_switch, claude_settings, files, profiles, switch_signal
from .lock import Lock


def stop_failure() -> int:
    """StopFailure (matcher rate_limit): the turn ended at the usage limit."""
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    if data.get("error") != "rate_limit":
        return 0
    files.log_event("usage limit reached (StopFailure hook)")
    try:
        auto_switch.switch_if_at_limit(limit_hit=True)
    except Error as e:
        files.log_event(f"automatic switch failed: {e}")
    return 0


def session_start() -> int:
    """SessionStart: give the new session switched.json to watch."""
    raw = sys.stdin.read()
    try:
        session = str((json.loads(raw) if raw.strip() else {}).get("session_id") or "?")[:8]
        existed = switch_signal.path().exists()
        switch_signal.ensure_exists()
        files.log_event(f"session start: session={session} watches {switch_signal.path().name}"
                        + ("" if existed else " (created it)"))
    except Exception:
        pass
    try:
        with Lock(timeout=2.0):
            profiles.sync_back()  # e.g. after `claude auth login` outside a session
        claude_settings.drop_old_api_key_helper()
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "watchPaths": [str(switch_signal.path())]}}))
    return 0


def switched() -> int:
    """FileChanged hook for switched.json (async).

    Windows: types the configured commands into this session (default /remote-control), and
    "continue" when it had stopped at a usage limit, unless `after-switch` did it already (Claude
    Code does not always run this hook, so every switch also starts `after-switch`). Elsewhere:
    exit code 2 (asyncRewake) tells the model, which then tells the user."""
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    files.log_event(f"switch hook ran: session={str(data.get('session_id') or '?')[:8]} event={data.get('event')}")
    if data.get("event") == "unlink":
        return 0
    try:
        sig = switch_signal.read()
    except ValueError:
        return 0  # caught in the middle of a write; the next file event reads it whole
    if not sig or not sig.get("seq"):
        return 0
    if sig.get("probe"):
        return 0  # a test of the file watch only (logged above); nothing is typed
    if not switch_signal.first_notice(data.get("session_id"), sig["seq"]):
        return 0
    text = after_switch.respond(data, sig)
    if text is None:
        return 0
    sys.stderr.write(text + "\n")
    return 2
