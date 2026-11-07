"""The login Claude Code uses now: its credentials (a file, or the macOS keychain) and the account
in .claude.json.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
from pathlib import Path

from . import Error, IS_MAC, files, paths

KEYCHAIN_SERVICE = "Claude Code-credentials"


# --------------------------------------------------------------------------
# Where Claude Code keeps the login
# --------------------------------------------------------------------------

class FileStore:
    """Windows and Linux: <config dir>/.credentials.json"""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.claude_dir() / ".credentials.json"

    def describe(self) -> str:
        return str(self.path)

    def read(self):
        return files.read_json(self.path)

    def write(self, data) -> None:
        files.write_json(self.path, data, private=True)


class KeychainStore:
    """macOS: a generic password item in the login keychain. (Not tested by the author.)"""

    def __init__(self, service: str):
        self.service = service

    def describe(self) -> str:
        return f"macOS Keychain item '{self.service}'"

    def _account(self) -> str:
        r = subprocess.run(["security", "find-generic-password", "-s", self.service],
                           capture_output=True, text=True)
        m = re.search(r'"acct"<blob>="([^"]*)"', r.stdout)
        return m.group(1) if m else getpass.getuser()

    def read(self):
        r = subprocess.run(["security", "find-generic-password", "-s", self.service, "-w"],
                           capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout.strip())

    def write(self, data) -> None:
        # The secret goes through stdin as hex (-X), never on the command line.
        hexpw = json.dumps(data, separators=(",", ":")).encode("utf-8").hex()
        cmd = f'add-generic-password -U -a "{self._account()}" -s "{self.service}" -X {hexpw}\n'
        r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True)
        if r.returncode != 0 or "error" in (r.stdout + r.stderr).lower():
            raise Error(f"could not write {self.describe()}: {(r.stdout + r.stderr).strip()}")

    def delete(self) -> None:
        subprocess.run(["security", "delete-generic-password", "-s", self.service],
                       capture_output=True, text=True)


def keychain_services() -> set:
    r = subprocess.run(["security", "dump-keychain"], capture_output=True, text=True)
    return set(re.findall(r'"svce"<blob>="(Claude Code-credentials[^"]*)"', r.stdout))


def live_store():
    if not IS_MAC:
        return FileStore()
    service = os.environ.get("ENCORE_KEYCHAIN_SERVICE")
    if not service:
        if os.environ.get("CLAUDE_CONFIG_DIR"):
            raise Error("on macOS with CLAUDE_CONFIG_DIR set, also set ENCORE_KEYCHAIN_SERVICE "
                        "to the keychain item name Claude Code uses (see README)")
        service = KEYCHAIN_SERVICE
    ks = KeychainStore(service)
    if ks.read() is not None or not FileStore().path.exists():
        return ks
    return FileStore()  # Claude Code falls back to the file when the keychain refuses


# --------------------------------------------------------------------------
# The live login
# --------------------------------------------------------------------------

def read_live_login():
    """(whole credentials file, its claudeAiOauth part, oauthAccount from .claude.json)"""
    creds = live_store().read() or {}
    oauth = creds.get("claudeAiOauth")
    oauth_account = (files.read_json(paths.claude_json_path(), {}) or {}).get("oauthAccount")
    return creds, oauth, oauth_account


def replace_live_login(oauth: dict, oauth_account: dict | None) -> None:
    """Make Claude Code use this login. The old credentials file is backed up first."""
    live = live_store()
    creds = live.read() or {}
    files.backup("credentials", creds)
    creds["claudeAiOauth"] = oauth  # other keys (MCP logins etc.) stay
    live.write(creds)
    if oauth_account:
        _set_oauth_account(oauth_account)


def _set_oauth_account(oauth_account: dict) -> None:
    path = paths.claude_json_path()
    data = files.read_json(path, {}) or {}
    if data.get("oauthAccount") != oauth_account:
        data["oauthAccount"] = oauth_account
        files.write_json(path, data)
