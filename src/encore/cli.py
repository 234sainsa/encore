"""The command line: argparse, and the exit code of every command.
"""
from __future__ import annotations

import argparse
import sys

from . import IS_WIN, Error, VERSION, after_switch, commands, hooks, setup_menu, statusline, watcher


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="encore",
                                description="Switch Claude Code between your accounts automatically.")
    p.add_argument("--version", action="version", version=f"encore {VERSION}")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("setup", help="interactive setup")
    x = sub.add_parser("save", help="save the current login as a profile")
    x.add_argument("name")
    x = sub.add_parser("add", help="sign in to another account in the browser and save it")
    x.add_argument("name")
    x.add_argument("--email")
    sub.add_parser("list", help="list profiles")
    x = sub.add_parser("status", help="profiles, usage and the automatic switch")
    x.add_argument("--json", action="store_true")
    x = sub.add_parser("use", help="switch to a profile")
    x.add_argument("name", nargs="?")
    x.add_argument("--soonest", action="store_true",
                   help="switch to the account that can be used first (when every account is at its limit)")
    x = sub.add_parser("usage", help="ask Anthropic for the current usage of a profile")
    x.add_argument("name", nargs="?")
    x = sub.add_parser("rename", help="rename a profile")
    x.add_argument("old")
    x.add_argument("new")
    x = sub.add_parser("remove", help="delete a profile")
    x.add_argument("name")
    x.add_argument("--force", action="store_true")
    x = sub.add_parser("auto", help="turn the automatic switch at the usage limit on or off (on by default)")
    x.add_argument("state", choices=["on", "off"])
    x.add_argument("--threshold", type=float,
                   help="switch early, at this percent of a limit (default 100 = when Claude Code stops at the limit)")
    x = sub.add_parser("on-switch", help="what to type into running sessions after a switch")
    x.add_argument("action", nargs="?", default="show", choices=["show", "set", "add", "clear", "continue", "reset"])
    x.add_argument("text", nargs="*")
    sub.add_parser("install", help="add the status line and StopFailure hook to settings.json")
    sub.add_parser("uninstall", help="remove them again")
    # Run by Claude Code (the command lines `install` writes into settings.json).
    sub.add_parser("statusline", help=argparse.SUPPRESS)
    sub.add_parser("hook-stop-failure", help=argparse.SUPPRESS)
    sub.add_parser("auto-check", help=argparse.SUPPRESS)
    sub.add_parser("hook-session-start", help=argparse.SUPPRESS)
    sub.add_parser("hook-switched", help=argparse.SUPPRESS)
    # Run by encore itself, in the background after a switch (Windows).
    x = sub.add_parser("after-switch", help=argparse.SUPPRESS)
    x.add_argument("--pid", type=int)
    return p


def run(a: argparse.Namespace) -> int:
    """Run the parsed command. Returns its exit code."""
    if a.cmd in (None, "setup"):
        setup_menu.run()
    elif a.cmd == "save":
        commands.cmd_save(a.name)
    elif a.cmd == "add":
        commands.cmd_add(a.name, a.email)
    elif a.cmd == "list":
        commands.cmd_list()
    elif a.cmd == "status":
        commands.cmd_status(a.json)
    elif a.cmd == "use":
        if a.soonest:
            commands.cmd_use_soonest()
        elif a.name:
            commands.cmd_use(a.name)
        else:
            raise Error("give a profile name, or --soonest")
    elif a.cmd == "usage":
        commands.cmd_usage(a.name)
    elif a.cmd == "rename":
        commands.cmd_rename(a.old, a.new)
    elif a.cmd == "remove":
        commands.cmd_remove(a.name, a.force)
    elif a.cmd == "auto":
        commands.cmd_auto(a.state == "on", a.threshold)
    elif a.cmd == "on-switch":
        commands.cmd_on_switch(a.action, a.text)
    elif a.cmd == "install":
        commands.cmd_install()
    elif a.cmd == "uninstall":
        commands.cmd_uninstall()
    elif a.cmd == "statusline":
        return statusline.run()
    elif a.cmd == "hook-stop-failure":
        return hooks.stop_failure()
    elif a.cmd == "auto-check":
        watcher.run()  # started in the background by the status line near the limit
    elif a.cmd == "hook-session-start":
        return hooks.session_start()
    elif a.cmd == "hook-switched":
        return hooks.switched()
    elif a.cmd == "after-switch":
        if not IS_WIN:
            return 0
        if a.pid:
            after_switch.type_into_one(a.pid)
        else:
            after_switch.type_into_all()
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    a = build_parser().parse_args(argv)
    try:
        return run(a)
    except Error as e:
        print(f"encore: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
