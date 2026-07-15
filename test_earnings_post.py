#!/usr/bin/env python3
"""Tests for the earnings lane: format correctness, math, and the value gate.

Run:  python3 test_earnings_post.py   (exits nonzero on failure; pytest-discoverable)
"""
import json, re, sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import io, contextlib
import monitor.earnings_post as earnings_post
from monitor.earnings_post import (
    _fiscal_label, _period_str, _pct_delta, _build_thread, _build_record, _write_draft,
    write_lane_health,
)
from compliance.earnings_check import verify_earnings, is_fresh
from datetime import date, datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))

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


def test_source_record_carries_broadcast_timestamp():
    # the freshness gate needs the full broadcast timestamp (with time), not just the date
    rec = _record()
    assert rec.get("bcast_date") == "09-Jan-2025 21:39:43"


# ── freshness / relevance gate (Srijan's rule: same-day, or late-evening → next-morning) ──

def test_freshness_same_day():
    assert is_fresh("09-Jan-2025 21:39:43", datetime(2025, 1, 9, 22, 0, tzinfo=_IST))[0]


def test_freshness_late_evening_posts_next_morning():
    assert is_fresh("09-Jan-2025 21:39:43", datetime(2025, 1, 10, 8, 30, tzinfo=_IST))[0]


def test_freshness_stale_by_next_afternoon():
    ok, why = is_fresh("09-Jan-2025 21:39:43", datetime(2025, 1, 10, 14, 0, tzinfo=_IST))
    assert not ok and "stale" in why


def test_freshness_daytime_filing_stale_next_morning():
    # only a LATE-evening filing gets the next-morning carve-out; a 10am filing does not
    assert not is_fresh("09-Jan-2025 10:00:00", datetime(2025, 1, 10, 8, 30, tzinfo=_IST))[0]


def test_freshness_two_days_old_stale():
    assert not is_fresh("09-Jan-2025 21:39:43", datetime(2025, 1, 11, 9, 0, tzinfo=_IST))[0]


def test_freshness_missing_timestamp_fail_closed():
    now = datetime(2025, 1, 9, 22, 0, tzinfo=_IST)
    assert not is_fresh("", now)[0]
    assert not is_fresh(None, now)[0]


# ── idempotency: a result's draft id is STABLE (no date), so evening + next-morning can't double-post ──

def _dry_body(today_iso: str) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _write_draft({**_ROW_BASE}, {**_DELTAS}, today_iso, dry_run=True)
    return buf.getvalue()


def test_draft_id_is_stable_across_run_days():
    b1, b2 = _dry_body("2025-01-09"), _dry_body("2025-01-10")
    # frontmatter id is the same on both run days (the idempotency key)...
    assert "id: earnings-tcs-q3fy25" in b1, b1[:300]
    assert "id: earnings-tcs-q3fy25" in b2
    # ...while the FILENAME stays dated (lane-slug + generated-day gating)
    assert "2025-01-09-earnings-tcs-q3fy25.md" in b1
    assert "2025-01-10-earnings-tcs-q3fy25.md" in b2


# ── session reuse: ONE NSEXbrlFetcher per run (the 403-storm fix) ─────────────

def test_session_reuse_single_fetcher_across_symbols():
    """run_today must construct NSEXbrlFetcher exactly once and pass it to all symbol fetches."""
    from unittest.mock import patch, MagicMock
    import monitor.earnings_post as ep

    fetcher_instances_passed = []

    def fake_fetch_and_parse(symbol, fresh_now=None, fetcher=None, nse_calls=None):
        fetcher_instances_passed.append(fetcher)
        return []   # no filings — fast

    with patch.object(ep, '_load_universe', return_value=["TCS", "INFY", "RELIANCE"]), \
         patch.object(ep, '_fetch_and_parse_filings', side_effect=fake_fetch_and_parse), \
         patch.object(ep, 'in_results_season', return_value=True), \
         patch.object(ep, '_open_db', return_value=MagicMock(close=lambda: None)):
        now = datetime(2026, 7, 15, 20, 0, tzinfo=_IST)
        ep.run_today(now, dry_run=True)

    assert len(fetcher_instances_passed) == 3, f"expected 3 calls, got {len(fetcher_instances_passed)}"
    # All symbols received the SAME fetcher object (constructed once, not per symbol)
    f0 = fetcher_instances_passed[0]
    assert f0 is not None
    assert all(f is f0 for f in fetcher_instances_passed), \
        "fetcher must be the SAME instance across all symbol calls"


