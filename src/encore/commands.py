"""The encore commands for people (save, add, use, list, install, ...): each one calls the
core and prints the outcome.
"""
from __future__ import annotations

import json
import sys
import time

from . import (Error, IS_WIN, auto_switch, claude_login, claude_settings, on_switch, paths, profiles,
               state, usage)
from .lock import Lock
from .switching import switch_to


# --------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------

def cmd_save(name: str) -> None:
    email = profiles.save_live_login(name)
    print(f"Saved the current login ({email}) as '{name}'.")


def cmd_add(name: str, email: str | None = None) -> None:
    """Log in to another account in a throwaway config folder, then keep that login."""
    profiles.check_new_name(name)
    claude = claude_login.find_claude()
    print("A browser window opens. Sign in with the account to add.")
    print("(If another account is already signed in on claude.ai, sign out there first,")
    print(" or use a private window with the URL that `claude` prints.)\n")
    oauth, oauth_account = claude_login.sign_in_elsewhere(claude, email)
    profiles.save_new_login(name, oauth, oauth_account)
    print(f"\nSaved {oauth_account.get('emailAddress')} as '{name}'.")


def cmd_remove(name: str, force: bool = False) -> None:
    profiles.remove(name, force)
    print(f"Removed '{name}'.")


def cmd_rename(old: str, new: str) -> None:
    profiles.rename(old, new)
    print(f"Renamed '{old}' to '{new}'.")


# --------------------------------------------------------------------------
# Switching
# --------------------------------------------------------------------------

def cmd_use(name: str) -> None:
    with Lock():
        switch_to(name)
    meta = profiles.load_meta(name)
    print(f"Now using '{name}' ({meta.get('email')}).")
    print("Running Claude Code sessions switch too, from their next request.")
    exp = profiles.login_expires_at(meta)
    if exp and exp < time.time():
        relogin(name, meta)


def relogin(name: str, meta: dict) -> None:
    """The saved login has expired: sign in again. Any new login of the same account is kept in
    its profile by itself (sync_back), also one made with /login inside Claude Code."""
    email = meta.get("email")
    print(f"\nThe saved login of '{name}' has expired.")
    if not sys.stdin.isatty():
        print(f"Run /login in Claude Code and sign in as {email}. encore keeps that login by itself.")
        return
    if input(f"Sign in as {email} in the browser now? [Y/n] ").strip().lower() not in ("", "y", "yes"):
        print(f"Later, run /login in Claude Code and sign in as {email}. encore keeps that login by itself.")
        return
    claude_login.sign_in(email)
    with Lock():
        saved = profiles.sync_back()
    if saved == name:
        print(f"Saved the new login in '{name}'.")
    else:
        print(f"That login is not {email}, so '{name}' was not updated.")


def cmd_use_soonest() -> None:
    """Switch to the account that can be used first (one that is not at its limit, or else the one
    whose limit resets first). encore also does this by itself at the limit (auto_switch)."""
    profiles.sync_back()
    now = time.time()
    rows = usage.soonest_first(now)
    if not rows:
        raise Error("no saved account logins")
    for at, name, source in rows:
        when = "usable now" if at <= now else f"usable from {usage.fmt_time(at)}"
        print(f"  {name:<16} {when:<24} ({source})")
    at, name, _ = rows[0]
    if name == profiles.current_profile():
        print(f"'{name}' is already in use.")
        return
    cmd_use(name)
    if at > now:
        print(f"Every account is at its limit. Sessions stopped at the limit continue by themselves at "
              f"{usage.fmt_time(at)}.")


# --------------------------------------------------------------------------
# Looking
# --------------------------------------------------------------------------

def fmt_windows(windows: list) -> str:
    if not windows:
        return "-"
    return "  ".join(f"{w['label']} {w['pct']:.0f}%" for w in windows)


