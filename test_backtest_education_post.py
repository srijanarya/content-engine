#!/usr/bin/env python3
"""Guards the backtest-education lane (monitor/backtest_education_post.py):
  - the real VALIDATION_REPORT.md parses to exactly the known index/futures daemons;
  - a daemon name outside the allowlist refuses loudly (a stock-level daemon must never
    silently ride this lane);
  - bare rupee/lot-size figures in the source refuse before ever reaching the LLM prompt;
  - the built context contains no capital figures and stays index/futures-level.

Run:  python3 test_backtest_education_post.py   (PASS/FAIL, exits nonzero; pytest-discoverable)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "monitor"))
import backtest_education_post as bep

REAL_REPORT = bep.AKSH / "permutation_results" / "VALIDATION_REPORT.md"

CLEAN_REPORT = """# Report
| Daemon | Step 1 | Step 2 | p-value | Overall |
|--------|--------|--------|---------|---------|
| VRP Kite (original) | PASS | FAIL | 0.0380 | FAIL |
| ORB | PASS | FAIL | 0.2000 | FAIL |

**Key Finding**: test finding here.
"""


def test_real_report_parses_to_known_allowlisted_daemons():
    if not REAL_REPORT.exists():
        print("SKIP: aksh repo not present")
        return
    daemons = bep.extract_daemons(REAL_REPORT.read_text(encoding="utf-8"))
    names = {d["name"] for d in daemons}
    assert names <= bep.DAEMON_ALLOWLIST, names - bep.DAEMON_ALLOWLIST
    assert len(daemons) == 5, daemons
    original = next(d for d in daemons if d["name"] == "VRP Kite (original)")
    assert original["p_value"] == "0.0380"


def test_unknown_daemon_refuses():
    bad = CLEAN_REPORT.replace("ORB", "Single Stock Momentum Screener")
    try:
        bep.extract_daemons(bad)
    except SystemExit as e:
        assert "not on the" in str(e)
        return
    raise AssertionError("unknown daemon name did not refuse")


def test_banned_capital_language_refuses():
    for term in bep.BANNED_IN_SOURCE:
        try:
            bep.extract_daemons(CLEAN_REPORT + f"\nUse {term} 5.\n")
        except SystemExit as e:
            assert term.split()[0].lower() in str(e).lower(), (term, e)
            continue
        raise AssertionError(f"banned term {term!r} did not refuse")


def test_build_context_is_index_level_and_capital_free():
    # build_context reads from a path; write CLEAN_REPORT to a temp file.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(CLEAN_REPORT)
        path = Path(f.name)
    try:
        ctx = bep.build_context(path)
    finally:
        path.unlink()
    assert "VRP Kite (original)" in ctx
    assert "0.0380" in ctx
    assert "₹" not in ctx
    assert "test finding here" in ctx


def test_context_passes_the_lint_gate():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(CLEAN_REPORT)
        path = Path(f.name)
    try:
        ctx = bep.build_context(path)
    finally:
        path.unlink()
    from compliance.lint import report
    blocks = [v for v in report(ctx) if v["severity"] == "block"]
    assert not blocks, blocks


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
