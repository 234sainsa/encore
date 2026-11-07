"""Saved profiles (~/.encore/profiles/<name>/{meta,secret}.json) and how they relate to the
live login: which profile it is, keeping its refreshed tokens, saving it as a new profile.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

from . import Error, credentials, files, paths, state
from .lock import Lock

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


# --------------------------------------------------------------------------
# The saved profiles
# --------------------------------------------------------------------------

def profile_dir(name: str) -> Path:
    return paths.home() / "profiles" / name


def _all_profile_names() -> list:
    d = paths.home() / "profiles"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if (p / "meta.json").exists())


def profile_names() -> list:
    """The saved Claude accounts."""
    return [n for n in _all_profile_names() if load_meta(n).get("kind") != "apikey"]


def old_api_key_profiles() -> list:
    """API key profiles saved by an older version. encore does not use them any more."""
    return [n for n in _all_profile_names() if load_meta(n).get("kind") == "apikey"]


def load_meta(name: str) -> dict:
    meta = files.read_json(profile_dir(name) / "meta.json")
    if meta is None:
        raise Error(f"there is no profile named '{name}' (see: encore list)")
    return meta


def load_secret(name: str) -> dict:
    return files.read_json(profile_dir(name) / "secret.json", {}) or {}


def save_profile(name: str, meta: dict, secret: dict | None = None) -> None:
    if secret is not None:
        files.write_json(profile_dir(name) / "secret.json", secret, private=True)
    files.write_json(profile_dir(name) / "meta.json", meta)


def check_new_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise Error("a profile name uses letters, digits, '.', '_' or '-' (up to 32 characters)")
    if (profile_dir(name) / "meta.json").exists():
        raise Error(f"a profile named '{name}' already exists")


def login_expires_at(meta: dict):
    """When the saved login stops working (epoch seconds), or None."""
    exp = meta.get("loginExpiresAt")
    return exp / 1000 if exp else None


def rename(old: str, new: str) -> None:
    load_meta(old)
    check_new_name(new)
    with Lock():
        os.replace(profile_dir(old), profile_dir(new))
        meta = load_meta(new)
        meta["name"] = new
        save_profile(new, meta)
        with state.edit() as st:
            if old in st["usage"]:
                st["usage"][new] = st["usage"].pop(old)
    files.log_event(f"rename {old} -> {new}")


def remove(name: str, force: bool = False) -> None:
    load_meta(name)
    if current_profile() == name and not force:
        raise Error(f"'{name}' is in use; switch to another profile first (or pass --force)")
    shutil.rmtree(profile_dir(name))


# --------------------------------------------------------------------------
# Profiles and the live login
# --------------------------------------------------------------------------

def identity(oauth_account: dict | None):
    """Who a login belongs to: (email, organization)."""
    if not oauth_account:
        return None
    email = (oauth_account.get("emailAddress") or "").lower()
    org = oauth_account.get("organizationUuid") or ""
    return (email, org) if email else None


def meta_from_login(name: str, oauth: dict, oauth_account: dict) -> dict:
    return {
        "name": name,
        "kind": "subscription",
        "email": oauth_account.get("emailAddress"),
        "organizationUuid": oauth_account.get("organizationUuid"),
        "organizationName": oauth_account.get("organizationName"),
        "subscriptionType": oauth.get("subscriptionType"),
        "loginExpiresAt": oauth.get("refreshTokenExpiresAt"),
        "created": int(time.time()),
    }


def find_profile_for(oauth_account: dict | None):
    who = identity(oauth_account)
    if not who:
        return None
    for name in profile_names():
        meta = load_meta(name)
        if meta.get("kind") != "subscription":
            continue
        if ((meta.get("email") or "").lower(), meta.get("organizationUuid") or "") == who:
            return name
    return None


def current_profile():
    """The saved account that Claude Code uses now, or None."""
    _, _, oauth_account = credentials.read_live_login()
    return find_profile_for(oauth_account)


def sync_back():
    """Copy the live login (which Claude Code refreshes by itself) into its profile.

    Must run before the live login is replaced, or the newest tokens are lost.
    Returns the name of the profile that matches the live login, or None.
    """
    _, oauth, oauth_account = credentials.read_live_login()
    if not oauth or not oauth_account:
        return None
    name = find_profile_for(oauth_account)
    if not name:
        return None
    secret = load_secret(name)
    if secret.get("claudeAiOauth") != oauth or secret.get("oauthAccount") != oauth_account:
        meta = load_meta(name)
        meta["subscriptionType"] = oauth.get("subscriptionType")
        meta["loginExpiresAt"] = oauth.get("refreshTokenExpiresAt")
        save_profile(name, meta, {"claudeAiOauth": oauth, "oauthAccount": oauth_account})
    return name


def save_live_login(name: str) -> str:
    """Save the login Claude Code uses now as profile `name`. Returns its email address."""
    check_new_name(name)
    _, oauth, oauth_account = credentials.read_live_login()
    if not oauth or not oauth_account:
        raise Error("Claude Code is not logged in with a Claude subscription (run `claude auth login`)")
    existing = find_profile_for(oauth_account)
    if existing:
        raise Error(f"this login is already saved as '{existing}'")
    _save_login(name, oauth, oauth_account)
    return oauth_account.get("emailAddress")


def save_new_login(name: str, oauth: dict, oauth_account: dict) -> None:
    """Save a login made outside Claude Code's config folder (`encore add`) as profile `name`."""
    other = find_profile_for(oauth_account)
    if other:
        raise Error(f"this account is already saved as '{other}'")
    _save_login(name, oauth, oauth_account)


def _save_login(name: str, oauth: dict, oauth_account: dict) -> None:
    save_profile(name, meta_from_login(name, oauth, oauth_account),
                 {"claudeAiOauth": oauth, "oauthAccount": oauth_account})
