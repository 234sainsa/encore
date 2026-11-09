"""state.json: the automatic switch's settings, the last usage numbers seen, the on-switch settings.

Read it with load(). Change it with `with state.edit() as st: ...`, which writes it back when the
block ends (and not when the block raises).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from . import files, paths


def path() -> Path:
    return paths.home() / "state.json"


def load() -> dict:
    st = files.read_json(path(), {}) or {}
    auto = st.get("auto")
    if not isinstance(auto, dict) or "fallback" in auto:
        # Older versions used "auto" for a move to an API key (removed). Now it is the automatic
        # switch to another account, and it is on unless the person turns it off.
        st["auto"] = {"enabled": True, "threshold": 100}
    st.pop("api_active", None)
    st.setdefault("usage", {})
    return st


@contextmanager
def edit():
    """Read state.json, let the block change it, then write it back.

    A `return` inside the block still writes; check first with load() when nothing may change."""
    st = load()
    yield st
    files.write_json(path(), st)
