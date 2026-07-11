#!/usr/bin/env python3
"""Guards the blockbuster lane (monitor/blockbuster_post.py): factual fields only, no score,
no advisory language, recency order (never growth/score order, which would be a de facto
ranked stock-pick list), and the built context passes the SEBI lint gate.

Run:  python3 test_blockbuster_post.py   (PASS/FAIL, exits nonzero; pytest-discoverable)
"""
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "monitor"))
import blockbuster_post as bp

SCHEMA = """
CREATE TABLE blockbuster_alerts (
    bse_code TEXT, nse_symbol TEXT, company_name TEXT, quarter TEXT, fy_year TEXT,
    revenue_cr REAL, pat_cr REAL, eps REAL, revenue_yoy_growth REAL, pat_yoy_growth REAL,
    eps_growth REAL, blockbuster_score INTEGER, verification_status TEXT, verified_at TEXT
)"""
ROWS = [
    ("500001", "AAA", "Alpha Ltd", "Q1", "FY27", 100.0, 20.0, 5.0, 30.0, 40.0, 10.0,
     90, "screener_verified", "2026-07-10T10:00:00"),
    ("500002", "BBB", "Beta Ltd", "Q1", "FY27", 200.0, 30.0, 8.0, 10.0, 15.0, 5.0,
     55, "screener_verified", "2026-07-12T10:00:00"),
    ("500003", "CCC", "Gamma Ltd", "Q1", "FY27", 50.0, 5.0, 1.0, 5.0, 5.0, 2.0,
     20, "not_verified", "2026-07-13T10:00:00"),  # unverified: must be excluded
]


def _seeded_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(f.name)
    conn.execute(SCHEMA)
    conn.executemany("INSERT INTO blockbuster_alerts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ROWS)
    conn.commit()
    conn.close()
    return Path(f.name)


def test_factual_stocks_excludes_score_and_unverified_orders_by_recency():
    db_path = _seeded_db()
    try:
        sys.path.insert(0, str(bp.AKSH))
        gbr = pytest.importorskip("scripts.generate_blockbuster_report")  # lives in the local AKSH repo (not this one); skip in CI
        with mock.patch.object(gbr, "BLOCKBUSTER_DB", db_path):
            stocks = bp.factual_stocks(limit=8)
    finally:
        db_path.unlink()
    assert len(stocks) == 2, stocks   # Gamma excluded (not verified)
    assert stocks[0]["company_name"] == "Beta Ltd"   # most recently verified first
    assert stocks[1]["company_name"] == "Alpha Ltd"
    for s in stocks:
        assert "blockbuster_score" not in s
        assert set(s) == set(bp.FACTUAL_FIELDS)


def test_build_context_has_no_score_or_advisory_language():
    stocks = [{"company_name": "Alpha Ltd", "quarter": "Q1", "fy_year": "FY27",
               "revenue_cr": 100.0, "pat_cr": 20.0, "eps": 5.0,
               "revenue_yoy_growth": 30.0, "pat_yoy_growth": 40.0, "eps_growth": 10.0,
               "verified_at": "2026-07-10T10:00:00"}]
    ctx = bp.build_context(stocks)
    assert "Alpha Ltd" in ctx and "30.0" in ctx
    for banned in ("blockbuster_score", "Score:", "technical confirmation", "before investing"):
        assert banned.lower() not in ctx.lower(), banned


def test_missing_table_returns_empty_not_crash():
    """Pre-season DB (file exists, no table yet): reader returns [], never raises."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = Path(f.name)
    try:
        sys.path.insert(0, str(bp.AKSH))
        gbr = pytest.importorskip("scripts.generate_blockbuster_report")
        with mock.patch.object(gbr, "BLOCKBUSTER_DB", db_path):
            assert bp.factual_stocks(limit=8) == []
    finally:
        db_path.unlink()


def test_main_exits_zero_when_no_rows():
    """A scheduled off-season probe must exit 0, not false-alarm."""
    with mock.patch.object(bp, "factual_stocks", return_value=[]), \
         mock.patch.object(sys, "argv", ["blockbuster_post.py"]):
        assert bp.main() == 0


def test_escalate_is_idempotent_per_draft():
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(bp, "ESC_DIR", Path(td)):
            draft = Path(td) / "2026-07-11-finance-blockbuster.md"
            bp.escalate(draft)
            bp.escalate(draft)   # re-run overwrites, never duplicates
            escs = list(Path(td).glob("blockbuster-*.md"))
            assert len(escs) == 1, escs
            body = escs[0].read_text()
            assert "Srijan posts manually" in body and draft.name in body


def test_empty_stocks_refuses():
    try:
        bp.build_context([])
    except SystemExit:
        return
    raise AssertionError("empty stock list did not refuse")


def test_context_passes_the_lint_gate():
    stocks = [{"company_name": "Alpha Ltd", "quarter": "Q1", "fy_year": "FY27",
               "revenue_cr": 100.0, "pat_cr": 20.0, "eps": 5.0,
               "revenue_yoy_growth": 30.0, "pat_yoy_growth": 40.0, "eps_growth": 10.0,
               "verified_at": "2026-07-10T10:00:00"}]
    ctx = bp.build_context(stocks)
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
