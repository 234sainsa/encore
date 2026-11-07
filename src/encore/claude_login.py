"""Running `claude auth login`: signing in to an account in the browser.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import Error, IS_MAC, credentials, files


def find_claude() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise Error("the `claude` command was not found on PATH")
    return exe


def sign_in_elsewhere(claude: str, email: str | None = None):
    """Sign in in a throwaway config folder, so that the live login stays as it is.

    Returns (claudeAiOauth, oauthAccount) of the new login."""
    tmp = Path(tempfile.mkdtemp(prefix="encore-login-"))
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(tmp))
    before = credentials.keychain_services() if IS_MAC else set()
    try:
        args = [claude, "auth", "login"] + (["--email", email] if email else [])
        if subprocess.run(args, env=env).returncode != 0:
            raise Error("the login did not finish")
        creds = files.read_json(tmp / ".credentials.json")
        if IS_MAC and not creds:
            new = sorted(credentials.keychain_services() - before)
            if len(new) == 1:
                item = credentials.KeychainStore(new[0])
                creds = item.read()
                item.delete()  # the throwaway folder's keychain item is not needed any more
        if not creds or not creds.get("claudeAiOauth"):
            raise Error("could not find the new login (see README: macOS)")
        oauth_account = (files.read_json(tmp / ".claude.json", {}) or {}).get("oauthAccount")
        if not oauth_account:
            r = subprocess.run([claude, "auth", "status", "--json"], env=env,
                               capture_output=True, text=True, encoding="utf-8")
            info = json.loads(r.stdout or "{}")
            oauth_account = {"emailAddress": info.get("email"), "organizationUuid": info.get("orgId"),
                             "organizationName": info.get("orgName")}
        return creds["claudeAiOauth"], oauth_account
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sign_in(email: str | None) -> None:
    """Sign in again in the live config folder (Claude Code then uses the new login)."""
    args = [find_claude(), "auth", "login"] + (["--email", email] if email else [])
    if subprocess.run(args).returncode != 0:
        raise Error("the login did not finish")
