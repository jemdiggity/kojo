import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kojo.codex import enforce, weekly_snapshot, QuotaStop, overrides


class QuotaTests(unittest.TestCase):
    cfg = {"weekly_resets_at": 123, "weekly_remaining_floor": 78}

    def snapshot(self, n):
        return {"remaining_percent": n, "resets_at": 123}

    def test_used_is_not_remaining(self):
        data = {
            "rateLimitsByLimitId": {
                "codex": {
                    "primary": {
                        "usedPercent": 12,
                        "windowDurationMins": 10080,
                        "resetsAt": 123,
                    }
                }
            }
        }
        self.assertEqual(weekly_snapshot(data)["remaining_percent"], 88)

    def test_refuses_floor_and_reserves_headroom(self):
        for percent in (78, 77, 79):
            with self.assertRaises(QuotaStop):
                enforce(self.snapshot(percent), self.cfg, [], True)
        enforce(self.snapshot(80), self.cfg, [], True)

    def test_recent_large_drop_raises_buffer(self):
        history = [self.snapshot(85), self.snapshot(82)]
        with self.assertRaises(QuotaStop):
            enforce(self.snapshot(81), self.cfg, history, True)

    def test_after_run_stops_at_floor(self):
        with self.assertRaises(QuotaStop):
            enforce(self.snapshot(78), self.cfg, [], False)
        enforce(self.snapshot(79), self.cfg, [], False)

    def test_missing_usage_and_reset_fail_closed(self):
        for data in (
            {},
            {"rateLimitsByLimitId": {}},
            {
                "rateLimits": {
                    "primary": {"usedPercent": None, "windowDurationMins": 10080}
                }
            },
        ):
            with self.assertRaises(QuotaStop):
                weekly_snapshot(data)
        with self.assertRaises(QuotaStop):
            enforce({"remaining_percent": 100, "resets_at": 124}, self.cfg, [], True)

    def test_exec_ignores_host_mcp_and_disables_memory(self):
        args = overrides(ignore_user_config=True)
        self.assertIn("memories.use_memories=false", args)
        self.assertIn("features.skip_host_skill_discovery=true", args)
        self.assertFalse(any(s.startswith("mcp_servers.") for s in args))

    def test_symlinked_skills_are_explicitly_disabled_without_user_config(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            target = Path(td) / "elsewhere/linked"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("canary")
            (home / ".agents/skills").mkdir(parents=True)
            (home / ".agents/skills/canary").symlink_to(
                target, target_is_directory=True
            )
            with patch("kojo.codex.Path.home", return_value=home):
                args = overrides(ignore_user_config=True)
            configs = [a for a in args if a.startswith("skills.config=")]
            self.assertIn(str(target / "SKILL.md"), configs[0])
            self.assertIn("enabled=false", configs[0])


if __name__ == "__main__":
    unittest.main()
