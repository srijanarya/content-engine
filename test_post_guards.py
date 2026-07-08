#!/usr/bin/env python3
"""Guards the 2026-06-23 incidents so they can't recur:
  - FLOOD/ORDER: post_x must post ONE lane's TODAY draft only, never a backlog / prior-day / wrong-lane.
  - PER-COMPANY: post_x must never post a finance draft that is ABOUT a single listed company (SEBI).

Run:  python3 test_post_guards.py   (prints PASS/FAIL, exits nonzero on failure; pytest-discoverable)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
px = pytest.importorskip("post_x")  # local-only module (gitignored); skip in CI

TODAY = "2026-06-23"


def fm(status="needs-review", engine="finance", generated=TODAY, topic="daily market wrap 2026-06-23"):
    return {"status": status, "engine": engine, "generated": generated, "topic": topic}


# ── per-company title guard ──
def test_blocks_tcs_title():
    assert px.names_company("Tata Consultancy Services Limited Financ",
                            "2026-06-23-finance-tata-consultancy-services-limited-financ.md")


def test_blocks_hcl_title():
    assert px.names_company("HCL Technologies Limited financial resul",
                            "2026-06-21-finance-hcl-technologies-limited-financial-resul.md")


def test_blocks_bare_ticker_title():
    assert px.names_company("INFY Q4FY26 read", "2026-06-20-finance-infy-q4fy26.md")


def test_allows_sector_wrap_titles():
    assert not px.names_company("daily market wrap 2026-06-23", "2026-06-23-finance-daily-market-wrap.md")
    assert not px.names_company("pre-market note 2026-06-23", "2026-06-23-finance-premarket-note.md")
    assert not px.names_company("evening wrap 2026-06-23", "2026-06-23-finance-evening-wrap.md")


# ── eligibility: one lane, today only, no per-company ──
def test_picks_todays_lane_draft():
    assert px.eligible("2026-06-23-finance-premarket-note.md", fm(topic="pre-market note 2026-06-23"),
                       lane_slug="premarket-note", today=TODAY, auto_approve=True)


def test_rejects_other_lane_draft():
    # asking for the premarket lane must NOT select the daily-wrap draft (the out-of-order flood)
    assert not px.eligible("2026-06-23-finance-daily-market-wrap.md", fm(),
                           lane_slug="premarket-note", today=TODAY, auto_approve=True)


def test_rejects_prior_day_backlog():
    # yesterday's stuck evening wrap must never post today (the backlog flush)
    assert not px.eligible("2026-06-22-finance-evening-wrap.md",
                           fm(generated="2026-06-22", topic="evening wrap 2026-06-22"),
                           lane_slug="evening-wrap", today=TODAY, auto_approve=True)


def test_rejects_already_posted():
    assert not px.eligible("2026-06-23-finance-premarket-note.md", fm(status="posted"),
                           lane_slug="premarket-note", today=TODAY, auto_approve=True)


def test_rejects_per_company_draft_even_when_fresh():
    # a per-company finance draft must never be eligible, even fresh + matching slug + auto
    assert not px.eligible("2026-06-23-finance-tata-consultancy-services-limited-financ.md",
                           fm(topic="Tata Consultancy Services Limited Financ"),
                           lane_slug="tata-consultancy", today=TODAY, auto_approve=True)


def test_auto_only_lifts_finance_needs_review():
    # auto mode auto-approves finance needs-review ONLY; an ai-world needs-review draft is not eligible
    assert not px.eligible("2026-06-23-ai-worl-something.md", fm(engine="ai-world", topic="some ai topic"),
                           lane_slug=None, today=TODAY, auto_approve=True)


# ── thread-marker parsing: BOTH generator formats (own-line + same-line) ──
_THREAD_HEADER = "## X / TWITTER THREAD\n\n"


def test_parse_thread_own_line_markers():
    # the format the daily wraps emit: **N/** on its own line, text on the next
    text = _THREAD_HEADER + "**1/**\nFirst tweet body.\n\n**2/**\nSecond tweet body.\n"
    tweets = px.parse_thread(text)
    # 2 numbered + the auto-appended disclaimer
    assert tweets[:2] == ["First tweet body.", "Second tweet body."], tweets
    assert px.SHORT_DISCLAIMER in tweets[-1]


def test_parse_thread_same_line_markers():
    # the format the backtest-education draft emitted, which used to parse to ZERO tweets
    # (silent skip at post time) before the fix.
    text = _THREAD_HEADER + "**1/** First tweet body.\n\n**2/** Second tweet body.\n"
    tweets = px.parse_thread(text)
    assert tweets[:2] == ["First tweet body.", "Second tweet body."], tweets
    assert px.SHORT_DISCLAIMER in tweets[-1]


def test_parse_thread_same_line_keeps_multiline_tweet_intact():
    # a same-line marker whose tweet has its own internal newlines (tweet 6 of the education
    # draft: a marker line then a list of p-values) must stay ONE tweet, not fragment.
    text = _THREAD_HEADER + "**1/** Results:\nVRP: p=0.038\nORB: failed\n\n**2/** Next tweet.\n"
    tweets = px.parse_thread(text)
    assert tweets[0] == "Results:\nVRP: p=0.038\nORB: failed", tweets
    assert tweets[1] == "Next tweet."


def test_parse_thread_no_section_returns_empty():
    assert px.parse_thread("## NEWSLETTER\n\nno thread here\n") == []


def test_daily_cap_is_srijans_authorized_value():
    # The cap value IS the authorization (Srijan's OK 2026-07-05, 3 -> 4 so a special post fits
    # alongside the daily trio). Changing this number means getting his OK first, like the factory
    # HeyGen budget caps — this test is the tripwire.
    assert px.MAX_THREADS_PER_DAY == 4


# ── GATE 3 per-lane value-check dispatch (check_values_for_lane) ──
def test_pulse_lane_skips_index_value_check():
    # Regression: the deterministic market-pulse thread carries breadth %s like "IT (85%)". The index
    # value_check reads the % after a sector code as that sector's PRICE move, so it false-blocked the
    # pulse. The pulse lane must bypass the index gate (it is hard-lint-gated at generation, no LLM step,
    # and carries no NIFTY headline). It must pass even with no regime present.
    ok, _ = px.check_values_for_lane("finance", "market-pulse", "Widest breadth: IT (85%). Thinnest: PSU (12%).")
    assert ok


def test_pulse_detected_by_filename_too():
    # A manual run may not pass --lane-slug; the filename marker "-market-pulse" also exempts it.
    class P:  # minimal path stub with a .name
        name = "2026-07-09-finance-market-pulse.md"
    ok, _ = px.check_values_for_lane("finance", None, "Widest breadth: IT (85%).", P())
    assert ok


def test_finance_wrap_still_value_checked():
    # The fake-NIFTY backstop must stay intact for the wrap/premarket/evening lanes: a sign-flipped
    # NIFTY vs the regime still BLOCKS. (fixture-free so the __main__ runner passes too.)
    import json, os, tempfile
    p = os.path.join(tempfile.mkdtemp(), "r.json")
    with open(p, "w") as f:
        json.dump({"nifty_change_pct": 0.83}, f)
    old = os.environ.get("REGIME_JSON")
    os.environ["REGIME_JSON"] = p
    try:
        ok, why = px.check_values_for_lane("finance", "daily-market-wrap", "NIFTY closed -0.61% today.")
    finally:
        os.environ.pop("REGIME_JSON", None) if old is None else os.environ.__setitem__("REGIME_JSON", old)
    assert not ok and "NIFTY" in why, why


def test_non_finance_lane_has_no_value_gate():
    # the audit lane (non-finance) carries no market numbers; the dispatch is a no-op.
    ok, _ = px.check_values_for_lane("audit", "audit", "Free teardown of your backtest. DM to grab it.")
    assert ok


# ── earnings lane carve-outs (Phase B) ──
def test_earnings_engine_is_eligible_despite_naming_company():
    # earnings engine is NOT subject to the names_company per-company block:
    # the eligible() guard only blocks engine == "finance". Auto-approve must also work.
    assert px.eligible(
        "2026-07-09-earnings-tcs-q3fy25.md",
        {"status": "needs-review", "engine": "earnings",
         "generated": TODAY, "topic": "TCS Q3FY25 results"},
        lane_slug="earnings", today=TODAY, auto_approve=True,
    )


def test_earnings_engine_auto_approved():
    # needs-review + engine: earnings + auto_approve=True must be eligible (auto-forever path)
    fm_earn = {"status": "needs-review", "engine": "earnings",
               "generated": TODAY, "topic": "RELIANCE Q3FY25 results"}
    assert px.eligible("2026-07-09-earnings-reliance-q3fy25.md", fm_earn,
                       lane_slug="earnings", today=TODAY, auto_approve=True)


def test_earnings_gate3_routes_to_verify_earnings_not_index_check():
    # GATE 3 for engine=earnings must NOT call the NIFTY index gate.
    # It calls verify_earnings; with no SOURCE block it blocks (no record), NOT the NIFTY path.
    ok, why = px.check_values_for_lane("earnings", "earnings",
                                       "TCS Q3FY25: Revenue ₹63,973 cr (+4.5% YoY)")
    # no path supplied → no SOURCE block → verify_earnings returns (False, "no SOURCE record ...")
    assert not ok and "SOURCE" in why, f"expected SOURCE block error, got: ok={ok} why={why!r}"


def test_earnings_gate3_passes_with_valid_source():
    # Verify the full gate-3 round-trip: craft a minimal draft file, pass its Path, confirm ok.
    import json, tempfile, os
    from pathlib import Path
    from compliance.earnings_check import verify_earnings
    rec = {
        "symbol": "TCS", "period_end": "2024-12-31", "fiscal_label": "Q3FY25",
        "consolidated": 1, "revenue_cr": 63973.0, "ebitda_cr": 18277.0, "opm_pct": 28.57,
        "pbt_cr": 16666.0, "pat_cr": 12444.0, "eps": 34.21,
        "yoy_revenue_pct": 4.5, "yoy_pat_pct": 5.2,
        "qoq_revenue_pct": 1.2, "qoq_pat_pct": 0.8,
        "source": "xbrl", "xbrl_url": "", "verified": 1, "bcast_date": "",
    }
    thread = (
        "TCS Q3FY25 (Consolidated):\n"
        "Revenue: ₹63,973 cr (+4.5% YoY, +1.2% QoQ)\n"
        "EBITDA: ₹18,277 cr | OPM: 28.6%\n\n"
        "PAT: ₹12,444 cr (+5.2% YoY, +0.8% QoQ)\n"
        "EPS: 34.21\nPBT: ₹16,666 cr"
    )
    draft_body = (
        "---\nengine: earnings\n---\n\n"
        f"## X / TWITTER THREAD\n\n{thread}\n\n"
        f"## SOURCE\n\n```json\n{json.dumps(rec)}\n```\n"
    )
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    tmp.write(draft_body); tmp.close()
    try:
        class P:
            name = os.path.basename(tmp.name)
            def read_text(self): return open(tmp.name).read()
        ok, why = px.check_values_for_lane("earnings", "earnings", thread, P())
        assert ok, f"valid earnings draft blocked at GATE 3: {why}"
    finally:
        os.unlink(tmp.name)


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
