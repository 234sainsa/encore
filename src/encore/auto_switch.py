"""The automatic switch to another account at the usage limit: its settings and the decision.
"""
from __future__ import annotations

import time

from . import Error, profiles, state, switching, usage
from .lock import Lock


def current_threshold() -> float:
    return float(state.load()["auto"].get("threshold") or 100)


def configure(on: bool, threshold: float | None) -> dict:
    """Turn the automatic switch on or off (and set its threshold). Returns its settings."""
    with state.edit() as st:
        a = st["auto"]
        a["enabled"] = on
        if threshold is not None:
            if not 1 <= threshold <= 100:
                raise Error("the threshold is a percentage from 1 to 100")
            a["threshold"] = threshold
    return a


def switch_if_at_limit(limit_hit: bool = False) -> str | None:
    """When the account in use is at its limit, move to the saved account that can be used first.

    Called by the watcher (`auto-check`) and by the StopFailure hook (limit_hit=True). The usage
    numbers come from Anthropic: the status line keeps the numbers of the last request that worked
    (it showed 99% while the account was already at 100% and Claude Code was waiting with
    "Retrying in 5h"). Returns the new account."""
    st = state.load()
    if not st["auto"].get("enabled", True):
        return None
    threshold = current_threshold()
    with Lock():
        cur = profiles.sync_back()
    if not cur:
        return None  # the login in use is not saved: leave it alone
    names = profiles.profile_names()
    if len(names) < 2:
        return None
    # The usage requests run without the lock: they can take a while.
    now = time.time()
    ready = {cur: usage.usable_from(cur, now, threshold, timeout=8)[0]}
    if limit_hit and ready[cur] <= now:
        ready[cur] = now + 5 * 3600  # it did stop at the limit, though the numbers do not show it yet
    if ready[cur] <= now:
        return None
    ready.update({n: usage.usable_from(n, now, threshold, timeout=8)[0] for n in names if n != cur})
    best = min(names, key=lambda n: (ready[n], n))
    if ready[best] >= ready[cur]:
        return None  # no account is better than the one in use
    with Lock():
        if profiles.current_profile() != cur:
            return None  # someone switched in the meantime
        switching.switch_to(best, why=f"auto: '{cur}' reached its usage limit")
    return best
