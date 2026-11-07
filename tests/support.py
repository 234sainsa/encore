"""Shared by the tests: throwaway folders for Claude Code and encore, and fake logins.

The tests never touch the real Claude Code login, never start the background watcher, and never
reach the network.

Run: python -m unittest discover -s tests
"""
import io
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from encore import background, credentials, files, watcher  # noqa: E402


def oauth(tag, exp_hours=8):
    now_ms = int(time.time() * 1000)
    return {"accessToken": f"access-{tag}", "refreshToken": f"refresh-{tag}",
            "expiresAt": now_ms + exp_hours * 3600_000,
            "refreshTokenExpiresAt": now_ms + 30 * 86400_000,
            "scopes": ["user:inference"], "subscriptionType": "max"}


def account(email, org="org-1"):
    return {"accountUuid": "u-" + email, "emailAddress": email, "organizationUuid": org,
            "organizationName": "Org"}


def no_network(*_a, **_k):
    raise AssertionError("a test tried to reach the network")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cfg = root / "claude"
        self.cfg.mkdir()
        self.env = mock.patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": str(self.cfg),
            "ENCORE_HOME": str(root / "encore"),
            "ENCORE_COMMAND": "encore",
        })
        self.env.start()
        # Tests use the file store even on macOS.
        self.store = mock.patch.object(credentials, "live_store", lambda: credentials.FileStore())
        self.store.start()
        # Never start a real background watcher from a test.
        no_watcher = mock.patch.object(watcher, "start", lambda: None)
        no_watcher.start()
        self.addCleanup(no_watcher.stop)
        # Never start any other background command either (a switch starts `after-switch` on
        # Windows): record it in self.started instead.
        self.started = []
        no_background = mock.patch.object(background, "start", self.started.append)
        no_background.start()
        self.addCleanup(no_background.stop)
        # Never ask Anthropic: a test that does fails loudly.
        offline = mock.patch("urllib.request.urlopen", no_network)
        offline.start()
        self.addCleanup(offline.stop)

    def tearDown(self):
        self.store.stop()
        self.env.stop()
        self.tmp.cleanup()

    def login(self, tag, email, extra=None):
        """Pretend Claude Code logged in (as `/login` would)."""
        creds = files.read_json(self.cfg / ".credentials.json", {}) or {}
        creds["claudeAiOauth"] = oauth(tag)
        if extra:
            creds.update(extra)
        files.write_json(self.cfg / ".credentials.json", creds)
        cj = files.read_json(self.cfg / ".claude.json", {}) or {}
        cj["oauthAccount"] = account(email)
        cj.setdefault("numStartups", 7)
        files.write_json(self.cfg / ".claude.json", cj)

    def live(self):
        return files.read_json(self.cfg / ".credentials.json")

    def quiet(self, fn, *a):
        with redirect_stdout(io.StringIO()):
            return fn(*a)