def test_integrated_filing_shape_flows_to_q1fy27_row():
    from types import SimpleNamespace
    import monitor.earnings_post as ep

    filing = SimpleNamespace(
        xbrl_url="https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1691776_13072026072058_WEB.xml",
        period="30-JUN-2026",
        broad_cast_date="14-Jul-2026 19:17:07",
        raw={"consolidated": "Consolidated"},
    )
    fake_fetcher = SimpleNamespace(
        fetch_financial_results=lambda symbol, period="Quarterly": [filing],
        download_xbrl=lambda url: b"<xml/>",
        parse_xbrl=lambda content: {
            "revenue_cr": 34579.0,
            "pat_cr": 4626.0,
            "eps": 17.09,
            "ebitda_cr": 7231.0,
            "pbt_cr": 6108.0,
            "opm_pct": 20.91,
        },
    )

    with patch.object(ep, "_try_cross_validate", lambda *a, **k: 1):
        rows = ep._fetch_and_parse_filings(
            "HCLTECH",
            fresh_now=datetime(2026, 7, 14, 20, 0, tzinfo=_IST),
            fetcher=fake_fetcher,
        )

    assert len(rows) == 1
    row = rows[0]
    assert row["period_end"] == "2026-06-30"
    assert row["fiscal_label"] == "Q1FY27"
    assert row["consolidated"] == 1
    assert row["revenue_cr"] == 34579.0
    assert row["verified"] == 1
    assert row["_bcast"] == "14-Jul-2026 19:17:07"


def test_screener_parse_takes_latest_quarter_from_button_markup():
    # Live markup shape 2026-07-15: label inside a showSchedule button, cells whitespace-padded,
    # columns oldest→newest. The parser must take the LAST cell (newest quarter), not the first.
    html = """
    <table><tbody>
      <tr class="stripe">
        <td class="text">
          <button class="button-plain" onclick="Company.showSchedule('Sales', 'quarters', this)">
            Sales&nbsp;<span class="blue-icon">+</span>
          </button>
        </td>
        <td class="highlight-cell">
          26,296
        </td>
        <td class="">
          33,981
        </td>
        <td class="">
          34,579
        </td>
      </tr>
      <tr>
        <td class="text">
          <button class="button-plain" onclick="Company.showSchedule('Net Profit', 'quarters', this)">
            Net Profit&nbsp;<span class="blue-icon">+</span>
          </button>
        </td>
        <td class="highlight-cell">
          3,531
        </td>
        <td class="">
          4,626
        </td>
      </tr>
    </tbody></table>
    """
    out = earnings_post._parse_screener_quarterly(html)
    assert out == {"revenue_cr": 34579.0, "pat_cr": 4626.0}


def test_screener_parse_fails_closed_on_structure_drift():
    assert earnings_post._parse_screener_quarterly("<html><body>nothing here</body></html>") is None


# ── cross-validate: verified=0 blocks posting ─────────────────────────────────

def test_cross_validate_zero_when_screener_unavailable():
    """_try_cross_validate returns 0 when Screener is unavailable → fail-closed."""
    import monitor.earnings_post as ep
    from unittest.mock import patch

    with patch.object(ep, '_screener_key_metrics', return_value=None):
        result = ep._try_cross_validate("TCS", {"revenue_cr": 63973.0, "pat_cr": 12444.0}, None)
    assert result == 0, "unavailable second source must return verified=0"


def test_cross_validate_zero_when_values_disagree():
    """_try_cross_validate returns 0 when Screener disagrees > 10% (SUSPICIOUS)."""
    import monitor.earnings_post as ep
    from unittest.mock import patch

    # Screener says revenue is wildly different → cross_validate returns SUSPICIOUS
    screener = {"revenue_cr": 5000.0, "pat_cr": 1000.0}  # vs xbrl 63973 / 12444 → >10% diff
    with patch.object(ep, '_screener_key_metrics', return_value=screener):
        result = ep._try_cross_validate("TCS", {"revenue_cr": 63973.0, "pat_cr": 12444.0}, None)
    assert result == 0, "SUSPICIOUS diff must return verified=0"


def test_verified_zero_blocks_verify_earnings():
    """verify_earnings must block a record where verified=0 (the fail-closed gate)."""
    from compliance.earnings_check import verify_earnings
    _, thread = _build_thread({**_ROW_BASE, **_DELTAS}, _ROW_BASE["_bcast"])
    bad_rec = {**_build_record(_ROW_BASE, _DELTAS), "verified": 0}
    ok, why = verify_earnings(thread, bad_rec)
    assert not ok and "not verified" in why


# ── in_results_season ─────────────────────────────────────────────────────────

def test_in_results_season_mid_july():
    from monitor.earnings_post import in_results_season
    assert in_results_season(date(2025, 7, 15)), "Jul 15 is in Q1 results season"


def test_in_results_season_all_of_august():
    from monitor.earnings_post import in_results_season
    assert in_results_season(date(2025, 8, 1))
    assert in_results_season(date(2025, 8, 31))


def test_in_results_season_february():
    from monitor.earnings_post import in_results_season
    assert in_results_season(date(2025, 2, 15)), "Feb is Q3 results season"


def test_in_results_season_false_march():
    from monitor.earnings_post import in_results_season
    assert not in_results_season(date(2025, 3, 1)), "Mar is off-season"
    assert not in_results_season(date(2025, 3, 31)), "Mar is off-season"


def test_in_results_season_false_june():
    from monitor.earnings_post import in_results_season
    assert not in_results_season(date(2025, 6, 1)), "Jun is off-season"


