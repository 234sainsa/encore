# encore

[日本語](README.ja.md)

Claude Code switches to your next account by itself when it hits the usage limit.

Save your Claude accounts once. From then on, when Claude Code stops at the usage limit, encore:

- **moves Claude Code to the account that can be used first.** An account that is not at its limit, or, if all of them are, the one whose limit resets first.
- **moves every open session along.** Each running Claude Code session uses the new account from its next request. No restart, no sign-in.
- **gets the stopped session going again.** The session that stopped at the limit is asked to continue and to restart stopped subagents. Remote Control is turned back on. (Windows)

You do not have to do anything. There is nothing to look after either: when a login expires, a plain `/login` in Claude Code is enough, and encore saves the new login. The status line shows the account in use and its 5-hour and weekly usage.

## Requirements

- Python 3.9+, standard library only.
- Tested on Windows. macOS is untested.

## Install

```sh
pipx install git+https://github.com/234sainsa/encore
encore setup
```

Without pipx: `python encore.py setup`.

## Get started

In `encore setup`:

1. **1** saves the current login as a profile (e.g. `main`).
2. **2** adds another account (signs in in the browser; your current login stays). Add as many as you have.
3. **3** installs the status line and hooks. The automatic switch needs them.

Then restart Claude Code. That is all.

## Commands

You do not need these for the automatic switch.

| Command | What it does |
|---|---|
| `encore use <name>` | Switch to a profile now |
| `encore use --soonest` | Switch now to the account that can be used first |
| `encore list` | List profiles (`*` = in use) |
| `encore usage [name]` | Show the 5-hour and weekly usage |
| `encore add <name>` / `save <name>` | Add another account / save the current login |
| `encore auto off` / `auto on [--threshold <percent>]` | Turn the automatic switch off / on (on by default). By default it switches when Claude Code really stops: an account can still be used for a while at 100%. With `--threshold 90` it switches early, at 90%. |
| `encore on-switch ...` | Change what is typed into sessions after a switch |
| `encore install` / `uninstall` | Add / remove the status line and hooks |
| `encore rename <old> <new>` / `remove <name>` | Rename / delete a profile |

## After a switch

Running sessions use the new login from their next request. No restart needed.

On Windows, encore also types into each session that was running before the switch (right after the switch, in the background; each step is written to `~/.encore/events.log`):

- `/remote-control` (Remote Control disconnects when the account changes).
- If the session had stopped at the usage limit: a message asking Claude to continue and to restart subagents that stopped. Only this message reaches Claude.

Anything you were typing is kept. Change what is typed with `encore on-switch set ...`, `on-switch continue "<text>"`, or `on-switch clear`.

## Notes

- A saved login lasts about one month. When it expires, run `/login` in Claude Code with the same account; encore keeps the new login by itself. (`encore use` to an expired profile offers the sign-in right away.)
- Data is stored in `~/.encore`.

## Upgrading from 1.0

Versions before 1.1 had another name. Install 1.1 and run `encore install` once: it moves your saved profiles to `~/.encore` and replaces the old status line and hooks. Then restart Claude Code.

## License

MIT

encore is an independent project. It is not made, endorsed or supported by Anthropic. Claude and Claude Code are trademarks of Anthropic, PBC.
