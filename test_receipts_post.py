#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'x'))
import receipts_post as R


class ReceiptsPostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.drafts = Path(self.tmp.name)
        self.drafts_patch = patch.object(R, "DRAFTS", self.drafts)
        self.drafts_patch.start()
        self.addCleanup(self.drafts_patch.stop)
        self.addCleanup(self.tmp.cleanup)

        self.state = {
            "numbers": {
                "published_total": 188,
                "views_total": 6278,
                "views_7d": 3270,
                "first_publish_date": "2026-06-26",
            },
            "lane_health": [
                {"lane": "facts", "ok": False, "note": "publishing disabled by kill switch"},
                {"lane": "drafts", "ok": False, "note": "27 stale drafts hidden"},
                {"lane": "ai", "ok": True, "note": "ok"},
            ],
        }

    def test_context_uses_real_receipts_and_cta(self):
        context = R.context_for(self.state)
        self.assertIn("188", context)
        self.assertIn("6278", context)
        self.assertIn("3270", context)
        self.assertIn("content-factory-claude-md.html", context)
        self.assertNotIn("9999", context)

    def test_health_line_filters_plumbing_lanes(self):
        line = R.health_line(self.state)
        self.assertEqual(
            line,
            "What broke or is waiting: facts - publishing disabled by kill switch.",
        )
        self.assertNotIn("drafts", line)

    def test_operating_days_only_exists_with_first_publish_date(self):
        missing_date = {**self.state, "numbers": {**self.state["numbers"], "first_publish_date": None}}
        self.assertNotIn("operating_days", R.context_for(missing_date))

        context = R.context_for(self.state)
        expected = (date.today() - date(2026, 6, 26)).days + 1
        self.assertIn(f"operating_days: {expected}", context)

    def test_fetch_state_exits_on_owner_script_failure_and_loads_json(self):
        owner_state = self.drafts / "owner_state.py"
        owner_state.write_text("import sys; sys.exit(3)\n")
        with patch.object(R, "OWNER_STATE", str(owner_state)):
            with self.assertRaises(SystemExit):
                R.fetch_state()

            owner_state.write_text(f"import json; print(json.dumps({self.state!r}))\n")
            self.assertEqual(R.fetch_state(), self.state)

    def test_todays_draft_finds_only_todays_receipts_draft(self):
        self.assertIsNone(R.todays_draft())
        draft = self.drafts / f"{date.today().isoformat()}-x-receipts.md"
        draft.write_text("draft\n")
        self.assertEqual(R.todays_draft(), draft)


if __name__ == "__main__":
    unittest.main()
