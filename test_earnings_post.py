#!/usr/bin/env python3
"""Tests for the earnings lane: format correctness, math, and the value gate.

Run:  python3 test_earnings_post.py   (exits nonzero on failure; pytest-discoverable)
"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monitor.earnings_post import (
    _fiscal_label, _period_str, _pct_delta, _build_thread, _build_record,
)
from compliance.earnings_check import verify_earnings
from datetime import date

# ── fixtures ──────────────────────────────────────────────────────────────────

_ROW_BASE = {
    "symbol": "TCS", "period_end": "2024-12-31",
    "fiscal_label": "Q3FY25", "consolidated": 1,
    "revenue_cr": 63973.0, "ebitda_cr": 18277.0, "opm_pct": 28.57,
    "pbt_cr": 16666.0, "pat_cr": 12444.0, "eps": 34.21,
    "source": "xbrl", "xbrl_url": "https://nsearchives.nseindia.com/x.xml",
    "verified": 1, "_bcast": "09-Jan-2025 21:39:43",
}
_DELTAS = {
    "yoy_revenue_pct": 4.5, "yoy_ebitda_pct": 3.1, "yoy_pbt_pct": 5.0, "yoy_pat_pct": 5.2,
    "qoq_revenue_pct": 1.2, "qoq_ebitda_pct": 0.9, "qoq_pbt_pct": 0.8, "qoq_pat_pct": 0.8,
    "yoy_opm_bps": -40.0, "qoq_opm_bps": 10.0,
}


def _thread():
    _, thread = _build_thread({**_ROW_BASE, **_DELTAS}, _ROW_BASE["_bcast"])
    return thread


def _record():
    return _build_record(_ROW_BASE, _DELTAS)


# ── fiscal label + period string ──────────────────────────────────────────────

def test_fiscal_label_q3():
    assert _fiscal_label(date(2024, 12, 31)) == "Q3FY25"


def test_fiscal_label_q4():
    assert _fiscal_label(date(2025, 3, 31)) == "Q4FY25"


def test_fiscal_label_q1():
    assert _fiscal_label(date(2025, 6, 30)) == "Q1FY26"


def test_fiscal_label_q2():
    assert _fiscal_label(date(2025, 9, 30)) == "Q2FY26"


def test_period_str_q3():
    from monitor.earnings_post import _period_str
    assert _period_str("2024-12-31") == "Oct-Dec 2024"


# ── delta math ────────────────────────────────────────────────────────────────

def test_pct_delta_positive():
    assert abs(_pct_delta(63973.0, 61298.5) - 4.4) < 0.05


def test_pct_delta_none_when_no_prev():
    assert _pct_delta(63973.0, None) is None


def test_pct_delta_none_when_zero_prev():
    assert _pct_delta(100.0, 0.0) is None


# ── thread format: NUMBERS ONLY, no sentiment/verdict/adjective ───────────────

_BANNED = re.compile(
    r"\b(buy|sell|hold|strong|bullish|bearish|beat|miss|solid|blockbuster|"
    r"great|excellent|disappoint|below.?expect|above.?expect|outperform|"
    r"underperform|recommend|target|avoid|accumulate|rating|verdict|"
    r"overweight|underweight)\b",
    re.IGNORECASE,
)

def test_thread_no_sentiment_or_verdict():
    t = _thread()
    m = _BANNED.search(t)
    assert m is None, f"banned word '{m.group()}' in thread: {t!r}"


def test_thread_has_x_section():
    _, thread = _build_thread({**_ROW_BASE, **_DELTAS}, _ROW_BASE["_bcast"])
    # The thread must have **1/** **2/** **3/** markers
    assert "**1/**" in thread
    assert "**2/**" in thread


def test_thread_has_symbol_and_label():
    t = _thread()
    assert "TCS" in t
    assert "Q3FY25" in t


def test_thread_has_revenue():
    t = _thread()
    assert "63,973" in t or "63973" in t


def test_thread_has_pat():
    t = _thread()
    assert "12,444" in t or "12444" in t


def test_thread_has_eps():
    t = _thread()
    assert "34.21" in t


def test_thread_no_emdash():
    t = _thread()
    assert "—" not in t and "–" not in t


def test_tweets_under_280_chars():
    t = _thread()
    for i, tweet in enumerate(t.split("\n\n"), 1):
        clean = re.sub(r"^\*\*\d+/\*\*\s*", "", tweet).strip()
        assert len(clean) <= 280, f"tweet {i} exceeds 280 chars ({len(clean)}): {clean!r}"


# ── value gate: happy path and tamper detection ───────────────────────────────

def test_value_gate_passes_correct_thread():
    ok, why = verify_earnings(_thread(), _record())
    assert ok, f"happy path blocked: {why}"


def test_value_gate_blocks_tampered_crore():
    t = _thread().replace("₹63,973 cr", "₹70,000 cr")
    ok, why = verify_earnings(t, _record())
    assert not ok and "orphan" in why, f"tampered crore should block: ok={ok} why={why}"


def test_value_gate_blocks_tampered_yoy():
    t = _thread().replace("+4.5% YoY", "+15.0% YoY")
    ok, why = verify_earnings(t, _record())
    assert not ok and "YOY" in why.upper(), f"tampered YoY should block: ok={ok} why={why}"


def test_value_gate_blocks_no_record():
    ok, why = verify_earnings(_thread(), None)
    assert not ok and "no SOURCE" in why


def test_value_gate_blocks_unverified():
    bad_rec = {**_record(), "verified": 0}
    ok, why = verify_earnings(_thread(), bad_rec)
    assert not ok and "not verified" in why


def test_value_gate_passes_no_deltas_when_absent_from_record():
    """If no prior quarter → deltas absent from record and absent from thread: still passes."""
    row = {**_ROW_BASE}
    deltas_empty = {k: None for k in _DELTAS}
    _, thread = _build_thread({**row, **deltas_empty}, row["_bcast"])
    rec = _build_record(row, deltas_empty)
    ok, why = verify_earnings(thread, rec)
    assert ok, f"no-delta happy path blocked: {why}"


# ── SEBI lint gate (no directional words near ticker in deterministic output) ──

def test_sebi_lint_passes():
    from compliance.lint import is_safe
    newsletter, thread = _build_thread({**_ROW_BASE, **_DELTAS}, _ROW_BASE["_bcast"])
    assert is_safe(newsletter + "\n" + thread), "SEBI lint blocked deterministic earnings text"


# ── source record structure ───────────────────────────────────────────────────

def test_source_record_has_required_keys():
    rec = _record()
    for key in ("symbol", "period_end", "fiscal_label", "consolidated",
                "revenue_cr", "ebitda_cr", "opm_pct", "pbt_cr", "pat_cr",
                "eps", "source", "xbrl_url", "verified"):
        assert key in rec, f"SOURCE record missing key: {key}"


def test_source_record_verified_flag():
    rec = _record()
    assert rec["verified"] == 1


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1; print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
