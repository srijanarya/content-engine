#!/usr/bin/env python3
"""fail_breaker: streak counting, single escalation at threshold, 24h dedupe, reset on success."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fail_breaker as fb


class FailBreakerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        fb.STATE_FILE = root / "state" / "failures.json"
        fb.ESC_DIR = root / "escalations"

    def escalations(self):
        return sorted(fb.ESC_DIR.glob("*.md")) if fb.ESC_DIR.exists() else []

    def test_trip_once_dedupe_and_reset(self):
        fb.record("x-postmarket", 1)
        fb.record("x-postmarket", 1)
        self.assertEqual(len(self.escalations()), 0, "below threshold must not escalate")
        fb.record("x-postmarket", 1)  # 3rd consecutive
        self.assertEqual(len(self.escalations()), 1, "threshold hit must escalate exactly once")
        fb.record("x-postmarket", 1)  # still failing, within 24h
        self.assertEqual(len(self.escalations()), 1, "within 24h must not re-escalate")
        self.assertIn("consecutive failures: **3**", self.escalations()[0].read_text())
        fb.record("x-postmarket", 0)  # recovery resets the streak
        fb.record("x-postmarket", 1)
        fb.record("x-postmarket", 1)
        self.assertEqual(len(self.escalations()), 1, "post-reset streak below threshold")

    def test_jobs_tracked_independently(self):
        for _ in range(3):
            fb.record("ai-world-monitor", 1)
        fb.record("x-postmarket", 1)
        self.assertEqual(len(self.escalations()), 1)
        self.assertIn("ai-world-monitor", self.escalations()[0].name)

    def test_breaker_never_raises_from_main(self):
        sys.argv = ["fail_breaker.py", "job-only-no-rc"]
        self.assertEqual(fb.main(), 0, "bad argv must be swallowed, not crash the lane")


if __name__ == "__main__":
    unittest.main()