def profile_rows():
    st = state.load()
    cur = profiles.current_profile()
    rows = []
    for name in profiles.profile_names():
        meta = profiles.load_meta(name)
        plan = (profiles.load_secret(name).get("oauthAccount") or {}).get("planDisplayName")
        who = f"{meta.get('email')} ({plan or meta.get('subscriptionType') or '?'})"
        exp = meta.get("loginExpiresAt")
        login = f"login until {usage.fmt_time(exp / 1000)}" if exp else ""
        if exp and exp / 1000 < time.time():
            login = "login EXPIRED - run /login in Claude Code with this account"
        last = st["usage"].get(name, {})
        used = fmt_windows(last.get("windows") or [])
        if last.get("at"):
            used += f"  (as of {usage.fmt_time(last['at'])})"
        rows.append((("*" if name == cur else " "), name, who, login, used))
    return rows, cur


def cmd_list() -> None:
    profiles.sync_back()
    rows, cur = profile_rows()
    if not rows:
        print("No profiles yet. Run: encore setup")
        return
    for mark, name, who, login, used in rows:
        print(f"{mark} {name:<14} {who}")
        extra = "   ".join(x for x in (login, used) if x and x != "-")
        if extra:
            print(f"  {'':<14} {extra}")
    if cur is None:
        print("\n(The current Claude Code login is not saved as a profile.)")
    old = profiles.old_api_key_profiles()
    if old:
        print(f"\nAPI keys saved by an older version (not used any more): {', '.join(old)}. "
              f"Delete with: encore remove <name>")


def cmd_status(as_json: bool = False) -> None:
    profiles.sync_back()
    st = state.load()
    cur = profiles.current_profile()
    if as_json:
        print(json.dumps({"current": cur, "auto": st["auto"], "usage": st["usage"],
                          "profiles": profiles.profile_names()}, indent=2))
        return
    cmd_list()
    print()
    print(auto_description(st["auto"]))
    print(f"Status line installed: {'yes' if claude_settings.statusline_installed() else 'no'}")


def cmd_usage(name: str | None) -> None:
    profiles.sync_back()
    name = name or profiles.current_profile()
    if not name:
        raise Error("the current login is not a saved profile; give a profile name")
    windows = usage.ask_anthropic(name)
    print(f"{name}:")
    for w in windows:
        print(f"  {w['label']:<16} {w['pct']:5.1f}%   resets {usage.fmt_time(w.get('resets'))}")


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def auto_description(a: dict) -> str:
    if not a.get("enabled", True):
        return "Automatic switch: off (turn on: encore auto on)"
    threshold = float(a.get("threshold") or 100)
    when = ("when Claude Code stops at the usage limit" if threshold >= 100
            else f"when the account in use reaches {threshold:.0f}% of a limit")
    return f"Automatic switch: on - {when}, move to the account that can be used first"


def cmd_auto(on: bool, threshold: float | None) -> None:
    a = auto_switch.configure(on, threshold)
    print(auto_description(a))
    if on and not claude_settings.statusline_installed():
        print("It needs the status line and hooks. Run: encore install")


def cmd_on_switch(action: str, text: list) -> None:
    """Show or change what is typed into running sessions after a switch."""
    cur = on_switch.change(action, text)
    print("After a switch, typed into each running session:")
    for c in cur["commands"] or []:
        print(f"  {c}")
    if not cur["commands"]:
        print("  (nothing)")
    if cur["continue_text"]:
        print(f"If the session had stopped at a usage limit, also: {cur['continue_text']}")
    else:
        print("If the session had stopped at a usage limit: nothing (continue is off)")
    if not IS_WIN:
        print("(Typing into sessions works on Windows only. Here the model is told about the switch instead.)")


def cmd_install() -> None:
    try:
        moved = paths.move_old_home()
    except OSError as e:
        raise Error(f"could not move the profiles to {paths.home().parent / '.encore'} ({e}). "
                    "Close Claude Code and run: encore install") from e
    if moved:
        print(f"Moved the profiles from {moved} to {paths.home()}.")
    kept_old_line = claude_settings.install()
    print(f"Installed the status line and the hooks (StopFailure, SessionStart, FileChanged) "
          f"in {paths.settings_path()}.")
    print("At the usage limit, encore now moves to the account that can be used first.")
    print("Sessions started from now on get the on-switch commands typed in after a switch "
          "(see: encore on-switch).")
    if kept_old_line:
        print("Your previous status line still shows, after the encore part.")


def cmd_uninstall() -> None:
    claude_settings.uninstall()
    print("Removed the status line and the hooks.")
