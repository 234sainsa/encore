"""encore: keep several Claude Code logins and switch to another one at the usage limit.

Layers. A module imports only from its own layer or the layers above it, never from below:

  shared        this file (VERSION, Error, IS_WIN, IS_MAC), paths, files, lock, state, background
  data          credentials, claude_login, profiles, switch_signal, on_switch, claude_settings
  core          switching, usage, auto_switch, watcher
  after switch  screen, transcript (pure parsing), win_console, session_typing (Windows only),
                after_switch (what a session gets after a switch)
  edges         cli, commands, setup_menu (for people); statusline, hooks (run by Claude Code);
                auto-check, after-switch (run by encore itself, in the background)

Only the edges read stdin, print, and choose exit codes. Everything else returns values or raises
Error; the messages for people are made at the edges. win_console and session_typing load ctypes
and are imported on Windows code paths only.
"""
import os
import sys

VERSION = "1.1.0"
IS_MAC = sys.platform == "darwin"
IS_WIN = os.name == "nt"


class Error(Exception):
    """An error shown to the user without a traceback."""
