import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


X_DIR = Path(__file__).parent / "x"
sys.path.insert(0, str(X_DIR))
import pull_analytics as analytics


FIXTURE = X_DIR / "fixtures" / "account-analytics-zero.json"


class PullAnalyticsCaptureTest(unittest.TestCase):
    def test_zero_result_saves_raw_html_fixture(self):
        captured = json.loads(FIXTURE.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = analytics.save_zero_capture(
                captured,
                debug_dir=Path(tmp),
                now=datetime(2026, 7, 15, 20, 5, 6),
            )

            self.assertEqual(path.name, "account-analytics-zero-20260715-200506.html")
            self.assertEqual(path.read_text(), captured["html"])


if __name__ == "__main__":
    unittest.main()
