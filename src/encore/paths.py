"""Where Claude Code and encore keep their files, and the command line that runs encore.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def claude_dir() -> Path:
    d = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(d).expanduser() if d else Path.home() / ".claude"


def claude_json_path() -> Path:
    # With CLAUDE_CONFIG_DIR, Claude Code keeps .claude.json inside that folder.
    d = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(d).expanduser() / ".claude.json" if d else Path.home() / ".claude.json"


def settings_path() -> Path:
    return claude_dir() / "settings.json"


def home() -> Path:
    """encore's own folder (~/.encore)."""
    d = os.environ.get("ENCORE_HOME")
    return Path(d).expanduser() if d else Path.home() / ".encore"


def self_command() -> str:
    """The command line that runs encore, for settings.json.

    From a checkout (or an editable install) the launcher encore.py next to src/ is used, so
    the command lines in settings.json keep working. With pipx there is no launcher: `-m encore`."""
    override = os.environ.get("ENCORE_COMMAND")
    if override:
        return override
    py = Path(sys.executable).as_posix()
    here = Path(__file__).resolve()
    launcher = here.parents[2] / "encore.py"
    if here.parents[1].name == "src" and launcher.is_file():
        return f'"{py}" "{launcher.as_posix()}"'
    return f'"{py}" -m encore'
