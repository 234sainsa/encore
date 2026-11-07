"""`encore setup`: the interactive menu.
"""
from __future__ import annotations

from . import Error, VERSION, commands, paths, profiles, state


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def ask_name(prompt: str, default: str | None = None) -> str:
    while True:
        name = ask(prompt, default)
        try:
            profiles.check_new_name(name)
            return name
        except Error as e:
            print(f"  {e}")


def pick_profile() -> str | None:
    names = profiles.profile_names()
    if not names:
        print("  (no matching profiles)")
        return None
    for i, n in enumerate(names, 1):
        print(f"  {i}) {n}")
    choice = ask("Number")
    if choice.isdigit() and 1 <= int(choice) <= len(names):
        return names[int(choice) - 1]
    return None


def run() -> None:
    print(f"encore {VERSION} setup. Profiles are kept in {paths.home()}\n")
    while True:
        try:
            commands.cmd_list()
        except Error as e:
            print(f"  ({e})")
        a = state.load()["auto"]
        th = float(a.get("threshold") or 100)
        auto = ("off" if not a.get("enabled", True)
                else "on (when Claude Code stops at the limit)" if th >= 100 else f"on (at {th:.0f}%)")
        print("\nWhat do you want to do?")
        print("  1) Save the current Claude Code login as a profile")
        print("  2) Add another Claude account (signs in with the browser)")
        print("  3) Install the status line and hooks (needed for the automatic switch)")
        print("  4) Switch to a profile now")
        print(f"  5) Automatic switch at the usage limit: {auto}")
        print("  6) Remove a profile")
        print("  7) Rename a profile")
        print("  q) Quit")
        choice = ask("Choose").lower()
        print()
        try:
            if choice == "1":
                commands.cmd_save(ask_name("Profile name", "main"))
            elif choice == "2":
                commands.cmd_add(ask_name("Profile name"), ask("Email to pre-fill (optional)") or None)
            elif choice == "3":
                commands.cmd_install()
            elif choice == "4":
                name = pick_profile()
                if name:
                    commands.cmd_use(name)
            elif choice == "5":
                if a.get("enabled", True):
                    if ask("Turn it off? (y/n)", "n").lower() == "y":
                        commands.cmd_auto(False, None)
                else:
                    commands.cmd_auto(True, float(ask("Switch at what percent of the limit "
                                                      "(100 = when Claude Code stops at the limit)", "100")))
            elif choice == "6":
                name = pick_profile()
                if name and ask(f"Remove '{name}'? (y/n)", "n").lower() == "y":
                    commands.cmd_remove(name)
            elif choice == "7":
                name = pick_profile()
                if name:
                    commands.cmd_rename(name, ask_name("New name"))
            elif choice in ("q", "quit", "exit", ""):
                return
        except Error as e:
            print(f"Error: {e}")
        except ValueError:
            print("Error: that was not a number")
        print()
