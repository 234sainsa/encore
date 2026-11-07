"""What is typed into running sessions after a switch (kept in state.json as "on_switch").
"""
from __future__ import annotations

from . import Error, state

DEFAULTS = {
    "commands": ["/remote-control"],   # typed into every running session after a switch
    # Typed too when the session had stopped at a usage limit. It is one line (Enter sends it).
    "continue_text": ("上限のためアカウントを切り替えました。続きをしてください。"
                      "切り替えの時に動いていたサブエージェントは止まっているかもしれません。"
                      "1 体ずつ確かめて、止まっていたらやり直してください。"),
    "wait_sec": 600,                   # how long to wait for the session to become idle
}


def config() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(state.load().get("on_switch") or {})
    return cfg


def change(action: str, text: list) -> dict:
    """Apply `encore on-switch <action> <text...>`. Returns the config in effect afterwards."""
    if action == "show":
        return config()
    with state.edit() as st:
        cur = config()
        own = dict(st.get("on_switch") or {})
        if action == "set":
            if not text:
                raise Error('give the commands, e.g.  encore on-switch set "/remote-control" "/color blue"')
            own["commands"] = list(text)
        elif action == "add":
            if not text:
                raise Error("give the command to add")
            own["commands"] = list(cur["commands"]) + list(text)
        elif action == "clear":
            own["commands"] = []
        elif action == "continue":
            if not text:
                raise Error('give the text, or "off":  encore on-switch continue "go on"')
            joined = " ".join(text)
            own["continue_text"] = "" if joined.lower() == "off" else joined
        elif action == "reset":
            own = {}
        st["on_switch"] = own
    return config()
