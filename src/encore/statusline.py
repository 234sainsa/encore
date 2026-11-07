"""The status line command: the account in use and its usage, e.g.
"[main] 5時間 2%(19:30) 1週間 97%(11/6 6:00)".

Each render also keeps the live login's tokens in its profile, remembers the numbers, and starts
the watcher near the limit.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime

from . import Error, profiles, state, usage, watcher
from .lock import Lock

STATUS_LABELS = {"5h": "5時間", "7d": "1週間"}


def run() -> int:
    raw = sys.stdin.read()
    text = _own_text(raw)
    then = state.load().get("statusline_then")
    if then:
        r = subprocess.run(then, shell=True, input=raw, capture_output=True, text=True, encoding="utf-8")
        other = (r.stdout or "").rstrip("\n")
        if other:
            text = f"{text} | {other}"
    print(text)
    return 0


def _own_text(raw: str) -> str:
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    try:
        rl = data.get("rate_limits")
        windows = usage.windows_from_statusline(rl) if isinstance(rl, dict) else None
        try:
            with Lock(timeout=1.0):
                cur = profiles.sync_back()
        except Error:
            cur = None  # another encore is busy; try next time
        if windows and cur:
            usage.record_usage(cur, windows)
            watcher.watch_if_near_limit(windows)
        cur = profiles.current_profile()
        exp = profiles.login_expires_at(profiles.load_meta(cur)) if cur else None
        return status_text(cur, windows, exp)
    except Exception as e:  # never break the status line
        return f"[encore: {type(e).__name__}]"


def status_text(profile, windows, login_expires) -> str:
    text = f"[{profile or '保存していないログイン'}]"
    if windows:
        # Short, so that the weekly numbers are not cut off: "5時間 2%(19:30) 1週間 97%(11/6 6:00)".
        # The time in brackets is when that limit resets.
        text += " " + " ".join(
            f"{STATUS_LABELS.get(w['label'], w['label'])} {w['pct']:.0f}%"
            + (f"({fmt_time_ja(w['resets'])})" if w.get("resets") else "")
            for w in windows)
    if login_expires and login_expires - time.time() < 3 * 86400:
        text += f" · ログインの期限 {fmt_time_ja(login_expires)}（切れたら /login）"
    return text


def fmt_time_ja(epoch) -> str:
    """15:00 today, 11/7 6:00 on another day (short: the status line is narrow)."""
    if not epoch:
        return "?"
    t = datetime.fromtimestamp(epoch)
    if t.date() == datetime.now().date():
        return t.strftime("%H:%M")
    return f"{t.month}/{t.day} {t.hour}:{t.minute:02d}"
