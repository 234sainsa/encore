"""What a running session gets after a switch: what is typed into it (Windows), and what the
model is told.
"""
from __future__ import annotations

import os
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
        f"'{sig.get('to')}' at {usage.fmt_time(sig.get('at'))}; /remote-control was typed in. {_old_limit_note(sig)}"
        "Subagents and background "
        "agents that were running during the switch may have stopped at the usage limit. The user set up this "
        "hook so that each of them is checked, one by one, and every one that stopped goes on from where it "
        "stopped, with the work it had done (a message to it resumes it), rather than being started over.")


def notice(sig: dict) -> str:
    # Written as a notice, not as orders: models rightly ignore orders that show up in tool output.
    return (
        f"encore (a hook the user installed): the login switched from '{sig.get('from')}' to "
        f"'{sig.get('to')}' at {usage.fmt_time(sig.get('at'))}. {_old_limit_note(sig)}"
        "Remote Control has likely disconnected; only the user "
        "can reconnect it (/remote-control). Subagents and background agents that were running during the "
        "switch may have stopped at the usage limit. The user set up this hook to hear about Remote Control, "
        "and so that each agent is checked, one by one, and every one that stopped goes on from where it "
        "stopped, with the work it had done (a message to it resumes it), rather than being started over.")


def _old_limit_note(sig: dict) -> str:
    """A "usage limit reached" note that Claude Code adds to the same turn was written for the old
    login; the model would otherwise wind down and stop."""
    return (f"If a note in this turn says the usage limit was reached, it was about '{sig.get('from')}', the "
            "login from before the switch, and does not apply now. ")


def type_after_switch(data: dict, sig: dict) -> bool:
    """Windows, from the FileChanged hook: type the on-switch commands into this session, and the
    continue text when it had stopped at the limit.

    Returns True when the session, or one of its subagents, had stopped at the limit (it got the
    continue text, which also asks about stopped subagents)."""
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
    when it, or one of its subagents, had stopped at the limit. Once per session and switch: both
    the FileChanged hook and `after-switch` may get here for the same session.

    Returns True when the continue text was due (it also asks about stopped subagents)."""
    from . import session_typing  # Windows only (ctypes)

    cfg = on_switch.config()
    commands = list(cfg.get("commands") or [])
    resume = cfg.get("continue_text") or ""
    if not commands and not resume:
        return False
    if not switch_signal.first_notice(f"pid{pid}", sig["seq"]):
        return False  # already typed into for this switch
    deadline = time.time() + float(cfg.get("wait_sec") or 600)
    path = transcript_path or transcript.of_pid(pid)  # `after-switch` knows only the pid
    # A session stopped at the old login's limit waits for that limit to reset. Cancel the wait
    # (Esc) and send the continue text, so it goes on with the new login now.
    stopped = False
    if resume:
        stopped = session_typing.limit_wait_on_screen(pid)
        if stopped:
            # Cancel the wait first: while it lasts, typed commands would only be queued.
            session_typing.cancel_limit_wait(pid, session)
        stopped = stopped or transcript.stopped_at_limit(path)
    for text in commands:
        if not _type_command(pid, text, deadline, session):
            return stopped
    if not resume:
        return False
    if not stopped:
        since = float(sig.get("at") or 0) - AGENT_WINDOW_SEC
        if transcript.limit_note_left(path, since):
            # No request was refused, but Claude Code told the model the old login's limit was
            # reached (a short grace allowance, then stop), and the model winds down even with the
            # new login. Claude Code takes the note back only with a prompt the user types, so the
            # continue text is that prompt.
            files.log_event(f"on-switch session={session}: the model was told the old login's limit was reached")
        elif transcript.agent_stopped_at_limit(path, since):
            # The session went on, but a subagent stopped at the limit: its parent hears only
            # "failed: you've hit your limit, resets at ...", and may wait for that reset.
            # (The FileChanged hook tells the model about its agents, but Claude Code does not
            # always run that hook.)
            files.log_event(f"on-switch session={session}: a subagent stopped at the limit")
        else:
            # Claude Code may still add the note to a later turn: it holds on to the old login's
            # limit until the user types a prompt. Watch the transcript for it in the background.
            background.start(f"after-switch --watch {pid}")
            return False
        # Both are checked after the commands, so that a note or a refusal that came just after
        # the switch counts too.
    session_typing.type_one(pid, resume, deadline, session, cancel_wait=True)
    return True


# Subagents written to this long before the switch, or later, are checked for a stop at the limit.
AGENT_WINDOW_SEC = 600

# How long after a switch, and how often, a session's transcript is watched for the old limit note.
WATCH_SEC = 3 * 3600
WATCH_POLL_SEC = 10


def watch_one(pid: int) -> None:
    """Windows, `encore after-switch --watch <pid>`: type the continue text when Claude Code tells
    the model, after the switch, that the old login's limit was reached.

    Claude Code adds that note to the session's next turn, which may come long after the switch
    (a subagent's report wakes it), and adds it again each turn until the user types a prompt.
    Stops at a newer switch, when the session ends, or after WATCH_SEC."""
    from . import session_typing, win_console  # Windows only (ctypes)

    sig = _current_switch()
    resume = on_switch.config().get("continue_text") or ""
    born = win_console.started_at(pid)
    if sig is None or not resume or born is None:
        return
    at = float(sig.get("at") or 0)
    seen = None
    while time.time() < at + WATCH_SEC:
        time.sleep(WATCH_POLL_SEC)
        if win_console.started_at(pid) != born:
            return  # the session ended
        now_sig = _current_switch()
        if not now_sig or now_sig.get("seq") != sig["seq"]:
            return  # a newer switch takes over
        path = transcript.of_pid(pid)  # changes with /clear
        try:
            stamp = (path, os.stat(transcript._long(path)).st_mtime) if path else None
        except OSError:
            stamp = None
        if stamp is None or stamp == seen:
            continue
        seen = stamp
        if not transcript.limit_note_left(path, at - AGENT_WINDOW_SEC):
            continue
        # The note is right when the new login is at its limit too (encore then had nowhere to go).
        until, source = usage.usable_from(str(sig.get("to")), time.time())
        if until > time.time() + 60:
            files.log_event(f"on-switch session=pid{pid}: the limit note is about '{sig.get('to')}' itself "
                            f"(usable from {usage.fmt_time(until)}, {source}); not typing")
            return
        files.log_event(f"on-switch session=pid{pid}: the model was told the old login's limit was reached "
                        "(a later turn)")
        session_typing.type_one(pid, resume, time.time() + float(on_switch.config().get("wait_sec") or 600),
                                f"pid{pid}", cancel_wait=True)
        return


def _type_command(pid: int, text: str, deadline: float, session: str) -> bool:
    """Type one on-switch command. False when the session never became ready for it."""
    from . import session_typing  # Windows only (ctypes)

    for attempt in range(3):
        if not session_typing.type_one(pid, text, deadline, session, cancel_wait=False):
            return False
        if not text.strip().startswith("/remote-control"):
            time.sleep(2.0)
            return True
        if not session_typing.remote_control_asked_retry(pid, deadline, session):
            return True
        # Remote Control still held the old account's connection. The dialog says: choose
        # Continue (done), wait about 10 seconds, then run /remote-control again.
        files.log_event(f"on-switch session={session}: Remote Control asked to retry; waiting")
        time.sleep(12.0)
    return True
