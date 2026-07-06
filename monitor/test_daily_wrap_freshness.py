#!/usr/bin/env python3
"""Guards the 2026-06-23 stale-data bug: the daily wrap must never publish old or pre-close numbers.

Run:  python3 monitor/test_daily_wrap_freshness.py   (exits nonzero on failure; pytest-discoverable)
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
dm = pytest.importorskip("daily_market_post")  # local-only module (gitignored); skip in CI

NOW = datetime(2026, 6, 23, 16, 0, 0)  # today, 4pm IST = post-close


def test_stale_date_refused():
    # the actual bug: May-12 data from the dead private file, stamped today
    r = dm.fresh_or_reason({"date": "2026-05-12", "generated_at": "2026-05-12T15:48:00"}, NOW)
    assert r and "stale" in r, r


def test_preopen_sample_refused():
    # a 09:06 pre-open snapshot is not a "wrap" of the completed session
    r = dm.fresh_or_reason({"date": "2026-06-23", "generated_at": "2026-06-23T09:06:54"}, NOW)
    assert r and "pre-close" in r, r


def test_fresh_postclose_accepted():
    r = dm.fresh_or_reason({"date": "2026-06-23", "generated_at": "2026-06-23T15:40:00"}, NOW)
    assert r is None, r


def test_missing_generated_at_refused():
    r = dm.fresh_or_reason({"date": "2026-06-23"}, NOW)
    assert r and "generated_at" in r, r


def test_dead_private_file_is_not_a_source():
    # regression: the frozen trading artifact must never be a fallback source again
    assert not any("aksh_backtesting_trading" in p for p in dm.REGIME_PATHS), dm.REGIME_PATHS
    assert any("regime_safe.json" in p for p in dm.REGIME_PATHS), dm.REGIME_PATHS


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1; print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