def test_in_results_season_false_early_july():
    from monitor.earnings_post import in_results_season
    assert not in_results_season(date(2025, 7, 9)), "Jul 9 is before season start (Jul 10)"


def test_in_results_season_false_december():
    from monitor.earnings_post import in_results_season
    assert not in_results_season(date(2025, 12, 15)), "Dec is off-season"


def test_earnings_lane_has_no_trading_day_gate():
    """Pin 2026-07-12: filings land on weekends (Sat 2026-07-11: DMart/LTM/Avantel) —
    the earnings-treum run.sh block must NOT gate on trading_day; premarket/wrap lanes keep it."""
    run_sh = (Path(__file__).resolve().parent / "x" / "cron" / "run.sh").read_text()
    block = run_sh.split("earnings-treum)", 1)[1].split(";;", 1)[0]
    assert "trading_day ||" not in block, "earnings-treum must run 7 days/week (weekend filings)"
    assert "trading_day ||" in run_sh, "the session lanes' trading_day gate must stay"


class EarningsHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine_dir = Path(self.tmp.name)
        self.x_dir = self.engine_dir / "x"
        self.x_dir.mkdir()
        self.health_file = self.x_dir / "earnings_lane_health.json"
        self.live_flag = self.x_dir / "EARNINGS_TREUM_LIVE"
        self.status_file = self.x_dir / "x-cron-status.md"

        for target, value in (
            ("ENGINE_DIR", self.engine_dir),
            ("HEALTH_FILE", self.health_file),
            ("LIVE_FLAG", self.live_flag),
        ):
            patcher = patch.object(earnings_post, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def outcomes(self, **overrides):
        values = {
            "fetch_attempts": 0,
            "fetch_successes": 0,
            "fetch_failures": 0,
            "filings_found": 0,
            "drafts_written": 0,
            "last_error": None,
            "is_403": False,
        }
        values.update(overrides)
        return values

    def health(self):
        return json.loads(self.health_file.read_text())

    def status(self):
        return self.status_file.read_text() if self.status_file.exists() else ""

    def test_off_season_empty_run_does_not_increment_or_escalate(self):
        self.live_flag.touch()
        with patch.object(earnings_post, "in_results_season", lambda *a: False):
            write_lane_health(self.outcomes(fetch_attempts=5, fetch_successes=5))
        self.assertEqual(self.health()["consecutive_empty_runs"], 0)
        self.assertNotIn("FAILED", self.status())

    def test_partial_failure_in_season_increments_without_total_failure(self):
        self.live_flag.touch()
        with patch.object(earnings_post, "in_results_season", lambda *a: True):
            write_lane_health(self.outcomes(fetch_attempts=10, fetch_successes=7, fetch_failures=3))
        self.assertEqual(self.health()["consecutive_empty_runs"], 1)
        self.assertNotIn("total-failure", self.status())

    def test_total_failure_escalates_only_when_live(self):
        self.live_flag.touch()
        write_lane_health(self.outcomes(fetch_attempts=10, fetch_failures=10))
        self.assertIn("FAILED earnings-treum", self.status())
        self.assertIn("total-failure", self.status())

        self.status_file.unlink()
        self.live_flag.unlink()
        write_lane_health(self.outcomes(fetch_attempts=10, fetch_failures=10))
        self.assertEqual(self.status(), "")

    def test_403_escalates_and_records_iso_timestamp(self):
        self.live_flag.touch()
        write_lane_health(self.outcomes(fetch_attempts=1, fetch_failures=1, is_403=True))
        self.assertIn("FAILED earnings-treum", self.status())
        self.assertIn("403", self.status())
        self.assertIsNotNone(self.health()["last_403"])
        datetime.fromisoformat(self.health()["last_403"])

    def test_three_in_season_empty_runs_escalate_then_filing_resets(self):
        self.live_flag.touch()
        empty = self.outcomes(fetch_attempts=1, fetch_successes=1)
        with patch.object(earnings_post, "in_results_season", lambda *a: True):
            write_lane_health(empty)
            write_lane_health(empty)
            write_lane_health(empty)
            self.assertIn("consecutive-empty-runs=3", self.status())
            write_lane_health(self.outcomes(fetch_attempts=1, fetch_successes=1, filings_found=1))
        self.assertEqual(self.health()["consecutive_empty_runs"], 0)

    def test_health_schema_is_complete_and_last_run_is_iso(self):
        write_lane_health(self.outcomes(fetch_attempts=1, fetch_successes=1))
        health = self.health()
        self.assertTrue({
            "last_run", "last_fetch_ok", "last_403", "last_error",
            "fetch_attempts", "fetch_successes", "fetch_failures", "filings_found",
            "drafts_written", "consecutive_empty_runs",
        }.issubset(health))
        datetime.fromisoformat(health["last_run"])

    def test_source_has_no_not_an_nse_trading_day_guard(self):
        source = Path(earnings_post.__file__).read_text()
        self.assertNotIn("not an NSE trading day", source)


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
