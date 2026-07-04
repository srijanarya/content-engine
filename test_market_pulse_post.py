#!/usr/bin/env python3
"""Guards the Market Pulse lane (monitor/market_pulse_post.py):
  - deterministic texts stay aggregate/sector-level, em-dash-free, and inside X's 280 limit;
  - a snapshot that somehow carries a per-stock directional string is BLOCKED by the same
    compliance lint the script gates on (the lane is deterministic, so a block = leaked field);
  - stale snapshots and thin breadth refuse loudly instead of posting yesterday's tape.

Run:  python3 test_market_pulse_post.py   (prints PASS/FAIL, exits nonzero; pytest-discoverable)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "monitor"))
import market_pulse_post as mpp

SNAP = {
    "as_of": "2026-07-04",
    "breadth": {"sectors": [
        {"sector": "NIFTY IT", "pct_above_50dema": 35.0},
        {"sector": "NIFTY BANK", "pct_above_50dema": 83.0},
        {"sector": "NIFTY PHARMA", "pct_above_50dema": 61.0},
        {"sector": "NIFTY METAL", "pct_above_50dema": 13.0},
        {"sector": "NIFTY AUTO", "pct_above_50dema": 72.0},
        {"sector": "NIFTY 500", "pct_above_50dema": 55.0},   # broad index: must be excluded
    ]},
    "rrg": {"sectors": [
        {"sector": "NIFTY BANK", "q": "Leading"},
        {"sector": "NIFTY PHARMA", "q": "Improving"},
        {"sector": "NIFTY IT", "q": "Weakening"},
        {"sector": "NIFTY METAL", "q": "Lagging"},
        {"sector": "NIFTY MIDCAP 100", "q": "Leading"},      # broad index: must be excluded
    ]},
    "macro": {"series": [
        {"yahoo": "INR=X", "close": 95.20, "pct_change": -0.23},
        {"yahoo": "BZ=F", "close": 72.13, "pct_change": 0.46},
        {"yahoo": "^GSPC", "close": 7483.24, "pct_change": 0.0},
        {"yahoo": "^N225", "close": 1.0, "pct_change": 9.9},  # not free-tier: must not appear
    ]},
}


def test_texts_are_aggregate_and_within_limits():
    newsletter, thread = mpp.build_texts(SNAP)
    assert "3 of 5 NIFTY sectors" in newsletter, newsletter          # 500 excluded from count
    assert "Bank (83%)" in newsletter and "Metal (13%)" in newsletter
    assert "Leading: Bank" in newsletter and "Midcap" not in newsletter
    assert "USD/INR 95.20" in newsletter and "N225" not in newsletter
    for i, t in enumerate(thread.split("\n\n"), 1):
        assert len(t) <= 280, f"tweet {i} is {len(t)} chars"
    assert "—" not in newsletter + thread, "em-dash in output (house voice rule)"


def test_texts_pass_the_lint_gate():
    newsletter, thread = mpp.build_texts(SNAP)
    from compliance.lint import report
    blocks = [v for v in report(newsletter + "\n" + thread) if v["severity"] == "block"]
    assert not blocks, blocks


def test_doctored_per_stock_row_is_blocked_by_lint():
    """If aksh's snapshot ever leaks a per-stock directional string where a sector name
    belongs, the SAME lint call the script gates on must return a BLOCK."""
    bad = {**SNAP, "breadth": {"sectors": [
        {"sector": "STRONG BUY RELIANCE", "pct_above_50dema": 99.0},
        *SNAP["breadth"]["sectors"],
    ]}}
    newsletter, thread = mpp.build_texts(bad)
    from compliance.lint import report
    blocks = [v for v in report(newsletter + "\n" + thread) if v["severity"] == "block"]
    assert blocks, "per-stock directional text passed the lint gate"


def test_thin_breadth_refuses():
    try:
        mpp.breadth_read({"sectors": SNAP["breadth"]["sectors"][:2]})
    except SystemExit:
        return
    raise AssertionError("thin breadth (<5 rows) did not refuse")


def test_stale_snapshot_refuses():
    if not (mpp.AKSH / "src" / "intelligence" / "market_pulse").exists():
        print("SKIP stale-snapshot check: aksh repo not present")
        return
    try:
        mpp.load_snapshot("1999-01-01")
    except SystemExit as e:
        assert "stale" in str(e)
        return
    raise AssertionError("stale snapshot did not refuse")


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted({k: v for k, v in globals().items()
                            if k.startswith("test_") and callable(v)}.items()):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
