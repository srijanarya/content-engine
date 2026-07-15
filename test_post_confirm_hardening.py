import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent / "x"))
import reconcile_posting as ledger


class FakeBrowser:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def confirm_thread(self, tweets):
        self.calls.append(("thread", tweets))
        return self.result

    def confirm_reply(self, target, text):
        self.calls.append(("reply", target, text))
        return self.result


class PostConfirmationHardeningTests(unittest.TestCase):
    def pending(self, attempts=1):
        return {"unconfirmed": {
            "row": {"kind": "thread", "tweets": ["A distinct opening line"], "attempts": attempts}
        }}

    def test_reconcile_moves_confirmed_thread_to_posted(self):
        log = self.pending()
        browser = FakeBrowser({"state": "posted", "url": "https://x.com/me/status/1"})

        resolved = ledger.reconcile(log, browser)

        self.assertEqual(resolved, ["row: posted"])
        self.assertNotIn("row", log["unconfirmed"])
        self.assertEqual(log["posted"]["row"]["url"], "https://x.com/me/status/1")
        self.assertEqual(browser.calls, [("thread", ["A distinct opening line"])])

    def test_reconcile_moves_missing_thread_to_failed(self):
        log = self.pending(attempts=1)

        resolved = ledger.reconcile(log, FakeBrowser({"state": "failed"}))

        self.assertEqual(resolved, ["row: failed"])
        self.assertNotIn("row", log["unconfirmed"])
        self.assertEqual(log["failed"]["row"]["attempts"], 1)
        self.assertNotIn("poisoned", log["failed"]["row"])

    def test_reconcile_ambiguity_leaves_row_unconfirmed(self):
        log = self.pending()
        messages = []

        resolved = ledger.reconcile(log, FakeBrowser({"state": "ambiguous", "reason": "timeline incomplete"}), messages.append)

        self.assertEqual(resolved, ["row: unconfirmed"])
        self.assertIn("row", log["unconfirmed"])
        self.assertNotIn("posted", log)
        self.assertIn("timeline incomplete", messages[0])

    def test_third_failed_attempt_poisoned_and_cannot_retry(self):
        log = {}
        for attempt in range(1, 4):
            self.assertTrue(ledger.start_attempt(log, "row", {"kind": "reply", "target": "https://x.com/a/status/1", "text": "reply"}))
            self.assertEqual(log["unconfirmed"]["row"]["attempts"], attempt)
            ledger.reconcile(log, FakeBrowser({"state": "failed"}))

        self.assertTrue(log["failed"]["row"]["poisoned"])
        self.assertFalse(ledger.start_attempt(log, "row", {"kind": "reply", "target": "https://x.com/a/status/1", "text": "reply"}))


if __name__ == "__main__":
    unittest.main()
