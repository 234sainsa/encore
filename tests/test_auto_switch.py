"""The automatic switch at the usage limit, the StopFailure hook, and the background watcher."""
import io
import json
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

from support import Base
from encore import Error, auto_switch, commands, files, hooks, profiles, state, statusline, \
    switch_signal, usage, watcher


class AutoTests(Base):
    """The automatic switch to another account at the usage limit (usage requests are offline here:
    the numbers come from what encore saw last)."""

    def setUp(self):
        super().setUp()
        for tag, email, name in (("a1", "a@example.com", "a"), ("b1", "b@example.com", "b"),
                                 ("c1", "c@example.com", "c")):
            self.login(tag, email)
            self.quiet(commands.cmd_save, name)
        self.quiet(commands.cmd_use, "a")
        self.offline = mock.patch.object(usage, "fetch_usage", side_effect=Error("offline"))
        self.offline.start()
        self.addCleanup(self.offline.stop)

    def full(self, name, hours):
        usage.record_usage(name, [{"label": "5h", "pct": 100.0, "resets": time.time() + hours * 3600}])

    def test_moves_to_an_account_that_is_not_at_its_limit(self):
        self.assertIsNone(auto_switch.switch_if_at_limit())   # 'a' is not at its limit: stays
        self.assertEqual(profiles.current_profile(), "a")
        self.full("a", 2)
        self.full("b", 1)
        self.assertEqual(auto_switch.switch_if_at_limit(), "c")  # 'c' can be used now
        self.assertEqual(profiles.current_profile(), "c")
        self.assertEqual(files.read_json(switch_signal.path())["to"], "c")  # running sessions are told

    def test_every_account_at_its_limit_moves_to_the_first_reset(self):
        self.full("a", 3)
        self.full("b", 1)
        self.full("c", 2)
        self.assertEqual(auto_switch.switch_if_at_limit(), "b")
        self.assertIsNone(auto_switch.switch_if_at_limit())   # 'b' resets first: no further switch
        self.assertEqual(profiles.current_profile(), "b")

    def test_off_does_nothing(self):
        self.quiet(commands.cmd_auto, False, None)
        self.full("a", 2)
        self.assertIsNone(auto_switch.switch_if_at_limit(limit_hit=True))
        self.assertEqual(profiles.current_profile(), "a")

    def test_stop_failure_hook_switches_without_numbers(self):
        payload = json.dumps({"hook_event_name": "StopFailure", "error": "rate_limit"})
        with mock.patch("sys.stdin", io.StringIO(payload)):
            hooks.stop_failure()
        self.assertEqual(profiles.current_profile(), "b")  # no numbers for 'a', but it did stop at the limit

    def render(self, pct):
        data = {"rate_limits": {"five_hour": {"used_percentage": pct, "resets_at": time.time() + 60}}}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(data))), redirect_stdout(io.StringIO()):
            statusline.run()

    def test_statusline_starts_one_watcher_near_the_limit(self):
        started = []
        with mock.patch.object(watcher, "start", lambda: started.append(1)):
            self.render(80)
            self.render(99)
            self.render(99)  # the watcher is alive: no second one
        self.assertEqual(started, [1])
        self.assertGreater(state.load()["auto"]["watch_until"], time.time() + 25 * 60)

    def stop_watching(self, _sec):
        with state.edit() as s:
            s["auto"]["watch_until"] = 0  # the status line stopped seeing high usage

    def test_watcher_switches_when_anthropic_says_100(self):
        # The status line said 99% (numbers of the last request that worked); Anthropic says 100%.
        with state.edit() as st:
            st["auto"]["watch_until"] = time.time() + 600
        self.full("a", 30)
        with mock.patch.object(watcher.time, "sleep", self.stop_watching):
            watcher.run()
        self.assertEqual(profiles.current_profile(), "b")

    def test_watcher_does_nothing_below_the_limit(self):
        with state.edit() as st:
            st["auto"]["watch_until"] = time.time() + 600
        usage.record_usage("a", [{"label": "7d", "pct": 99.0, "resets": time.time() + 3600}])
        with mock.patch.object(watcher.time, "sleep", self.stop_watching):
            watcher.run()
        self.assertEqual(profiles.current_profile(), "a")


if __name__ == "__main__":
    unittest.main()
