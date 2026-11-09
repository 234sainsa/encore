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
    if not isinstance(st.get("auto"), dict):
        st["auto"] = {"enabled": True, "threshold": 100}  # on unless the person turns it off
    st.setdefault("usage", {})
    return st


@contextmanager
def edit():
    """Read state.json, let the block change it, then write it back.

    A `return` inside the block still writes; check first with load() when nothing may change."""
    st = load()
    yield st
    files.write_json(path(), st)
