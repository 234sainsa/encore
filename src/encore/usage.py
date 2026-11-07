"""Usage numbers: asking Anthropic, reading the status line's numbers, and what encore saw last.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime

from . import Error, VERSION, profiles, state

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
USER_AGENT = f"encore/{VERSION}"


def iso_to_epoch(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def fmt_time(epoch) -> str:
    if not epoch:
        return "?"
    t = datetime.fromtimestamp(epoch)
    now = datetime.now()
    return t.strftime("%H:%M") if t.date() == now.date() else t.strftime("%m-%d %H:%M")


# --------------------------------------------------------------------------
# The numbers
# --------------------------------------------------------------------------

def fetch_usage(access_token: str, timeout: float = 15) -> dict:
    """GET the usage numbers that `/usage` in Claude Code shows. Not a documented API."""
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {access_token}",
        "anthropic-beta": OAUTH_BETA,
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise Error(f"usage request failed: HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise Error(f"usage request failed: {e.reason}") from None


def windows_from_api(data: dict) -> list:
    out = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        w = data.get(key)
        if isinstance(w, dict) and w.get("utilization") is not None:
            out.append({"label": label, "pct": float(w["utilization"]),
                        "resets": iso_to_epoch(w.get("resets_at"))})
    for item in data.get("limits") or []:
        if not isinstance(item, dict) or not item.get("is_active") or item.get("kind") == "weekly_all":
            continue
        out.append({"label": item.get("kind", "?"), "pct": float(item.get("percent") or 0),
                    "resets": iso_to_epoch(item.get("resets_at"))})
    return out


def windows_from_statusline(rate_limits: dict) -> list:
    out = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        w = rate_limits.get(key)
        if isinstance(w, dict) and w.get("used_percentage") is not None:
            out.append({"label": label, "pct": float(w["used_percentage"]),
                        "resets": w.get("resets_at")})
    return out


def record_usage(name: str, windows: list) -> None:
    """Remember the numbers seen for `name` (state.json is only written when they changed)."""
    if state.load()["usage"].get(name, {}).get("windows") == windows:
        return
    with state.edit() as st:
        st["usage"][name] = {"at": int(time.time()), "windows": windows}


def ask_anthropic(name: str) -> list:
    """The current numbers of profile `name`, asked from Anthropic now (and remembered)."""
    profiles.load_meta(name)
    oauth = profiles.load_secret(name).get("claudeAiOauth") or {}
    if (oauth.get("expiresAt") or 0) / 1000 < time.time():
        raise Error(f"the saved access token of '{name}' has expired. Claude Code renews it the next "
                    f"time '{name}' is used; encore does not renew tokens itself")
    windows = windows_from_api(fetch_usage(oauth["accessToken"]))
    record_usage(name, windows)
    return windows


# --------------------------------------------------------------------------
# When an account can be used
# --------------------------------------------------------------------------

def usable_from(name: str, now: float, threshold: float = 100.0, timeout: float = 15):
    """(time from which the account can be used again, where the numbers came from).

    An account counts as used up while a limit is at `threshold` percent or more. The numbers come
    from Anthropic when the saved access token still works, otherwise from the last numbers
    encore saw for that account (status line, `usage`)."""
    windows, source = None, "no numbers yet"
    oauth = profiles.load_secret(name).get("claudeAiOauth") or {}
    if (oauth.get("expiresAt") or 0) / 1000 > now + 60:
        try:
            windows = windows_from_api(fetch_usage(oauth["accessToken"], timeout))
            record_usage(name, windows)
            source = "now"
        except Error:
            pass
    if windows is None:
        seen = state.load()["usage"].get(name)
        if seen:
            windows, source = seen.get("windows"), f"seen {fmt_time(seen.get('at'))}"
    full = [w for w in windows or [] if w["pct"] >= threshold and (w.get("resets") or 0) > now]
    return (max(w["resets"] for w in full) if full else now), source


def soonest_first(now: float) -> list:
    """[(usable from, profile name, where the numbers came from)] of every saved account, the
    account that can be used first at the top."""
    rows = []
    for name in profiles.profile_names():
        at, source = usable_from(name, now)
        rows.append((at, name, source))
    rows.sort()
    return rows
