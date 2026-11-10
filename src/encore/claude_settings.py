"""Claude Code's settings.json: encore's status line and hooks (install, uninstall), and the
cleanup of what older versions left there.

An entry is ours when its command line runs encore (encore.py, `-m encore`, or this install's own
command line) or the version of the old name; everything else is left alone. "encore" is an
ordinary word, so a command line that merely contains it is not enough.
"""
from __future__ import annotations

import re

from . import files, on_switch, paths, state, switch_signal

_RUNS_ENCORE = re.compile(r'(?:encore\.py"?|-m encore) [a-z-]+$')

OUR_HOOK_EVENTS = ("StopFailure", "SessionStart", "FileChanged", "CwdChanged")


def load() -> dict:
    return files.read_json(paths.settings_path(), {}) or {}


def save(s: dict) -> None:
    files.backup("settings", files.read_json(paths.settings_path()))
    files.write_json(paths.settings_path(), s)


def is_ours(command) -> bool:
    if not isinstance(command, str):
        return False
    return (command.startswith(paths.self_command() + " ") or paths.OLD_NAME in command
            or _RUNS_ENCORE.search(command) is not None)


def statusline_installed() -> bool:
    return is_ours((load().get("statusLine") or {}).get("command"))


def drop_old_api_key_helper() -> None:
    """Older versions could point Claude Code at an API key (apiKeyHelper). Take it out."""
    s = load()
    if is_ours(s.get("apiKeyHelper")):
        del s["apiKeyHelper"]
        save(s)


def _our_hooks(cmd: str) -> dict:
    return {
        "StopFailure": {"matcher": "rate_limit",
                        "hooks": [{"type": "command", "command": f"{cmd} hook-stop-failure"}]},
        # Gives every new session the signal file to watch.
        "SessionStart": {"hooks": [{"type": "command", "command": f"{cmd} hook-session-start"}]},
        # Runs in every session after a switch (even when idle): types the on-switch commands.
        # asyncRewake is for systems where typing is not supported (exit 2 = tell the model).
        "FileChanged": {"matcher": switch_signal.path().name,
                        "hooks": [{"type": "command", "command": f"{cmd} hook-switched",
                                   "async": True, "asyncRewake": True,
                                   "timeout": int(on_switch.DEFAULTS["wait_sec"]) + 60}]},
        # When the session's working folder changes, Claude Code replaces the watched files with
        # what the CwdChanged hooks answer (nothing, without this hook): switched.json would no
        # longer be watched and the session would not hear about later switches.
        "CwdChanged": {"hooks": [{"type": "command", "command": f"{cmd} hook-cwd-changed"}]},
    }


def _has_ours(group: dict) -> bool:
    return any(is_ours(h.get("command")) for h in group.get("hooks", []))


# With CLAUDE_CODE_RETRY_WATCHDOG=1, Claude Code does not stop at the usage limit: it waits for the
# reset ("Retrying in 5h"), so no StopFailure hook runs and nothing switches. Its subagents wait
# too, and keep the old login when they try again. A usage-limit wait of at most 1 ms makes Claude
# Code stop at the limit instead (it still waits out overloaded servers). Without the watchdog
# the value changes nothing.
STOP_AT_LIMIT = ("CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS", "1")


def add_stop_at_limit() -> None:
    """Put STOP_AT_LIMIT into the env of settings.json, once. When the person takes it out or sets
    another value, it is left that way."""
    key, value = STOP_AT_LIMIT
    if state.load().get("stop_at_limit_added"):
        return
    s = load()
    env = s.setdefault("env", {})
    if key not in env:
        env[key] = value
        save(s)
    with state.edit() as st:
        st["stop_at_limit_added"] = True


def _drop_stop_at_limit(s: dict, st: dict) -> None:
    key, value = STOP_AT_LIMIT
    env = s.get("env")
    if st.pop("stop_at_limit_added", None) and isinstance(env, dict) and env.get(key) == value:
        del env[key]
        if not env:
            del s["env"]


def add_missing_hooks() -> None:
    """For installs made before a hook was added: put in the hooks of ours that are missing.
    Does nothing when encore's hooks are not installed (after `encore uninstall`)."""
    s = load()
    hooks = s.get("hooks")
    if not isinstance(hooks, dict) or not any(_has_ours(g) for g in hooks.get("FileChanged", [])):
        return
    missing = {event: group for event, group in _our_hooks(paths.self_command()).items()
               if not any(_has_ours(g) for g in hooks.get(event, []))}
    if not missing:
        return
    for event, group in missing.items():
        hooks[event] = list(hooks.get(event, [])) + [group]
    save(s)


def install() -> bool:
    """Add our status line and hooks, or bring ours up to date (a moved checkout, the old name).
    Returns True when the status line that was there before keeps showing after ours."""
    s = load()
    cmd = paths.self_command()
    with state.edit() as st:
        line = s.get("statusLine") or {}
        if line.get("command") and not is_ours(line["command"]):
            st["statusline_then"] = line["command"]  # keep showing the old status line after ours
        s["statusLine"] = {"type": "command", "command": f"{cmd} statusline", "padding": line.get("padding", 0)}
        hooks = s.setdefault("hooks", {})
        for event, group in _our_hooks(cmd).items():
            hooks[event] = [g for g in hooks.get(event, []) if not _has_ours(g)] + [group]
        if is_ours(s.get("apiKeyHelper")):
            del s["apiKeyHelper"]  # left by an older version (API keys are not used any more)
        save(s)
    add_stop_at_limit()
    switch_signal.ensure_exists()
    return bool(st.get("statusline_then"))


def uninstall() -> None:
    """Take our status line and hooks out again, and put the earlier status line back."""
    s = load()
    with state.edit() as st:
        if is_ours((s.get("statusLine") or {}).get("command")):
            if st.get("statusline_then"):
                s["statusLine"] = {"type": "command", "command": st.pop("statusline_then")}
            else:
                del s["statusLine"]
        for event in OUR_HOOK_EVENTS:
            groups = (s.get("hooks") or {}).get(event) or []
            groups = [g for g in groups if not _has_ours(g)]
            if groups:
                s["hooks"][event] = groups
            elif "hooks" in s:
                s["hooks"].pop(event, None)
        if "hooks" in s and not s["hooks"]:
            del s["hooks"]
        if is_ours(s.get("apiKeyHelper")):
            del s["apiKeyHelper"]  # left by an older version
        _drop_stop_at_limit(s, st)
        save(s)
