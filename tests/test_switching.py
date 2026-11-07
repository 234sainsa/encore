"""Profiles and the switch: save, use, rename, use --soonest, and the cleanup of old data."""
import time
import unittest
from unittest import mock

from support import Base, oauth
from encore import Error, claude_settings, commands, files, paths, profiles, state, usage


class SwitchTests(Base):
    def setup_two(self):
        self.login("a1", "a@example.com", extra={"mcpOAuth": {"server": "keep-me"}})
        self.quiet(commands.cmd_save, "a")
        self.login("b1", "b@example.com")
        self.quiet(commands.cmd_save, "b")

    def test_use_swaps_only_the_login(self):
        self.setup_two()
        self.quiet(commands.cmd_use, "a")
        live = self.live()
        self.assertEqual(live["claudeAiOauth"]["accessToken"], "access-a1")
        self.assertEqual(live["mcpOAuth"], {"server": "keep-me"})
        cj = files.read_json(self.cfg / ".claude.json")
        self.assertEqual(cj["oauthAccount"]["emailAddress"], "a@example.com")
        self.assertEqual(cj["numStartups"], 7)
        self.assertEqual(profiles.current_profile(), "a")

    def test_refreshed_tokens_are_written_back_before_switching(self):
        self.setup_two()
        self.quiet(commands.cmd_use, "a")
        # Claude Code refreshes the token of 'a' while it is live.
        creds = self.live()
        creds["claudeAiOauth"] = oauth("a2")
        files.write_json(self.cfg / ".credentials.json", creds)
        self.quiet(commands.cmd_use, "b")
        self.assertEqual(profiles.load_secret("a")["claudeAiOauth"]["refreshToken"], "refresh-a2")
        self.quiet(commands.cmd_use, "a")
        self.assertEqual(self.live()["claudeAiOauth"]["refreshToken"], "refresh-a2")

    def test_rename_keeps_login_and_references(self):
        self.setup_two()
        usage.record_usage("a", [{"label": "5h", "pct": 10.0, "resets": None}])
        self.quiet(commands.cmd_rename, "a", "work")
        self.assertEqual(profiles.profile_names(), ["b", "work"])
        self.assertEqual(profiles.load_meta("work")["name"], "work")
        self.assertEqual(profiles.load_secret("work")["claudeAiOauth"]["accessToken"], "access-a1")
        self.assertIn("work", state.load()["usage"])
        self.quiet(commands.cmd_use, "work")
        self.assertEqual(profiles.current_profile(), "work")
        with self.assertRaises(Error):
            commands.cmd_rename("b", "work")

    def test_save_refuses_the_same_account_twice(self):
        self.setup_two()
        with self.assertRaises(Error):
            commands.cmd_save("again")

    def test_use_soonest_picks_the_first_reset(self):
        now = time.time()
        self.setup_two()
        self.login("c1", "c@example.com")
        self.quiet(commands.cmd_save, "c")
        usage.record_usage("b", [{"label": "5h", "pct": 100.0, "resets": now + 3600}])
        usage.record_usage("c", [{"label": "5h", "pct": 100.0, "resets": now + 7200}])
        usage.record_usage("a", [{"label": "7d", "pct": 100.0, "resets": now + 86400}])
        with mock.patch.object(usage, "fetch_usage", side_effect=Error("offline")):
            self.quiet(commands.cmd_use_soonest)
        self.assertEqual(profiles.current_profile(), "b")
        usage.record_usage("a", [{"label": "5h", "pct": 40.0, "resets": now + 600}])  # a is usable now
        with mock.patch.object(usage, "fetch_usage", side_effect=Error("offline")):
            self.quiet(commands.cmd_use_soonest)
        self.assertEqual(profiles.current_profile(), "a")

    def test_leftovers_of_the_old_api_key_feature_are_cleaned_up(self):
        self.setup_two()
        profiles.save_profile("api", {"name": "api", "kind": "apikey"}, {"apiKey": "sk-ant-x"})
        files.write_json(paths.settings_path(), {"apiKeyHelper": "encore api-key", "theme": "dark"})
        files.write_json(paths.home() / "state.json", {"api_active": "api", "usage": {},
                                                       "auto": {"enabled": False, "fallback": "api"}})
        self.assertEqual(profiles.profile_names(), ["a", "b"])
        self.assertEqual(state.load()["auto"], {"enabled": True, "threshold": 100})
        with self.assertRaises(Error):
            commands.cmd_use("api")
        self.quiet(commands.cmd_use, "a")
        self.assertEqual(claude_settings.load(), {"theme": "dark"})
        # Someone else's apiKeyHelper stays.
        files.write_json(paths.settings_path(), {"apiKeyHelper": "my-own-helper"})
        self.quiet(commands.cmd_use, "b")
        self.assertEqual(claude_settings.load()["apiKeyHelper"], "my-own-helper")


class StateTests(Base):
    def test_edit_writes_back_but_not_when_the_block_fails(self):
        with state.edit() as st:
            st["on_switch"] = {"commands": ["/x"]}
        self.assertEqual(state.load()["on_switch"], {"commands": ["/x"]})
        with self.assertRaises(Error):
            with state.edit() as st:
                st["on_switch"] = {}
                raise Error("stop")
        self.assertEqual(state.load()["on_switch"], {"commands": ["/x"]})


if __name__ == "__main__":
    unittest.main()
