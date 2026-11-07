"""The switch: make a saved profile the login Claude Code uses, and tell running sessions.
"""
from __future__ import annotations

from . import IS_WIN, Error, background, claude_settings, credentials, files, profiles, switch_signal


def switch_to(name: str, why: str = "manual") -> None:
    """Make `name` the login Claude Code uses. Call with the Lock held."""
    meta = profiles.load_meta(name)
    if meta.get("kind") == "apikey":
        raise Error(f"'{name}' is an API key saved by an older version; API keys are not used any more "
                    f"(delete it: encore remove {name})")
    before = profiles.current_profile()
    profiles.sync_back()
    secret = profiles.load_secret(name)
    if not secret.get("claudeAiOauth"):
        raise Error(f"profile '{name}' has no saved login")
    credentials.replace_live_login(secret["claudeAiOauth"], secret.get("oauthAccount"))
    claude_settings.drop_old_api_key_helper()
    files.log_event(f"switch to={name} why={why}")
    if before != name:
        switch_signal.announce(before, name, why)
        if IS_WIN:
            # Type the on-switch commands into the running sessions (`after-switch`). The FileChanged
            # hook on switched.json is not enough: Claude Code does not always run it (2.1.319 ran it
            # in no session), and then nothing reconnected Remote Control.
            background.start("after-switch")
