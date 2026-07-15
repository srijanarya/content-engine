import re
import unittest
from pathlib import Path


RUN_SH = Path(__file__).parent / "x" / "cron" / "run.sh"


class EveningTelemetryNonfatalTest(unittest.TestCase):
    def test_only_evening_telemetry_uses_best_effort(self):
        script = RUN_SH.read_text()
        evening = re.search(r"  evening\)\n(?P<body>.*?);;[^\n]*\n", script, re.DOTALL)
        self.assertIsNotNone(evening)
        body = evening.group("body")

        for command in ("x/track_followers.py", "x/pull_analytics.py"):
            self.assertRegex(body, rf"best_effort \$PY {re.escape(command)}")
            self.assertNotRegex(body, rf"step \$PY {re.escape(command)}")

        self.assertRegex(
            body,
            r"step env AUTOPOST_MODE=auto \$PY post_x.py --lane-slug evening-wrap",
        )
        self.assertRegex(body, r"step \$PY monitor/evening_wrap_post.py")

    def test_best_effort_records_and_prints_failures(self):
        script = RUN_SH.read_text()
        helper = re.search(r"best_effort\(\) \{(?P<body>.*?)\}\n", script)
        self.assertIsNotNone(helper)
        self.assertIn('fail_note "$message"', helper.group("body"))
        self.assertIn("printf", helper.group("body"))


if __name__ == "__main__":
    unittest.main()
