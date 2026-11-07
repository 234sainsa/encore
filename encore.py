#!/usr/bin/env python3
"""Launcher: `python encore.py <command>` runs the encore package in src/.

The command lines that `encore install` writes into Claude Code's settings.json point at this
file, so it stays at the top of the checkout. Standard library only. Python 3.9+.
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
# This file is itself named encore.py and its folder is sys.path[0]: take that folder out so
# that `import encore` finds the package in src/ and not this launcher.
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != _here]
sys.path.insert(0, os.path.join(_here, "src"))

from encore.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
