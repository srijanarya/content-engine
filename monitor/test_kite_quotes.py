#!/usr/bin/env python3
"""kite_quotes: on-demand reauth retry when the cached access token has gone stale.

Root cause under test: the trading repo's kite-daily-auth launchd job (08:15 + 12:30) misses its 08:15
slot whenever this Mac is still asleep/booting then -- routine most mornings (`last reboot`). The 12:30
backup lands after the premarket lane's 9-11 IST window closes, so every premarket retry in that window
used to fail closed on TokenException with no chance to recover same-day. fetch_quotes() now retries once
through an on-demand reauth call; these tests exercise that control flow without touching any real
credentials or the network.
"""
import sys, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import kite_quotes as kq
from kiteconnect.exceptions import TokenException


class _FakeKite:
    """First .quote() call raises TokenException; the retry after reauth succeeds."""

    calls = 0

    def __init__(self, api_key):
        pass

    def set_access_token(self, tok):
        pass

    def quote(self, syms):
        _FakeKite.calls += 1
        if _FakeKite.calls == 1:
            raise TokenException("Incorrect `api_key` or `access_token`.")
        return _make_quote_payload()


def _make_quote_payload():
    q = {
        "NSE:NIFTY 50": {"last_price": 24000.0, "net_change": 100.0, "ohlc": {"close": 23900.0},
                          "instrument_token": 256265},
        "NSE:INDIA VIX": {"last_price": 13.5},
    }
    for sym in kq.SECTORS.values():
        q[f"NSE:{sym}"] = {"last_price": 100.0, "net_change": 1.0, "ohlc": {"close": 99.0}}
    return q


class ReauthRetryTest(unittest.TestCase):
    def setUp(self):
        _FakeKite.calls = 0
        self.addCleanup(patch.stopall)
        patch.object(kq, "_load_creds", return_value=("key", "tok")).start()
        patch("kiteconnect.KiteConnect", _FakeKite).start()

    def test_stale_token_recovers_via_reauth_then_succeeds(self):
        with patch.object(kq, "_reauth", return_value=True) as reauth:
            out = kq.fetch_quotes()
        reauth.assert_called_once()
        self.assertEqual(_FakeKite.calls, 2, "must retry the quote exactly once after reauth")
        self.assertEqual(out["nifty_close"], 24000.0)

    def test_stale_token_reauth_failure_fails_closed(self):
        with patch.object(kq, "_reauth", return_value=False) as reauth:
            with self.assertRaises(kq.KiteUnavailable):
                kq.fetch_quotes()
        reauth.assert_called_once()
        self.assertEqual(_FakeKite.calls, 1, "must not retry the quote if reauth itself failed")

    def test_non_token_failure_never_calls_reauth(self):
        class _NetworkFailKite(_FakeKite):
            def quote(self, syms):
                raise RuntimeError("network unreachable")

        with patch("kiteconnect.KiteConnect", _NetworkFailKite):
            with patch.object(kq, "_reauth") as reauth:
                with self.assertRaises(kq.KiteUnavailable):
                    kq.fetch_quotes()
                reauth.assert_not_called()


if __name__ == "__main__":
    unittest.main()
