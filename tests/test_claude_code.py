"""What encore puts into Claude Code: the status line, and settings.json (install, uninstall)."""
import io
import json
import os
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from support import Base
from encore import claude_settings, commands, files, paths, profiles, state, statusline


class ReloginTests(Base):
    def test_login_inside_claude_code_is_kept_in_the_profile(self):
        self.login("a1", "a@example.com")
        self.quiet(commands.cmd_save, "a")
        self.login("a2", "a@example.com")  # the login expired; /login in Claude Code, same account
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("{}")), redirect_stdout(out):
            statusline.run()
        self.assertEqual(profiles.load_secret("a")["claudeAiOauth"], self.live()["claudeAiOauth"])

    def test_statusline_warns_before_the_login_expires(self):
        self.login("a1", "a@example.com")
        self.quiet(commands.cmd_save, "a")
        meta = profiles.load_meta("a")
        meta["loginExpiresAt"] = int((time.time() + 86400) * 1000)
        profiles.save_profile("a", meta, profiles.load_secret("a"))
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("{}")), redirect_stdout(out), \
                mock.patch.object(profiles, "sync_back", lambda: "a"):
            statusline.run()
        self.assertIn("ログインの期限", out.getvalue())


class StatusLineTests(Base):
    def test_statusline_shows_usage_in_words(self):
        self.login("a1", "a@example.com")
        self.quiet(commands.cmd_save, "a")
        data = {"rate_limits": {"seven_day": {"used_percentage": 94, "resets_at": time.time() + 3 * 86400}}}
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(data))), redirect_stdout(out):
            statusline.run()
        self.assertRegex(out.getvalue(), r"^\[a\] 1週間 94%\(\d{1,2}/\d{1,2} \d{1,2}:\d\d\)")


class InstallTests(Base):
    def test_install_keeps_existing_status_line_and_hooks(self):
        files.write_json(paths.settings_path(), {
            "statusLine": {"type": "command", "command": "my-line"},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]},
            "theme": "dark"})
        self.quiet(commands.cmd_install)
        self.quiet(commands.cmd_install)  # twice: no duplicates
        s = claude_settings.load()
        self.assertEqual(s["statusLine"]["command"], "encore statusline")
        self.assertEqual(len(s["hooks"]["StopFailure"]), 1)
        self.assertEqual(len(s["hooks"]["SessionStart"]), 1)
        fc = s["hooks"]["FileChanged"][0]
        self.assertEqual(fc["matcher"], "switched.json")
        self.assertTrue(fc["hooks"][0]["async"] and fc["hooks"][0]["asyncRewake"])
        self.assertEqual(state.load()["statusline_then"], "my-line")
        self.quiet(commands.cmd_uninstall)
        s = claude_settings.load()
        self.assertEqual(s["statusLine"]["command"], "my-line")
        self.assertEqual(s["hooks"], {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]})
        self.assertEqual(s["theme"], "dark")

    def test_only_command_lines_that_run_encore_are_ours(self):
        self.assertTrue(claude_settings.is_ours('"C:/py.exe" "C:/src/encore/encore.py" statusline'))
        self.assertTrue(claude_settings.is_ours('"/usr/bin/python3" -m encore hook-stop-failure'))
        self.assertTrue(claude_settings.is_ours(f'"py" "C:/src/{paths.OLD_NAME}/{paths.OLD_NAME}.py" statusline'))
        self.assertFalse(claude_settings.is_ours("python encore-backup.py"))
        self.assertFalse(claude_settings.is_ours("notify --title encore done"))

    def test_install_replaces_the_entries_of_the_old_name_and_keeps_the_rest(self):
        old = f'"py" "C:/src/{paths.OLD_NAME}/{paths.OLD_NAME}.py"'
        other = {"hooks": [{"type": "command", "command": "python encore-backup.py"}]}
        files.write_json(paths.settings_path(), {
            "statusLine": {"type": "command", "command": f"{old} statusline", "padding": 0},
            "hooks": {"StopFailure": [{"matcher": "rate_limit",
                                       "hooks": [{"type": "command", "command": f"{old} hook-stop-failure"}]},
                                      other]}})
        self.quiet(commands.cmd_install)
        s = claude_settings.load()
        self.assertEqual(s["statusLine"]["command"], "encore statusline")
        self.assertNotIn("statusline_then", state.load())
        self.assertEqual(s["hooks"]["StopFailure"][0], other)
        self.assertEqual(s["hooks"]["StopFailure"][1]["hooks"][0]["command"], "encore hook-stop-failure")
        self.assertEqual(len(s["hooks"]["StopFailure"]), 2)
        self.assertNotIn(paths.OLD_NAME, json.dumps(s))


class OldFolderTests(Base):
    def test_old_folder_is_used_until_install_moves_it(self):
        root = Path(self.tmp.name) / "user"
        old = root / f".{paths.OLD_NAME}"
        old.mkdir(parents=True)
        (old / "state.json").write_text('{"auto": {"enabled": false}}', encoding="utf-8")
        env = dict(os.environ)
        env.pop("ENCORE_HOME")
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("pathlib.Path.home", return_value=root):
            self.assertEqual(paths.home(), old)
            self.quiet(commands.cmd_install)
            self.assertEqual(paths.home(), root / ".encore")
            self.assertFalse(old.exists())
            self.assertFalse(state.load()["auto"]["enabled"])


if __name__ == "__main__":
    unittest.main()
