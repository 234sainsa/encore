"""What a running session gets after a switch: what is typed into it (Windows), and what the
model is told.
"""
from __future__ import annotations

import time

from . import IS_WIN, background, files, on_switch, switch_signal, transcript, usage


def respond(data: dict, sig: dict):
    """Handle switch `sig` for the session of hook input `data`.

    Returns the notice for the model (the hook sends it with exit code 2, asyncRewake), or None
    when the session needs no notice."""
    if IS_WIN:
        stopped = False
        try:
            stopped = type_after_switch(data, sig)
        except Exception as e:  # never fail the hook
            files.log_event(f"on-switch error: {type(e).__name__}: {e}")
        if stopped:
            return None  # the continue text already asked about stopped subagents
        return notice_after_typing(sig)  # the model hears about its agents
    return notice(sig)


def notice_after_typing(sig: dict) -> str:
    """Windows, for a session that was not stopped at the limit: /remote-control was typed in, but
    the model still has to hear about its agents."""
    return (
        f"encore (a hook the user installed): the login switched from '{sig.get('from')}' to "
        f"'{sig.get('to')}' at {usage.fmt_time(sig.get('at'))}; /remote-control was typed in. Subagents and background "
        "agents that were running during the switch may have stopped. The user set up this hook so that each of "
        "them is checked, one by one, and every one that stopped is started again.")


def notice(sig: dict) -> str:
    # Written as a notice, not as orders: models rightly ignore orders that show up in tool output.
    return (
        f"encore (a hook the user installed): the login switched from '{sig.get('from')}' to "
        f"'{sig.get('to')}' at {usage.fmt_time(sig.get('at'))}. Remote Control has likely disconnected; only the user "
        "can reconnect it (/remote-control). Subagents and background agents that were running during the "
        "switch may have stopped. The user set up this hook to hear about Remote Control, and so that each "
        "agent is checked, one by one, and every one that stopped is started again.")


def type_after_switch(data: dict, sig: dict) -> bool:
    """Windows, from the FileChanged hook: type the on-switch commands into this session, and the
    continue text when it had stopped at the limit.

    Returns True when the session had stopped at the limit (it got the continue text, which also
    asks about stopped subagents)."""
    from . import win_console  # Windows only (ctypes)

    session = str(data.get("session_id") or "?")[:8]
    pid = win_console.find_claude_pid()
    if not pid:
        files.log_event(f"on-switch session={session}: claude.exe not found among the parent processes")
        return False
    return type_into(pid, sig, session, data.get("transcript_path"))


def type_into_all() -> None:
    """Windows, `encore after-switch`, started in the background by every switch: start one
    `after-switch --pid` for each session that was running before the switch.

    Sessions that started after the switch already use the new login, and /remote-control would
    only open its Disconnect menu there. One process per session, because a process can borrow
    only one console at a time, and each may wait minutes for its session to become idle."""
    from . import win_console  # Windows only (ctypes)

    sig = _current_switch()
    if sig is None:
        return
    pids = [pid for pid in win_console.session_pids() if (win_console.started_at(pid) or 0) < sig["at"]]
    files.log_event(f"after switch {sig['seq']}: sessions running since before it: {pids or 'none'}")
    for pid in pids:
        background.start(f"after-switch --pid {pid}")


def type_into_one(pid: int) -> None:
    """Windows, `encore after-switch --pid <pid>`: type into that one session."""
    sig = _current_switch()
    if sig is None:
        return
    try:
        type_into(pid, sig, f"pid{pid}")
    except Exception as e:  # nobody sees a traceback of a background process
        files.log_event(f"on-switch pid{pid} error: {type(e).__name__}: {e}")


def _current_switch():
    """The last switch from switched.json, or None when there is none to act on."""
    try:
        sig = switch_signal.read()
    except ValueError:
        return None
    if not sig or not sig.get("seq") or sig.get("probe"):
        return None
    return sig


def type_into(pid: int, sig: dict, session: str, transcript_path=None) -> bool:
    """Type the on-switch commands into the session in the console of `pid`, and the continue text
    when it had stopped at the limit. Once per session and switch: both the FileChanged hook and
    `after-switch` may get here for the same session.

    Returns True when the session had stopped at the limit."""
    from . import session_typing  # Windows only (ctypes)

    cfg = on_switch.config()
    commands = list(cfg.get("commands") or [])
    resume = cfg.get("continue_text") or ""
    if not commands and not resume:
        return False
    if not switch_signal.first_notice(f"pid{pid}", sig["seq"]):
        return False  # already typed into for this switch
    deadline = time.time() + float(cfg.get("wait_sec") or 600)
    # A session stopped at the old login's limit waits for that limit to reset. Cancel the wait
    # (Esc) and send the continue text, so it goes on with the new login now.
    stopped = False
    if resume:
        stopped = session_typing.limit_wait_on_screen(pid)
        if stopped:
            # Cancel the wait first: while it lasts, typed commands would only be queued.
            session_typing.cancel_limit_wait(pid, session)
        stopped = stopped or transcript.stopped_at_limit(transcript_path)
    todo = commands + ([resume] if stopped else [])
    for i, text in enumerate(todo):
        for attempt in range(3):
            if not session_typing.type_one(pid, text, deadline, session, cancel_wait=(i == len(commands))):
                return stopped
            if not text.strip().startswith("/remote-control"):
                time.sleep(2.0)
                break
            if not session_typing.remote_control_asked_retry(pid, deadline):
                break
            # Remote Control still held the old account's connection. The dialog says: choose
            # Continue (done), wait about 10 seconds, then run /remote-control again.
            files.log_event(f"on-switch session={session}: Remote Control asked to retry; waiting")
            time.sleep(12.0)
    return stopped
